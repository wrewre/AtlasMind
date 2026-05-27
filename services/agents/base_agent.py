"""
Base Agent  —  fixed version
=============================
Fixes over previous version:

1. SANE RETRY BACKOFF
   Old: wait = 1.5^attempt + random(1,10)  → up to 446s for 12 retries
   New: max 3 retries, capped wait of 8s, jitter 0-2s only.
   Rationale: the LLM client already handles provider-level retries.
   The base agent retries cover transient Redis or parsing errors only.

2. TIMEOUT GUARD PER CHUNK
   Wraps process_chunk() in asyncio.wait_for(timeout=90s) so a hung HTTP
   call never blocks the consumer loop indefinitely.

3. GRACEFUL DLQ: publishes a FAILED result to agent.results
   instead of silently dropping the chunk.  The consensus engine can
   then count it and still trigger with partial data.

4. REDUCED count=3 → count=1 per XREADGROUP poll
   Prevents one slow agent from building a backlog of 3 chunks in flight.
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

import redis.asyncio as aioredis
import structlog

REDIS_URL     = os.getenv("REDIS_URL", "redis://redis:6379/0")
CHUNKS_STREAM = "chunks.ready"
RESULTS_STREAM = "agent.results"
DLQ_STREAM    = "dead.letter.queue"
MAX_RETRIES   = int(os.getenv("MAX_RETRIES", "3"))  # sensible default: 3
CHUNK_TIMEOUT = int(os.getenv("CHUNK_TIMEOUT", "90"))   # seconds per chunk

log = structlog.get_logger("base_agent")


class BaseAgent(ABC):

    def __init__(self, agent_type: str, agent_id: Optional[str] = None):
        self.agent_type     = agent_type
        self.agent_id       = agent_id or f"{agent_type}-{os.getenv('HOSTNAME', 'local')}"
        self.consumer_group = f"{agent_type}-agents"
        self.log            = structlog.get_logger(self.agent_id)

    @abstractmethod
    async def process_chunk(self, chunk_data: Dict[str, Any]) -> Dict[str, Any]:
        ...

    async def publish_result(self, redis_client: aioredis.Redis, result: Dict[str, Any]):
        """Publish result to agent.results stream — consumed by consensus engine."""
        await redis_client.xadd(
            RESULTS_STREAM,
            {
                "agent_id":     self.agent_id,
                "agent_type":   self.agent_type,
                "document_id":  result.get("document_id", ""),
                "chunk_id":     result.get("chunk_id", ""),
                "chunk_index":  str(result.get("chunk_index", 0)),
                "total_chunks": str(result.get("total_chunks", 0)),
                "payload":      json.dumps(result, default=str),
            },
            maxlen=100000,
        )

    async def _publish_failed_result(
        self,
        redis_client: aioredis.Redis,
        data: Dict[str, Any],
        error: str,
    ):
        """
        Publish a FAILED stub result so the consensus engine can still count it.
        This prevents the pipeline from hanging when a chunk permanently fails.
        """
        failed_result = {
            "agent_id":           self.agent_id,
            "agent_type":         self.agent_type,
            "document_id":        data.get("document_id", ""),
            "chunk_id":           data.get("chunk_id", ""),
            "chunk_index":        int(data.get("chunk_index", 0)),
            "total_chunks":       int(data.get("total_chunks", 0)),
            "concepts":           [],
            "relationships":      [],
            "summary":            None,
            "confidence_overall": 0.0,
            "error":              error,
            "failed":             True,
        }
        await self.publish_result(redis_client, failed_result)
        self.log.warning("published_failed_result", chunk_index=data.get("chunk_index"), error=error)

    async def send_to_dlq(self, redis_client, msg_id, data, error):
        try:
            await redis_client.xadd(
                DLQ_STREAM,
                {
                    "original_msg_id": msg_id,
                    "agent_id":        self.agent_id,
                    "error":           error[:500],
                    "document_id":     data.get("document_id", ""),
                    "chunk_index":     str(data.get("chunk_index", "")),
                },
                maxlen=10000,
            )
        except Exception as e:
            self.log.error("dlq_publish_failed", error=str(e))

    async def run(self):
        redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)

        try:
            await redis_client.xgroup_create(
                CHUNKS_STREAM, self.consumer_group, id="0", mkstream=True
            )
            self.log.info("consumer_group_created", group=self.consumer_group)
        except aioredis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

        self.log.info("agent_ready", agent_id=self.agent_id, type=self.agent_type)

        while True:
            try:
                messages = await redis_client.xreadgroup(
                    self.consumer_group,
                    self.agent_id,
                    {CHUNKS_STREAM: ">"},
                    count=1,          # process one chunk at a time
                    block=2000,
                )
                if not messages:
                    continue

                for stream, entries in messages:
                    for msg_id, data in entries:
                        await self._handle_with_retry(redis_client, msg_id, data)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.log.error("consumer_loop_error", error=str(exc))
                await asyncio.sleep(2)

        await redis_client.aclose()

    async def _handle_with_retry(self, redis_client, msg_id, data):
        """
        Attempt process_chunk up to MAX_RETRIES times with capped back-off.
        On final failure: publish a failed stub result (not silent drop),
        send to DLQ, then ACK so the stream isn't blocked.
        """
        last_error = "unknown error"

        for attempt in range(1, MAX_RETRIES + 1):
            start = time.time()
            try:
                # Hard timeout per chunk — prevents silent hangs
                result = await asyncio.wait_for(
                    self.process_chunk(data),
                    timeout=CHUNK_TIMEOUT,
                )
                result["processing_time_ms"] = int((time.time() - start) * 1000)
                await self.publish_result(redis_client, result)
                await redis_client.xack(CHUNKS_STREAM, self.consumer_group, msg_id)
                self.log.info(
                    "chunk_processed",
                    doc=data.get("document_id"),
                    chunk=data.get("chunk_index"),
                    ms=result["processing_time_ms"],
                )
                return

            except asyncio.TimeoutError:
                last_error = f"chunk timed out after {CHUNK_TIMEOUT}s"
                self.log.warning("chunk_timeout", attempt=attempt, chunk=data.get("chunk_index"))
                # Don't retry on timeout — cascade is already handled in LLM client
                break

            except Exception as exc:
                last_error = str(exc)
                # Cap backoff at 8s max, small jitter

                wait = min(2.0 ** attempt, 8.0) + random.uniform(0, 1.5)
                self.log.warning(
                    "chunk_retry",
                    attempt=attempt, max=MAX_RETRIES,
                    error=last_error[:200], wait=round(wait, 1),
                )
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(wait)

        # All retries exhausted — publish FAILED result so consensus can proceed
        await self._publish_failed_result(redis_client, data, last_error)
        await self.send_to_dlq(redis_client, msg_id, data, last_error)
        await redis_client.xack(CHUNKS_STREAM, self.consumer_group, msg_id)
