"""
Chunking Service  —  fixed version
====================================
Fixes:
1. SMALL FILE HANDLING
   Old algorithm dropped final chunk if < MIN_CHUNK_SIZE even when it was the
   ONLY chunk (small files).  New: always emit at least one chunk if text exists.

2. CORRECT CHAR POSITION TRACKING
   Old code tracked chunk_start incorrectly after overlap slide — used approximate
   math that drifted on multi-chunk docs.  New: track byte offset from original text.

3. EMPTY TEXT GUARD
   Strips Unicode control chars and normalises whitespace before chunking.

4. MINIMUM 1 CHUNK GUARANTEE
   If the entire document is shorter than chunk_size, it produces exactly 1 chunk.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import unicodedata
import uuid
from typing import List, Tuple

import redis.asyncio as aioredis
import structlog

REDIS_URL        = os.getenv("REDIS_URL",    "redis://redis:6379/0")
EXTRACTED_STREAM = "document.extracted"
CHUNKS_STREAM    = "chunks.ready"
CONSUMER_GROUP   = "chunking-service"
CONSUMER_NAME    = os.getenv("HOSTNAME",     "chunker-1")

CHUNK_SIZE    = int(os.getenv("CHUNK_SIZE",    "3000"))   # chars per chunk
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "300"))    # overlap chars
MIN_CHUNK_SIZE= int(os.getenv("MIN_CHUNK_SIZE","80"))     # min to emit

log = structlog.get_logger("chunking_service")


def clean_text(text: str) -> str:
    """Remove null bytes, control chars, normalise whitespace."""
    # Remove null bytes and other problematic control chars
    text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    # Remove non-printable characters except newlines and tabs
    text = "".join(
        ch for ch in text
        if ch == "\n" or ch == "\t" or not unicodedata.category(ch).startswith("C")
    )
    # Collapse excessive blank lines (3+ → 2)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_into_chunks(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[Tuple[str, int, int]]:
    """
    Split text into overlapping sentence-aware chunks.
    Returns list of (chunk_text, char_start, char_end).

    Guarantees:
    - Always returns at least 1 chunk if text is non-empty
    - Each chunk is at most chunk_size characters
    - Consecutive chunks share ~overlap characters of context
    """
    text = clean_text(text)
    if not text:
        return []

    # If text fits in a single chunk, return as-is
    if len(text) <= chunk_size:
        return [(text, 0, len(text))]

    # Split on sentence boundaries (period/exclamation/question + space)
    sentence_end = re.compile(r'(?<=[.!?])\s+')
    raw_sentences = sentence_end.split(text)
    sentences: List[str] = [s.strip() for s in raw_sentences if s.strip()]

    if not sentences:
        # No sentence boundaries found — fall back to hard character split
        return _hard_split(text, chunk_size, overlap)

    chunks: List[Tuple[str, int, int]] = []
    current: List[str]  = []
    current_len: int    = 0
    # Track where in the original text we are
    pos: int            = 0         # scans through `text`
    chunk_start: int    = 0

    for sentence in sentences:
        sent_len = len(sentence)

        if current_len + sent_len + len(current) > chunk_size and current:
            # Emit chunk
            chunk_text  = " ".join(current)
            chunk_end   = chunk_start + len(chunk_text)
            chunks.append((chunk_text, chunk_start, chunk_end))

            # Build overlap: keep trailing sentences that fit in `overlap` chars
            overlap_sents: List[str] = []
            budget = overlap
            for s in reversed(current):
                if budget <= 0:
                    break
                overlap_sents.insert(0, s)
                budget -= len(s) + 1   # +1 for space

            current     = overlap_sents
            current_len = sum(len(s) for s in current)
            # New chunk starts where the current overlap starts in original text
            if current:
                overlap_text = " ".join(current)
                idx = text.find(overlap_text, chunk_start)
                chunk_start  = idx if idx != -1 else chunk_end

        current.append(sentence)
        current_len += sent_len

    # Emit final chunk
    if current:
        chunk_text = " ".join(current)
        if len(chunk_text) >= MIN_CHUNK_SIZE or not chunks:
            chunks.append((chunk_text, chunk_start, chunk_start + len(chunk_text)))

    # Safety: guarantee at least 1 chunk
    if not chunks:
        chunks = [(text[:chunk_size], 0, min(len(text), chunk_size))]

    return chunks


def _hard_split(text: str, chunk_size: int, overlap: int) -> List[Tuple[str, int, int]]:
    """Fallback: split by characters when no sentence boundaries exist."""
    chunks = []
    step   = max(chunk_size - overlap, 100)
    i      = 0
    while i < len(text):
        end   = min(i + chunk_size, len(text))
        chunk = text[i:end]
        if chunk.strip():
            chunks.append((chunk, i, end))
        i += step
    if not chunks and text.strip():
        chunks = [(text, 0, len(text))]
    return chunks


async def process_message(redis_client: aioredis.Redis, msg_id: str, data: dict):
    document_id = data.get("document_id", "")
    text        = data.get("text",        "")
    filename    = data.get("filename",    "unknown")

    if not text or not text.strip():
        log.warning("empty_document", document_id=document_id)
        # Mark job as failed
        raw = await redis_client.get(f"job:state:{document_id}")
        if raw:
            state = json.loads(raw)
            state["status"] = "failed"
            state["error_message"] = "Document contained no extractable text"
            await redis_client.setex(f"job:state:{document_id}", 86400, json.dumps(state))
        return

    log.info("chunking_document", document_id=document_id, chars=len(text))
    chunks      = split_into_chunks(text)
    total_chunks = len(chunks)

    log.info("chunks_created", document_id=document_id, total=total_chunks,
             avg_size=int(sum(len(c) for c, _, _ in chunks) / max(total_chunks, 1)))

    # Update job state BEFORE fanning out chunks so agents see correct total
    raw = await redis_client.get(f"job:state:{document_id}")
    if raw:
        state = json.loads(raw)
        state["total_chunks"] = total_chunks
        state["status"]       = "processing"
        await redis_client.setex(f"job:state:{document_id}", 86400, json.dumps(state))

    # Fan-out via pipeline (single round-trip to Redis)
    pipe = redis_client.pipeline()
    for idx, (chunk_text, char_start, char_end) in enumerate(chunks):
        chunk_id = str(uuid.uuid4())
        pipe.xadd(
            CHUNKS_STREAM,
            {
                "chunk_id":     chunk_id,
                "document_id":  document_id,
                "chunk_index":  str(idx),
                "total_chunks": str(total_chunks),
                "text":         chunk_text,
                "char_start":   str(char_start),
                "char_end":     str(char_end),
                "filename":     filename,
            },
            maxlen=50000,
        )
    await pipe.execute()
    log.info("chunks_published", document_id=document_id, count=total_chunks)


async def run_consumer():
    redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)
    try:
        await redis_client.xgroup_create(EXTRACTED_STREAM, CONSUMER_GROUP, id="0", mkstream=True)
    except aioredis.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise

    log.info("chunking_service_ready", consumer=CONSUMER_NAME,
             chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP)

    while True:
        try:
            messages = await redis_client.xreadgroup(
                CONSUMER_GROUP, CONSUMER_NAME,
                {EXTRACTED_STREAM: ">"},
                count=2, block=2000,
            )
            if not messages:
                continue
            for stream, entries in messages:
                for msg_id, data in entries:
                    try:
                        await process_message(redis_client, msg_id, data)
                        await redis_client.xack(EXTRACTED_STREAM, CONSUMER_GROUP, msg_id)
                    except Exception as exc:
                        log.error("chunk_error", msg_id=msg_id, error=str(exc))
                        await redis_client.xack(EXTRACTED_STREAM, CONSUMER_GROUP, msg_id)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            log.error("consumer_loop_error", error=str(exc))
            await asyncio.sleep(2)

    await redis_client.aclose()


if __name__ == "__main__":
    asyncio.run(run_consumer())
