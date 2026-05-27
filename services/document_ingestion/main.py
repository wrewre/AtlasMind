"""
Document Ingestion Service
==========================
Consumes from 'document.ingested' Redis Stream.
Extracts raw text from PDF/TXT/MD files.
Publishes raw text to 'document.extracted' stream for the Chunking Service.

Fault tolerance: Uses Redis Streams consumer groups so that if this
service crashes mid-processing, the message is NOT acknowledged and
another instance can pick it up.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import sys
import time
from pathlib import Path

import pdfplumber
import redis.asyncio as aioredis
import structlog

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
INGESTION_STREAM = "document.ingested"
EXTRACTED_STREAM = "document.extracted"
CONSUMER_GROUP = "ingestion-service"
CONSUMER_NAME = os.getenv("HOSTNAME", "ingestion-1")

log = structlog.get_logger("document_ingestion")

# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

def extract_text_from_pdf(path: str) -> tuple[str, int]:
    """Extract text from PDF using pdfplumber. Returns (text, page_count)."""
    pages = []
    with pdfplumber.open(path) as pdf:
        page_count = len(pdf.pages)
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages.append(text.strip())
    return "\n\n".join(pages), page_count


def extract_text_from_file(path: str, file_type: str) -> tuple[str, int]:
    """Route to appropriate extractor based on file type."""
    if file_type == "pdf":
        return extract_text_from_pdf(path)
    elif file_type in ("txt", "md", "markdown"):
        content = Path(path).read_text(encoding="utf-8", errors="replace")
        return content, 1
    else:
        raise ValueError(f"Unsupported file type: {file_type}")


# ---------------------------------------------------------------------------
# Main consumer loop
# ---------------------------------------------------------------------------

async def process_message(redis_client: aioredis.Redis, msg_id: str, data: dict):
    document_id = data.get("document_id", "")
    storage_path = data.get("storage_path", "")
    file_type = data.get("file_type", "txt")
    filename = data.get("filename", "unknown")

    log.info("processing_document", document_id=document_id, path=storage_path)

    start = time.time()
    try:
        text, page_count = extract_text_from_file(storage_path, file_type)
    except Exception as exc:
        log.error("extraction_failed", document_id=document_id, error=str(exc))
        # Update job state
        raw = await redis_client.get(f"job:state:{document_id}")
        if raw:
            state = json.loads(raw)
            state["status"] = "failed"
            state["error_message"] = str(exc)
            await redis_client.setex(f"job:state:{document_id}", 86400, json.dumps(state))
        return

    elapsed_ms = int((time.time() - start) * 1000)

    # Publish extracted text downstream
    await redis_client.xadd(
        EXTRACTED_STREAM,
        {
            "document_id": document_id,
            "filename": filename,
            "file_type": file_type,
            "page_count": str(page_count),
            "text": text,
            "char_count": str(len(text)),
            "extraction_ms": str(elapsed_ms),
        },
        maxlen=5000,
    )

    # Update job status
    raw = await redis_client.get(f"job:state:{document_id}")
    if raw:
        state = json.loads(raw)
        state["status"] = "processing"
        await redis_client.setex(f"job:state:{document_id}", 86400, json.dumps(state))

    log.info(
        "extraction_complete",
        document_id=document_id,
        chars=len(text),
        pages=page_count,
        elapsed_ms=elapsed_ms,
    )


async def run_consumer():
    redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)

    # Create consumer group idempotently
    try:
        await redis_client.xgroup_create(INGESTION_STREAM, CONSUMER_GROUP, id="0", mkstream=True)
        log.info("consumer_group_created", stream=INGESTION_STREAM, group=CONSUMER_GROUP)
    except aioredis.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise
        log.info("consumer_group_exists", stream=INGESTION_STREAM)

    log.info("ingestion_service_ready", consumer=CONSUMER_NAME)

    while True:
        try:
            # XREADGROUP: blocks 2s then loops — allows graceful shutdown
            messages = await redis_client.xreadgroup(
                CONSUMER_GROUP,
                CONSUMER_NAME,
                {INGESTION_STREAM: ">"},
                count=5,
                block=2000,
            )
            if not messages:
                continue

            for stream, entries in messages:
                for msg_id, data in entries:
                    try:
                        await process_message(redis_client, msg_id, data)
                        # ACK only after successful processing (at-least-once)
                        await redis_client.xack(INGESTION_STREAM, CONSUMER_GROUP, msg_id)
                    except Exception as exc:
                        log.error("message_processing_error", msg_id=msg_id, error=str(exc))
                        # Do NOT ack — message stays for retry / DLQ handling

        except asyncio.CancelledError:
            break
        except Exception as exc:
            log.error("consumer_loop_error", error=str(exc))
            await asyncio.sleep(2)

    await redis_client.aclose()


if __name__ == "__main__":
    asyncio.run(run_consumer())
