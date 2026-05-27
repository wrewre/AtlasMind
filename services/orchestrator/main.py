"""
Orchestrator Agent
==================
The entry point of agentic behaviour. Unlike a fixed pipeline where every
document is processed identically, the Orchestrator PERCEIVES the document
(size, type, domain, density) and DECIDES the processing strategy before
any chunk is dispatched.

Agentic loop:
  1. PERCEIVE  — read document metadata from job:state:{doc_id}
  2. REASON    — call LLM to classify document and decide strategy
  3. ACT       — write strategy config back to Redis so the Unified Agent
                 reads it and adapts its extraction prompt per chunk
  4. OBSERVE   — the downstream pipeline executes under the strategy

This runs ONCE per document, triggered by the document.extracted event,
BEFORE the Chunking Service fans out chunks. It writes:

  orchestrator:strategy:{document_id}  →  JSON config (TTL 1h)

The Unified Agent reads this key and adapts its system prompt accordingly.
If the key is absent (orchestrator crashed or timed out), the agent falls
back to its default extraction strategy — pipeline never blocks.

Strategy config schema:
  {
    "chunk_size":          3000,      # override chunker default
    "chunk_overlap":       300,
    "extraction_strategy": "relationship_first" | "concept_first" | "balanced",
    "domain":              "technical" | "legal" | "narrative" | "general",
    "confidence_threshold": 0.4,
    "focus_categories":    ["TECHNOLOGY", "PROCESS"],  # hint for agent
    "rationale":           "..."      # LLM's own reasoning (logged, not used)
  }
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time

import httpx
import redis.asyncio as aioredis
import structlog

sys.path.insert(0, "/app")

REDIS_URL         = os.getenv("REDIS_URL", "redis://redis:6379/0")
LITELLM_URL       = os.getenv("LITELLM_URL", "http://litellm:4000")
LITELLM_KEY       = os.getenv("LITELLM_API_KEY", "sk-mindmap-master-key-2025")
EXTRACTED_STREAM  = "document.extracted"
CONSUMER_GROUP    = "orchestrator-group"
CONSUMER_NAME     = os.getenv("HOSTNAME", "orchestrator-1")
STRATEGY_TTL      = 3600   # 1 hour

# LLM keys (same env vars as agents)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GROQ_API_KEY   = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL     = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
OLLAMA_HOST    = os.getenv("OLLAMA_HOST", "http://ollama:11434")
OLLAMA_MODEL   = os.getenv("OLLAMA_MODEL", "llama3.2")

log = structlog.get_logger("orchestrator")

ORCHESTRATOR_SYSTEM = """You are a document analysis orchestrator. Given a document preview, 
classify it and return a JSON processing strategy. Output ONLY valid JSON, no explanation.

Classify domain as one of: technical, legal, narrative, scientific, general
Classify extraction_strategy as one of:
  - relationship_first: for technical/scientific docs with dense interconnections
  - concept_first: for educational/reference docs with many distinct entities
  - balanced: for general/narrative docs

Return exactly this JSON structure:
{
  "domain": "technical",
  "extraction_strategy": "relationship_first",
  "chunk_size": 3000,
  "chunk_overlap": 300,
  "confidence_threshold": 0.4,
  "focus_categories": ["TECHNOLOGY", "PROCESS"],
  "rationale": "one sentence explanation"
}

Rules:
- technical/scientific → relationship_first, chunk_size 2500, overlap 400
- legal → concept_first, chunk_size 2000, overlap 500  
- narrative → balanced, chunk_size 3500, overlap 200
- general → balanced, chunk_size 3000, overlap 300
- focus_categories should reflect what matters most in this domain"""

ORCHESTRATOR_USER = """Analyse this document preview and return a processing strategy:

FILENAME: {filename}
CHAR COUNT: {char_count}
PREVIEW (first 800 chars):
{preview}

Return only the JSON strategy object."""


async def _call_llm_for_strategy(preview: str, filename: str, char_count: int) -> dict:
    """Try LLM providers in cascade to get strategy. Falls back to defaults on all failures."""
    user_msg = ORCHESTRATOR_USER.format(
        filename=filename,
        char_count=char_count,
        preview=preview[:800]
    )

    async with httpx.AsyncClient(timeout=25.0) as client:
        # Try LiteLLM proxy first (handles all provider routing)
        try:
            resp = await client.post(
                f"{LITELLM_URL}/v1/chat/completions",
                headers={"Authorization": f"Bearer {LITELLM_KEY}"},
                json={
                    "model": "summary",
                    "messages": [
                        {"role": "system", "content": ORCHESTRATOR_SYSTEM},
                        {"role": "user",   "content": user_msg},
                    ],
                    "max_tokens": 300,
                    "temperature": 0.1,
                },
            )
            if resp.status_code == 200:
                text = resp.json()["choices"][0]["message"]["content"]
                return _parse_strategy(text, "litellm")
        except Exception as e:
            log.warning("orchestrator_litellm_failed", error=str(e))

    # All providers failed — use safe defaults
    log.warning("orchestrator_all_providers_failed_using_defaults")
    return _default_strategy(filename, char_count)


def _parse_strategy(text: str, provider: str) -> dict:
    import re
    clean = re.sub(r"^```(?:json)?\s*", "", text.strip())
    clean = re.sub(r"\s*```\s*$", "", clean.strip())
    try:
        data = json.loads(clean)
        # Validate and sanitise
        strategy = {
            "domain":               data.get("domain", "general"),
            "extraction_strategy":  data.get("extraction_strategy", "balanced"),
            "chunk_size":           max(1000, min(int(data.get("chunk_size", 3000)), 5000)),
            "chunk_overlap":        max(100, min(int(data.get("chunk_overlap", 300)), 800)),
            "confidence_threshold": max(0.2, min(float(data.get("confidence_threshold", 0.4)), 0.8)),
            "focus_categories":     data.get("focus_categories", []),
            "rationale":            str(data.get("rationale", ""))[:200],
            "decided_by":           provider,
        }
        log.info("orchestrator_strategy_decided", provider=provider,
                 domain=strategy["domain"], strategy=strategy["extraction_strategy"])
        return strategy
    except Exception as e:
        log.warning("orchestrator_parse_failed", provider=provider, error=str(e))
        return _default_strategy("", 0)


def _default_strategy(filename: str, char_count: int) -> dict:
    """Rule-based fallback when LLM is unavailable."""
    ext = filename.lower().split(".")[-1] if "." in filename else ""
    if ext == "pdf" and char_count > 10000:
        domain, strategy = "technical", "relationship_first"
    else:
        domain, strategy = "general", "balanced"
    return {
        "domain": domain,
        "extraction_strategy": strategy,
        "chunk_size": 3000,
        "chunk_overlap": 300,
        "confidence_threshold": 0.4,
        "focus_categories": [],
        "rationale": "default strategy (LLM unavailable)",
        "decided_by": "rule_based_fallback",
    }


async def orchestrate_document(redis_client: aioredis.Redis, msg_id: str, data: dict):
    document_id = data.get("document_id", "")
    text        = data.get("text", "")
    filename    = data.get("filename", "document")

    if not document_id or not text:
        return

    log.info("orchestrating", document_id=document_id, filename=filename, chars=len(text))

    strategy = await _call_llm_for_strategy(text, filename, len(text))
    strategy["document_id"] = document_id
    strategy["orchestrated_at"] = time.time()

    # Write strategy to Redis so unified agents can read it
    await redis_client.setex(
        f"orchestrator:strategy:{document_id}",
        STRATEGY_TTL,
        json.dumps(strategy)
    )

    # Also update job state so the UI can show the domain/strategy
    raw = await redis_client.get(f"job:state:{document_id}")
    if raw:
        state = json.loads(raw)
        state["orchestrator"] = {
            "domain":     strategy["domain"],
            "strategy":   strategy["extraction_strategy"],
            "decided_by": strategy["decided_by"],
            "rationale":  strategy["rationale"],
        }
        await redis_client.setex(f"job:state:{document_id}", 86400, json.dumps(state))

    log.info("strategy_written", document_id=document_id, **{
        k: v for k, v in strategy.items() if k not in ("document_id", "orchestrated_at")
    })


async def run_consumer():
    redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)

    # The orchestrator also listens to document.extracted — same stream as chunker,
    # but different consumer group so both receive every message independently.
    try:
        await redis_client.xgroup_create(EXTRACTED_STREAM, CONSUMER_GROUP, id="0", mkstream=True)
    except aioredis.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise

    log.info("orchestrator_ready", consumer=CONSUMER_NAME)

    while True:
        try:
            messages = await redis_client.xreadgroup(
                CONSUMER_GROUP, CONSUMER_NAME,
                {EXTRACTED_STREAM: ">"},
                count=1, block=2000,
            )
            if not messages:
                continue
            for stream, entries in messages:
                for msg_id, data in entries:
                    try:
                        await asyncio.wait_for(
                            orchestrate_document(redis_client, msg_id, data),
                            timeout=30.0
                        )
                    except asyncio.TimeoutError:
                        log.warning("orchestration_timeout", msg_id=msg_id)
                    except Exception as exc:
                        log.error("orchestration_error", error=str(exc))
                    finally:
                        await redis_client.xack(EXTRACTED_STREAM, CONSUMER_GROUP, msg_id)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            log.error("consumer_loop_error", error=str(exc))
            await asyncio.sleep(2)

    await redis_client.aclose()


if __name__ == "__main__":
    asyncio.run(run_consumer())
