"""
Graph Builder Service
=====================
Consumes from 'graph.built' stream.
Persists the knowledge graph to Neo4j (if available) OR
exports it as a portable JSON file for offline use.

Neo4j Cypher queries:
- MERGE on concept IDs ensures idempotency
- Relationships use MERGE to avoid duplicates on reprocessing
- All properties stored for rich graph queries

Fallback: if Neo4j is unavailable, stores graph as JSON file
(useful for development without Neo4j).
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

import redis.asyncio as aioredis
import structlog

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
GRAPH_STREAM = "graph.built"
CONSUMER_GROUP = "graph-builder"
CONSUMER_NAME = os.getenv("HOSTNAME", "graph-builder-1")
GRAPH_OUTPUT_DIR = Path(os.getenv("GRAPH_OUTPUT_DIR", "/app/graphs"))
GRAPH_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "mindmap123")
NEO4J_ENABLED = os.getenv("NEO4J_ENABLED", "false").lower() == "true"

log = structlog.get_logger("graph_builder")

# ---------------------------------------------------------------------------
# Neo4j integration (optional)
# ---------------------------------------------------------------------------

neo4j_driver = None

def get_neo4j_driver():
    global neo4j_driver
    if neo4j_driver is None and NEO4J_ENABLED:
        try:
            from neo4j import GraphDatabase
            neo4j_driver = GraphDatabase.driver(
                NEO4J_URI,
                auth=(NEO4J_USER, NEO4J_PASSWORD),
            )
            log.info("neo4j_connected", uri=NEO4J_URI)
        except Exception as exc:
            log.warning("neo4j_unavailable", error=str(exc))
    return neo4j_driver


def evaluate_graph_quality(graph: Dict[str, Any], document_id: str):
    """
    Component 5: Quality Feedback Loop
    Analyzes the built graph for orphaned nodes or low density.
    Logs feedback metrics and simulates re-queuing chunks for agentic self-correction.
    """
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    
    if not nodes:
        return
        
    # Count orphaned nodes (nodes with 0 edges)
    connected_nodes = set()
    for edge in edges:
        connected_nodes.add(edge["source"])
        connected_nodes.add(edge["target"])
        
    orphaned_count = 0
    for node in nodes:
        if node["id"] not in connected_nodes:
            orphaned_count += 1
            
    orphaned_ratio = orphaned_count / len(nodes)
    log.info("graph_quality_evaluation", 
             document_id=document_id,
             orphaned_nodes=orphaned_count,
             orphaned_ratio=round(orphaned_ratio, 2))
             
    if orphaned_ratio > 0.20:
        log.warning("QUALITY_FEEDBACK_TRIGGERED", 
                    reason="orphaned_ratio_too_high",
                    ratio=orphaned_ratio,
                    action="re-queue_chunks_with_strategy: force_relationships")
        # In a fully persistent system, we would fetch the original text from DB
        # and publish to `document.orchestrated` with strategy='force_relationships'.


def persist_to_neo4j(driver, graph: Dict[str, Any]):
    """
    Persist the knowledge graph to Neo4j using MERGE for idempotency.
    Running the same document twice won't create duplicates.
    """
    document_id = graph.get("document_id", "unknown")

    with driver.session() as session:
        # Create document node
        session.run(
            """
            MERGE (d:Document {id: $doc_id})
            SET d.processed_at = datetime()
            """,
            doc_id=document_id,
        )

        # Create concept nodes
        for node in graph.get("nodes", []):
            session.run(
                """
                MERGE (c:Concept {id: $id})
                SET c.label = $label,
                    c.category = $category,
                    c.confidence = $confidence,
                    c.mention_count = $mention_count,
                    c.sentiment = $sentiment
                WITH c
                MATCH (d:Document {id: $doc_id})
                MERGE (d)-[:CONTAINS]->(c)
                """,
                id=node["id"],
                label=node["label"],
                category=node.get("category", "CONCEPT"),
                confidence=node.get("confidence", 0.5),
                mention_count=node.get("mention_count", 1),
                sentiment=node.get("sentiment"),
                doc_id=document_id,
            )

        # Create relationships
        for edge in graph.get("edges", []):
            session.run(
                f"""
                MATCH (s:Concept {{id: $source}})
                MATCH (t:Concept {{id: $target}})
                MERGE (s)-[r:{edge['relation_type'].upper()}]->(t)
                SET r.label = $label,
                    r.confidence = $confidence,
                    r.weight = $weight,
                    r.document_id = $doc_id
                """,
                source=edge["source"],
                target=edge["target"],
                label=edge.get("label", ""),
                confidence=edge.get("confidence", 0.5),
                weight=edge.get("weight", 1.0),
                doc_id=document_id,
            )

    log.info(
        "neo4j_persist_complete",
        document_id=document_id,
        nodes=len(graph.get("nodes", [])),
        edges=len(graph.get("edges", [])),
    )


def export_graph_json(graph: Dict[str, Any], document_id: str):
    """Fallback: export graph as JSON file for visualization."""
    output_path = GRAPH_OUTPUT_DIR / f"{document_id}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(graph, f, indent=2, default=str)
    log.info("graph_exported", path=str(output_path))
    return str(output_path)


# ---------------------------------------------------------------------------
# Main consumer loop
# ---------------------------------------------------------------------------

async def process_message(redis_client: aioredis.Redis, data: dict):
    document_id = data.get("document_id", "")
    if not document_id:
        return

    # Fetch graph from Redis
    raw = await redis_client.get(f"graph:{document_id}")
    if not raw:
        log.warning("graph_not_found_in_redis", document_id=document_id)
        return

    graph = json.loads(raw)

    # ── Agentic Feedback Loop ──
    evaluate_graph_quality(graph, document_id)

    # Try Neo4j first
    driver = get_neo4j_driver()
    if driver:
        try:
            persist_to_neo4j(driver, graph)
        except Exception as exc:
            log.error("neo4j_persist_failed", error=str(exc))
            export_graph_json(graph, document_id)
    else:
        export_graph_json(graph, document_id)

    log.info(
        "graph_built",
        document_id=document_id,
        nodes=data.get("node_count"),
        edges=data.get("edge_count"),
    )


async def run_consumer():
    redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)

    try:
        await redis_client.xgroup_create(GRAPH_STREAM, CONSUMER_GROUP, id="0", mkstream=True)
    except aioredis.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise

    log.info("graph_builder_ready", consumer=CONSUMER_NAME)

    while True:
        try:
            messages = await redis_client.xreadgroup(
                CONSUMER_GROUP,
                CONSUMER_NAME,
                {GRAPH_STREAM: ">"},
                count=5,
                block=2000,
            )
            if not messages:
                continue

            for stream, entries in messages:
                for msg_id, data in entries:
                    try:
                        await process_message(redis_client, data)
                    except Exception as exc:
                        log.error("graph_build_error", msg_id=msg_id, error=str(exc))
                    finally:
                        # Always ACK to prevent infinite reprocessing on failure
                        try:
                            await redis_client.xack(GRAPH_STREAM, CONSUMER_GROUP, msg_id)
                        except Exception as ack_err:
                            log.error("ack_failed", msg_id=msg_id, error=str(ack_err))

        except asyncio.CancelledError:
            break
        except Exception as exc:
            log.error("consumer_loop_error", error=str(exc))
            await asyncio.sleep(2)

    await redis_client.aclose()


if __name__ == "__main__":
    asyncio.run(run_consumer())
