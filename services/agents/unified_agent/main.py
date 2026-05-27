"""
Unified Agent — ReAct + Critic (Agentic Version)
=================================================

What changed from the original unified agent:
----------------------------------------------
1. REACT LOOP (Thought -> Action -> Observation -> Repeat)
   The agent classifies the chunk (Thought), picks an extraction strategy
   (Action), observes confidence of the result (Observation), and if
   confidence is below threshold retries once with a targeted prompt.

2. ORCHESTRATOR STRATEGY AWARENESS
   Reads orchestrator:strategy:{document_id} from Redis before processing.
   Adapts extraction prompt based on document domain/type.

3. INTRA-CHUNK CRITIC
   After extraction, a second LLM call scores each relationship for
   factual grounding. Relationships below 0.5 grounding are filtered
   BEFORE results reach the Consensus Engine.

4. FULL AUDIT TRAIL
   Every result includes: react_iterations, critic_filtered_count,
   extraction_strategy_used, llm_used, processing_time_ms.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
import uuid
from typing import Any, Dict, List

sys.path.insert(0, "/app")

from base_agent import BaseAgent
from llm_client import get_llm_client

VALID_CATEGORIES     = {"ENTITY","TECHNOLOGY","PROCESS","CONCEPT","PERSON","ORGANIZATION","LOCATION","EVENT"}
VALID_RELATION_TYPES = {"is_a","part_of","causes","enables","requires","uses","implements","related_to","contrasts_with","produces"}

_BASE_EXTRACT = """You are a knowledge graph extraction engine. Extract from the text chunk below.
Respond ONLY with this exact JSON, no markdown, no explanation:
{
  "concepts": [
    {"id": "snake_case_id", "label": "Human Label", "category": "CATEGORY", "confidence": 0.9}
  ],
  "relationships": [
    {"source": "id_a", "target": "id_b", "relation_type": "uses", "label": "uses for X", "confidence": 0.85}
  ],
  "summary": "1-3 sentence factual summary.",
  "overall_sentiment": 0.0,
  "sentiment_label": "neutral",
  "concept_sentiments": []
}
Categories: ENTITY | TECHNOLOGY | PROCESS | CONCEPT | PERSON | ORGANIZATION | LOCATION | EVENT
Relation types: is_a | part_of | causes | enables | requires | uses | implements | related_to | contrasts_with | produces
Only include relationships with confidence >= 0.45."""

STRATEGY_PROMPTS = {
    "relationship_first": _BASE_EXTRACT + "\nFOCUS: Prioritise RELATIONSHIPS. Extract 3-10 high-quality relationships. Prefer: causes, enables, requires, implements, uses. Extract 5-12 concepts.",
    "concept_first":      _BASE_EXTRACT + "\nFOCUS: Prioritise CONCEPTS. Extract 8-15 well-defined concepts. Extract 2-6 relationships only where highly confident (>=0.65).",
    "balanced":           _BASE_EXTRACT + "\nFOCUS: Balanced. Extract 5-12 concepts and 3-8 relationships.",
}

CRITIC_SYSTEM = """You are a fact-checker for knowledge graph extraction.
Given a source text and extracted relationships, score each for grounding in the source text.
0.0 = not supported by text, 1.0 = explicitly stated.
Respond ONLY with JSON: {"scores": [{"source": "id_a", "target": "id_b", "grounding_score": 0.8}]}"""

CRITIC_USER = "Source text:\n{text}\n\nExtracted relationships:\n{relationships}\n\nScore each relationship. Return only JSON."
USER_TMPL   = "Extract knowledge graph data from this text chunk:\n--- TEXT ---\n{text}\n--- END ---\nOutput only the JSON object."


def _normalise_id(raw: str) -> str:
    cid = raw.lower().strip().replace(" ", "_").replace("-", "_").replace(".", "_")
    return re.sub(r"[^\w]", "_", cid).strip("_")


class UnifiedAgent(BaseAgent):

    def __init__(self):
        super().__init__(agent_type="unified")
        self.llm    = get_llm_client()
        self._redis = None

    async def _get_redis(self):
        if self._redis is None:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(
                os.getenv("REDIS_URL", "redis://redis:6379/0"), decode_responses=True
            )
        return self._redis

    async def _get_strategy(self, document_id: str) -> dict:
        try:
            r   = await self._get_redis()
            raw = await r.get(f"orchestrator:strategy:{document_id}")
            if raw:
                s = json.loads(raw)
                self.log.info("strategy_loaded", domain=s.get("domain"), extraction=s.get("extraction_strategy"))
                return s
        except Exception as e:
            self.log.warning("strategy_read_failed", error=str(e))
        return {"extraction_strategy": "balanced", "confidence_threshold": 0.4, "focus_categories": [], "domain": "general"}

    def _classify_chunk(self, text: str, strategy: dict) -> str:
        """THINK step: decide strategy for THIS chunk (may override document-level)."""
        tl = text.lower()
        if any(kw in tl for kw in ["references\n", "bibliography\n", "et al.", "[1]", "[2]"]):
            return "concept_first"
        if len(text) < 500:
            return "balanced"
        return strategy.get("extraction_strategy", "balanced")

    async def _extract(self, text: str, strat: str) -> tuple:
        system = STRATEGY_PROMPTS.get(strat, STRATEGY_PROMPTS["balanced"])
        raw, provider = await self.llm.complete(system, USER_TMPL.format(text=text[:3000]), max_tokens=1500)
        clean = re.sub(r"^```(?:json)?\s*", "", raw.strip())
        clean = re.sub(r"\s*```\s*$", "", clean.strip())
        for fn in [lambda s: json.loads(s), lambda s: json.loads(re.search(r'\{.*\}', s, re.DOTALL).group())]:
            try:
                return fn(clean), provider
            except Exception:
                pass
        return {}, provider

    async def _run_critic(self, text: str, relationships: list) -> tuple:
        if len(relationships) < 2:
            return relationships, 0
        rel_summary = json.dumps([
            {"source": r["source"], "target": r["target"],
             "relation_type": r["relation_type"], "label": r["label"]}
            for r in relationships
        ], indent=2)
        try:
            raw, _ = await self.llm.complete(
                CRITIC_SYSTEM,
                CRITIC_USER.format(text=text[:2000], relationships=rel_summary),
                max_tokens=400,
            )
            clean = re.sub(r"^```(?:json)?\s*", "", raw.strip())
            clean = re.sub(r"\s*```\s*$", "", clean.strip())
            scores_data = json.loads(clean)
            scores = {
                (s["source"], s["target"]): float(s.get("grounding_score", 1.0))
                for s in scores_data.get("scores", [])
            }
            filtered, removed = [], 0
            for r in relationships:
                score = scores.get((r["source"], r["target"]), 1.0)
                if score >= 0.5:
                    r["grounding_score"] = round(score, 3)
                    filtered.append(r)
                else:
                    removed += 1
            return filtered, removed
        except Exception as e:
            self.log.warning("critic_failed", error=str(e))
            return relationships, 0

    async def process_chunk(self, data: Dict[str, Any]) -> Dict[str, Any]:
        chunk_id     = data.get("chunk_id",     str(uuid.uuid4()))
        document_id  = data.get("document_id",  "")
        chunk_index  = int(data.get("chunk_index",  0))
        total_chunks = int(data.get("total_chunks", 1))
        text         = data.get("text", "").strip()

        if not text:
            return self._empty(chunk_id, document_id, chunk_index, total_chunks)

        t0 = time.time()

        # PERCEIVE
        strategy       = await self._get_strategy(document_id)
        conf_threshold = float(strategy.get("confidence_threshold", 0.4))

        # THINK
        chunk_strategy = self._classify_chunk(text, strategy)
        self.log.info("react_thought", chunk=chunk_index, strategy=chunk_strategy)

        # ACT
        result, provider_used = await self._extract(text, chunk_strategy)
        react_iterations = 1

        # OBSERVE
        raw_concepts      = result.get("concepts", [])
        raw_relationships = result.get("relationships", [])
        avg_conf          = sum(float(c.get("confidence", 0)) for c in raw_concepts) / max(len(raw_concepts), 1)

        if avg_conf < conf_threshold and react_iterations < 2:
            fallback = "concept_first" if chunk_strategy == "relationship_first" else "relationship_first"
            self.log.info("react_retry", chunk=chunk_index, avg_conf=round(avg_conf, 3), retrying_with=fallback)
            retry_result, retry_provider = await self._extract(text, fallback)
            react_iterations = 2
            retry_conf = sum(float(c.get("confidence", 0)) for c in retry_result.get("concepts", [])) / max(len(retry_result.get("concepts", [])), 1)
            if retry_conf > avg_conf:
                result, provider_used = retry_result, retry_provider
                raw_concepts      = result.get("concepts", [])
                raw_relationships = result.get("relationships", [])
                self.log.info("react_retry_accepted", chunk=chunk_index, new_conf=round(retry_conf, 3))

        # CRITIC
        critic_filtered = 0
        if len(raw_relationships) >= 2:
            raw_relationships, critic_filtered = await self._run_critic(text, raw_relationships)

        # Parse concepts
        concepts: List[Dict] = []
        for c in raw_concepts:
            cid = _normalise_id(str(c.get("id", "")))
            lbl = str(c.get("label", "")).strip()
            if not cid or not lbl:
                continue
            cat = str(c.get("category", "CONCEPT")).upper()
            if cat not in VALID_CATEGORIES:
                cat = "CONCEPT"
            conf = min(max(float(c.get("confidence", 0.7)), 0.0), 1.0)
            concepts.append({"id": cid, "label": lbl, "category": cat, "confidence": conf, "source_chunk_id": chunk_id})

        # Parse relationships
        relationships: List[Dict] = []
        for r in raw_relationships:
            src  = _normalise_id(str(r.get("source", "")))
            tgt  = _normalise_id(str(r.get("target", "")))
            if not src or not tgt or src == tgt:
                continue
            conf = min(max(float(r.get("confidence", 0.6)), 0.0), 1.0)
            if conf < 0.45:
                continue
            rel = r.get("relation_type", "related_to")
            if rel not in VALID_RELATION_TYPES:
                rel = "related_to"
            relationships.append({
                "source": src, "target": tgt, "relation_type": rel,
                "label": str(r.get("label", rel.replace("_", " "))).strip(),
                "confidence": conf, "grounding_score": r.get("grounding_score"),
                "source_chunk_id": chunk_id,
            })

        summary = str(result.get("summary", "")).strip() or text[:200]
        try:
            overall_sentiment = min(max(float(result.get("overall_sentiment", 0.0)), -1.0), 1.0)
        except (TypeError, ValueError):
            overall_sentiment = 0.0

        concept_sentiments = []
        for cs in result.get("concept_sentiments", []):
            cid = _normalise_id(str(cs.get("concept_id", "")))
            if not cid:
                continue
            try:
                s = min(max(float(cs.get("sentiment", 0.0)), -1.0), 1.0)
            except (TypeError, ValueError):
                s = 0.0
            concept_sentiments.append({"concept_id": cid, "sentiment": s, "label": cs.get("label", "neutral")})

        final_conf = sum(c["confidence"] for c in concepts) / max(len(concepts), 1)

        return {
            "agent_id":              self.agent_id,
            "agent_type":            "unified",
            "document_id":           document_id,
            "chunk_id":              chunk_id,
            "chunk_index":           chunk_index,
            "total_chunks":          total_chunks,
            "concepts":              concepts,
            "relationships":         relationships,
            "summary":               summary,
            "sentiment_score":       overall_sentiment,
            "sentiment_label":       result.get("sentiment_label", "neutral"),
            "concept_sentiments":    concept_sentiments,
            "confidence_overall":    round(final_conf, 3),
            # Agentic audit trail
            "react_iterations":      react_iterations,
            "extraction_strategy":   chunk_strategy,
            "doc_domain":            strategy.get("domain", "general"),
            "llm_used":              provider_used,
            "critic_filtered_count": critic_filtered,
            "processing_time_ms":    int((time.time() - t0) * 1000),
        }

    def _empty(self, chunk_id, document_id, chunk_index, total_chunks):
        return {
            "agent_id": self.agent_id, "agent_type": "unified",
            "document_id": document_id, "chunk_id": chunk_id,
            "chunk_index": chunk_index, "total_chunks": total_chunks,
            "concepts": [], "relationships": [], "summary": "",
            "sentiment_score": 0.0, "sentiment_label": "neutral",
            "concept_sentiments": [], "confidence_overall": 0.0,
            "react_iterations": 0, "extraction_strategy": "none",
            "doc_domain": "general", "llm_used": "none",
            "critic_filtered_count": 0, "processing_time_ms": 0,
        }


if __name__ == "__main__":
    asyncio.run(UnifiedAgent().run())
