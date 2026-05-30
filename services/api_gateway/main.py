"""
API Gateway Service (Enterprise)
==================================
Single entry point for all client requests. Enterprise additions:
  - JWT authentication (register / login / me endpoints)
  - Per-user document history (SQLite, 10 graphs/user max)
  - Proper SCAN-based Redis iteration (replaces O(N) KEYS)
  - ingestion_start timestamp for latency tracking
  - Per-user rate limiting (max 2 active jobs)
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator, List, Optional

import aiofiles
import redis.asyncio as aioredis
import structlog
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel

from auth import (
    TokenData,
    create_access_token,
    get_current_user,
    get_current_user_optional,
    hash_password,
    verify_password,
)
from database import (
    add_document_to_history,
    create_user,
    delete_user_document,
    get_user_by_id,
    get_user_by_username,
    get_user_history,
    init_db,
    close_db,
    update_document_stats,
)

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

UPLOAD_DIR  = Path(os.getenv("UPLOAD_DIR", "/app/uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

REDIS_URL    = os.getenv("REDIS_URL", "redis://redis:6379/0")
REDIS_STREAM = os.getenv("REDIS_STREAM", "document.ingested")

MAX_ACTIVE_JOBS_PER_USER = 2  # fair-use limit per user

log = structlog.get_logger("api_gateway")

# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

redis_client: aioredis.Redis | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client
    redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)
    await init_db()
    log.info("api_gateway_started", redis=REDIS_URL)

    # ── Launch all microservice workers inside this process ─────────────────
    worker_tasks = []
    try:
        from workers import start_all_workers
        worker_tasks = await start_all_workers()
        log.info("monolith_workers_started", count=len(worker_tasks))
    except Exception as exc:
        log.error("worker_launch_failed", error=str(exc))

    yield

    # ── Graceful shutdown ────────────────────────────────────────────────────
    for t in worker_tasks:
        t.cancel()
    if worker_tasks:
        await asyncio.gather(*worker_tasks, return_exceptions=True)
    await close_db()
    await redis_client.aclose()



app = FastAPI(
    title="MindMap API Gateway",
    version="2.0.0",
    description="Distributed Mind Map Generator — Enterprise API Gateway",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

import traceback

@app.exception_handler(Exception)
async def debug_exception_handler(request, exc):
    if isinstance(exc, HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail}
        )
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    log.error("unhandled_error", error=str(exc), traceback=tb)
    return JSONResponse(
        status_code=500,
        content={
            "detail": f"Unhandled error: {str(exc)}",
            "traceback": tb
        }
    )

# ---------------------------------------------------------------------------
# WebSocket connection manager
# ---------------------------------------------------------------------------

class ConnectionManager:
    def __init__(self):
        self._connections: dict[str, list[WebSocket]] = {}

    async def connect(self, ws: WebSocket, document_id: str):
        await ws.accept()
        self._connections.setdefault(document_id, []).append(ws)

    def disconnect(self, ws: WebSocket, document_id: str):
        conns = self._connections.get(document_id, [])
        if ws in conns:
            conns.remove(ws)

    async def broadcast(self, document_id: str, message: dict):
        for ws in list(self._connections.get(document_id, [])):
            try:
                await ws.send_json(message)
            except Exception:
                pass


manager = ConnectionManager()

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    username: str
    password: str
    email: Optional[str] = None

class LoginRequest(BaseModel):
    username: str
    password: str

# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------

@app.post("/api/auth/register")
async def register(req: RegisterRequest):
    if len(req.username) < 3 or len(req.username) > 30:
        raise HTTPException(400, "Username must be 3-30 characters")
    if len(req.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")

    password_hash = hash_password(req.password)
    user = await create_user(req.username, password_hash, req.email)
    if not user:
        raise HTTPException(409, "Username already taken")

    token = create_access_token(user["id"], user["username"])
    log.info("user_registered", username=req.username)
    return {
        "access_token": token,
        "token_type":   "bearer",
        "user": {"id": user["id"], "username": user["username"]},
    }


@app.post("/api/auth/login")
async def login(req: LoginRequest):
    user = await get_user_by_username(req.username)
    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(401, "Invalid username or password")

    token = create_access_token(user["id"], user["username"])
    log.info("user_logged_in", username=req.username)
    return {
        "access_token": token,
        "token_type":   "bearer",
        "user": {"id": user["id"], "username": user["username"]},
    }


@app.get("/api/auth/me")
async def get_me(current_user: TokenData = Depends(get_current_user)):
    user = await get_user_by_id(current_user.user_id)
    if not user:
        raise HTTPException(404, "User not found")
    return user

# ---------------------------------------------------------------------------
# History endpoints
# ---------------------------------------------------------------------------

@app.get("/api/v1/history")
async def get_history(current_user: TokenData = Depends(get_current_user)):
    """Return the authenticated user's document history (newest first, max 10)."""
    docs = await get_user_history(current_user.user_id)
    return {"documents": docs, "total": len(docs)}


@app.delete("/api/v1/history/{document_id}")
async def delete_from_history(
    document_id: str,
    current_user: TokenData = Depends(get_current_user),
):
    """Remove a document from the user's history."""
    deleted = await delete_user_document(document_id, current_user.user_id)
    if not deleted:
        raise HTTPException(404, "Document not found in your history")
    return {"success": True, "document_id": document_id}

# ---------------------------------------------------------------------------
# Core pipeline endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "service": "api_gateway", "version": "2.0.0"}


@app.post("/api/v1/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    current_user: Optional[TokenData] = Depends(get_current_user_optional),
):
    """
    Accept document upload and enqueue for processing.
    If authenticated, adds to user history immediately.
    """
    allowed = {".pdf", ".txt", ".md"}
    ext = Path(file.filename or "").suffix.lower()
    if ext not in allowed:
        raise HTTPException(400, f"Unsupported file type: {ext}. Allowed: {', '.join(allowed)}")

    # Per-user active job limit
    if current_user:
        active_key = f"active_jobs:{current_user.user_id}"
        active = await redis_client.get(active_key)
        if active and int(active) >= MAX_ACTIVE_JOBS_PER_USER:
            raise HTTPException(
                429,
                f"You have {MAX_ACTIVE_JOBS_PER_USER} documents processing. Please wait."
            )

    document_id = str(uuid.uuid4())
    dest        = UPLOAD_DIR / f"{document_id}{ext}"

    async with aiofiles.open(dest, "wb") as f:
        while chunk := await file.read(1024 * 256):
            await f.write(chunk)

    file_size   = dest.stat().st_size
    now         = datetime.utcnow().isoformat()
    log.info("document_uploaded", document_id=document_id, filename=file.filename, size=file_size)

    await redis_client.xadd(
        REDIS_STREAM,
        {
            "document_id":  document_id,
            "storage_path": str(dest),
            "filename":     file.filename or "unknown",
            "file_type":    ext.lstrip("."),
            "file_size":    str(file_size),
            "user_id":      current_user.user_id if current_user else "",
        },
        maxlen=10000,
    )

    await redis_client.setex(
        f"job:state:{document_id}",
        86400,
        json.dumps({
            "job_id":                 document_id,
            "document_id":            document_id,
            "status":                 "pending",
            "total_chunks":           0,
            "chunks_completed":       0,
            "agent_results_received": 0,
            "progress_pct":           0.0,
            "ingestion_start":        now,         # FIX: was missing before
            "user_id":                current_user.user_id if current_user else None,
            "filename":               file.filename,
        }),
    )

    # Add to history immediately so user can track it
    if current_user:
        await add_document_to_history(
            user_id=current_user.user_id,
            document_id=document_id,
            filename=file.filename or "unknown",
        )
        # Track active job count (TTL 20 min)
        pipe = redis_client.pipeline()
        pipe.incr(f"active_jobs:{current_user.user_id}")
        pipe.expire(f"active_jobs:{current_user.user_id}", 1200)
        await pipe.execute()

    return {"document_id": document_id, "filename": file.filename, "status": "queued"}


@app.get("/api/v1/documents/{document_id}/status")
async def get_job_status(document_id: str):
    raw = await redis_client.get(f"job:state:{document_id}")
    if raw is None:
        raise HTTPException(404, "Document not found")
    return json.loads(raw)


@app.get("/api/v1/debug/jobs")
async def list_all_jobs():
    """Debug endpoint to list all job states in Redis."""
    jobs = []
    cur = 0
    while True:
        cur, keys = await redis_client.scan(cur, match="job:state:*", count=100)
        for key in keys:
            raw = await redis_client.get(key)
            if raw:
                jobs.append(json.loads(raw))
        if cur == 0:
            break
    return jobs


@app.get("/api/v1/debug/test-agent")
async def test_agent_endpoint():
    """Debug endpoint to test importing and running UnifiedAgent."""
    import sys
    import os
    try:
        # Replicate workers.py path modifications
        services_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if services_dir not in sys.path:
            sys.path.insert(0, services_dir)
        agents_dir = os.path.join(services_dir, "agents")
        if agents_dir not in sys.path:
            sys.path.insert(0, agents_dir)
            
        from agents.unified_agent.main import UnifiedAgent
        agent = UnifiedAgent()
        
        # Test processing a dummy chunk
        result = await agent.process_chunk({
            "chunk_id": "test-chunk-id",
            "document_id": "test-doc-id",
            "chunk_index": 0,
            "total_chunks": 1,
            "text": "The solar system consists of the Sun and the objects that orbit it, including eight planets: Mercury, Venus, Earth, Mars, Jupiter, Saturn, Uranus, and Neptune."
        })
        return {
            "success": True,
            "result": result
        }
    except Exception as exc:
        import traceback
        return {
            "success": False,
            "error": str(exc),
            "traceback": traceback.format_exc()
        }


@app.get("/api/v1/debug/test-gemini")
async def test_gemini_endpoint():
    """Debug endpoint to test direct Gemini API call using GEMINI_API_KEY."""
    import httpx
    import os
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return {"success": False, "error": "GEMINI_API_KEY environment variable is not set or empty"}
        
    masked_key = key[:6] + "..." + key[-4:] if len(key) > 10 else "too short"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={key}"
    payload = {
        "contents": [{"parts": [{"text": "Hello, respond with the word SUCCESS."}]}]
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload, headers={"Content-Type": "application/json"})
            status_code = resp.status_code
            body = resp.text
            if status_code == 200:
                return {
                    "success": True,
                    "status_code": status_code,
                    "masked_key": masked_key,
                    "length": len(key),
                    "response": resp.json()
                }
            else:
                return {
                    "success": False,
                    "status_code": status_code,
                    "masked_key": masked_key,
                    "length": len(key),
                    "error_body": body
                }
    except Exception as exc:
        import traceback
        return {
            "success": False,
            "masked_key": masked_key,
            "length": len(key),
            "error": str(exc),
            "traceback": traceback.format_exc()
        }


@app.get("/api/v1/documents/{document_id}/graph")
async def get_graph(
    document_id: str,
    current_user: Optional[TokenData] = Depends(get_current_user_optional),
):
    """Return the final graph. Also updates history stats when first fetched."""
    raw = await redis_client.get(f"graph:{document_id}")
    if raw is None:
        raw_status = await redis_client.get(f"job:state:{document_id}")
        if raw_status:
            state = json.loads(raw_status)
            if state.get("status") != "completed":
                raise HTTPException(202, "Graph not yet ready")
        raise HTTPException(404, "Graph not found")

    graph_data = json.loads(raw)

    # Update history stats on first graph fetch
    if current_user:
        node_count = len(graph_data.get("nodes", []))
        edge_count = len(graph_data.get("edges", []))
        summary    = graph_data.get("global_summary", "")[:300]
        now        = datetime.utcnow().isoformat()
        await update_document_stats(
            document_id=document_id,
            user_id=current_user.user_id,
            node_count=node_count,
            edge_count=edge_count,
            summary_snippet=summary,
            processed_at=now,
        )
        # Decrement active job counter
        raw_state = await redis_client.get(f"job:state:{document_id}")
        if raw_state:
            st = json.loads(raw_state)
            if st.get("status") == "completed":
                await redis_client.decr(f"active_jobs:{current_user.user_id}")

    return graph_data


@app.get("/api/v1/documents/{document_id}/stream")
async def stream_progress(document_id: str):
    """SSE endpoint for real-time progress streaming."""
    async def event_generator() -> AsyncGenerator[str, None]:
        last_state = None
        timeout    = 300
        elapsed    = 0
        while elapsed < timeout:
            raw = await redis_client.get(f"job:state:{document_id}")
            if raw and raw != last_state:
                last_state = raw
                state = json.loads(raw)
                yield f"data: {json.dumps(state)}\n\n"
                if state.get("status") in ("completed", "failed"):
                    break
            await asyncio.sleep(0.5)
            elapsed += 0.5
        yield 'data: {"status": "stream_closed"}\n\n'

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.websocket("/ws/{document_id}")
async def websocket_progress(ws: WebSocket, document_id: str):
    await manager.connect(ws, document_id)
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(f"updates:{document_id}")
    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                await ws.send_text(message["data"])
    except WebSocketDisconnect:
        manager.disconnect(ws, document_id)
    finally:
        await pubsub.unsubscribe(f"updates:{document_id}")
        await pubsub.aclose()


@app.get("/api/v1/documents")
async def list_documents(
    cursor: int = 0,
    count: int = 20,
    current_user: Optional[TokenData] = Depends(get_current_user_optional),
):
    """
    List recent documents using Redis SCAN (O(1) amortized, safe for production).
    FIX: replaced KEYS('graph:*') which was O(N) and could freeze Redis.
    """
    docs     = []
    cur      = cursor
    scanned  = 0
    target   = min(count, 50)

    while scanned < target:
        cur, keys = await redis_client.scan(cur, match="graph:*", count=100)
        for key in keys:
            doc_id = key.replace("graph:", "")
            state_raw = await redis_client.get(f"job:state:{doc_id}")
            if state_raw:
                state = json.loads(state_raw)
                docs.append({
                    "document_id": doc_id,
                    "status":      state.get("status"),
                    "progress":    state.get("progress_pct", 0),
                    "filename":    state.get("filename"),
                })
                scanned += 1
                if scanned >= target:
                    break
        if cur == 0:
            break  # full scan complete

    return {"documents": docs, "next_cursor": cur}
