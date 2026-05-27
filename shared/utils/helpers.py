"""
Shared utilities for all microservices.
- Structured JSON logging (for log aggregators like Loki/ELK)
- Redis client factory
- Retry decorator with exponential back-off
"""
from __future__ import annotations
import json
import logging
import os
import time
import functools
from typing import Any, Callable, Optional, Type
import redis
import structlog

# ---------------------------------------------------------------------------
# Structured logging setup
# ---------------------------------------------------------------------------

def configure_logging(service_name: str, level: str = "INFO") -> structlog.BoundLogger:
    """
    Configure structlog with JSON output.
    Every log line carries `service`, `timestamp`, `level`, and any bound ctx.
    """
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )
    logger = structlog.get_logger(service_name)
    return logger


# ---------------------------------------------------------------------------
# Redis helpers
# ---------------------------------------------------------------------------

def get_redis_client() -> redis.Redis:
    """Return a Redis client configured from environment variables."""
    return redis.Redis(
        host=os.getenv("REDIS_HOST", "redis"),
        port=int(os.getenv("REDIS_PORT", 6379)),
        db=int(os.getenv("REDIS_DB", 0)),
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=10,
        retry_on_timeout=True,
    )


def redis_set_json(client: redis.Redis, key: str, data: Any, ttl: int = 86400) -> None:
    """Serialize data to JSON and store in Redis with optional TTL."""
    client.setex(key, ttl, json.dumps(data, default=str))


def redis_get_json(client: redis.Redis, key: str) -> Optional[Any]:
    """Fetch and deserialize JSON from Redis. Returns None if missing."""
    raw = client.get(key)
    if raw is None:
        return None
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Retry decorator
# ---------------------------------------------------------------------------

def retry(
    max_attempts: int = 3,
    backoff_base: float = 1.5,
    exceptions: tuple[Type[Exception], ...] = (Exception,),
    logger: Optional[Any] = None,
) -> Callable:
    """
    Exponential back-off retry decorator.
    Distributed systems design: transient failures (network blips,
    broker restarts) should be handled transparently at the call site.
    """
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    wait = backoff_base ** attempt
                    if logger:
                        logger.warning(
                            "retry_attempt",
                            fn=fn.__name__,
                            attempt=attempt,
                            max=max_attempts,
                            wait=wait,
                            error=str(exc),
                        )
                    if attempt < max_attempts:
                        time.sleep(wait)
            raise last_exc  # type: ignore[misc]
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Topic name constants (single source of truth)
# ---------------------------------------------------------------------------

class Topics:
    DOCUMENT_INGESTED = "document.ingested"
    CHUNKS_READY = "chunks.ready"
    AGENT_RESULTS = "agent.results"
    CONSENSUS_DONE = "consensus.done"
    GRAPH_BUILT = "graph.built"
    DLQ = "dead.letter.queue"


# ---------------------------------------------------------------------------
# Redis key helpers
# ---------------------------------------------------------------------------

class RedisKeys:
    @staticmethod
    def job_state(document_id: str) -> str:
        return f"job:state:{document_id}"

    @staticmethod
    def knowledge_graph(document_id: str) -> str:
        return f"graph:{document_id}"

    @staticmethod
    def agent_results(document_id: str) -> str:
        return f"agent:results:{document_id}"

    @staticmethod
    def chunk_lock(chunk_id: str) -> str:
        return f"lock:chunk:{chunk_id}"
