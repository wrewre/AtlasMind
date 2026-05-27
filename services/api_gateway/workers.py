"""
Workers Launcher — Monolith Edition
=====================================
Runs all background worker coroutines inside the same process as the
API Gateway so Railway can host everything in a single container.

The core logic of every worker is UNCHANGED — they still:
  - Communicate exclusively through Redis Streams
  - Use consumer groups for fault-tolerance
  - ACK messages only after successful processing

This file simply imports each worker's `run_consumer` / `run` coroutine
and launches them as concurrent asyncio tasks.
"""
from __future__ import annotations

import asyncio
import sys
import os
import structlog

log = structlog.get_logger("workers_launcher")


async def _safe_run(name: str, coro):
    """Wrap a worker coroutine so one crash doesn't kill the others."""
    while True:
        try:
            log.info("worker_starting", worker=name)
            await coro()
            log.warning("worker_exited_unexpectedly", worker=name)
        except asyncio.CancelledError:
            log.info("worker_cancelled", worker=name)
            return
        except Exception as exc:
            log.error("worker_crashed", worker=name, error=str(exc))
        # Brief pause before restarting crashed worker
        await asyncio.sleep(3)


async def start_all_workers():
    """
    Start all microservice workers as background asyncio tasks.
    Called from the FastAPI lifespan so they boot when the server starts.
    """
    # ── Import each service's run_consumer / run function ─────────────────
    # We add the parent paths so Python can find the modules
    services_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, services_dir)
    sys.path.insert(0, os.path.join(services_dir, "agents"))

    tasks = []

    # 1. Document Ingestion Service
    try:
        from document_ingestion.main import run_consumer as ingestion_consumer
        tasks.append(asyncio.create_task(_safe_run("document_ingestion", ingestion_consumer)))
        log.info("worker_registered", worker="document_ingestion")
    except Exception as e:
        log.error("worker_import_failed", worker="document_ingestion", error=str(e))

    # 2. Chunking Service
    try:
        from chunking_service.main import run_consumer as chunking_consumer
        tasks.append(asyncio.create_task(_safe_run("chunking_service", chunking_consumer)))
        log.info("worker_registered", worker="chunking_service")
    except Exception as e:
        log.error("worker_import_failed", worker="chunking_service", error=str(e))

    # 3. Orchestrator
    try:
        from orchestrator.main import run_consumer as orchestrator_consumer
        tasks.append(asyncio.create_task(_safe_run("orchestrator", orchestrator_consumer)))
        log.info("worker_registered", worker="orchestrator")
    except Exception as e:
        log.error("worker_import_failed", worker="orchestrator", error=str(e))

    # 4. Unified Agent (the AI brain — runs process chunks via LLM)
    try:
        # The unified agent imports base_agent and llm_client from /app/agents
        agents_dir = os.path.join(services_dir, "agents")
        if agents_dir not in sys.path:
            sys.path.insert(0, agents_dir)
        from agents.unified_agent.main import UnifiedAgent
        agent = UnifiedAgent()
        tasks.append(asyncio.create_task(_safe_run("unified_agent", agent.run)))
        log.info("worker_registered", worker="unified_agent")
    except Exception as e:
        log.error("worker_import_failed", worker="unified_agent", error=str(e))


    # 5. Consensus Engine
    try:
        from consensus_engine.main import run_consumer as consensus_consumer
        tasks.append(asyncio.create_task(_safe_run("consensus_engine", consensus_consumer)))
        log.info("worker_registered", worker="consensus_engine")
    except Exception as e:
        log.error("worker_import_failed", worker="consensus_engine", error=str(e))

    # 6. Graph Builder
    try:
        from graph_builder.main import run_consumer as graph_consumer
        tasks.append(asyncio.create_task(_safe_run("graph_builder", graph_consumer)))
        log.info("worker_registered", worker="graph_builder")
    except Exception as e:
        log.error("worker_import_failed", worker="graph_builder", error=str(e))

    log.info("all_workers_launched", count=len(tasks))
    return tasks
