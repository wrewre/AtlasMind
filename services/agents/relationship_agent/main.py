"""
Relationship Extraction Agent
==============================
Identifies directed semantic relationships between concepts.
Uses Gemini → Groq cascade.
"""
from __future__ import annotations

import asyncio
import re
import sys
import uuid
from typing import Any, Dict

sys.path.insert(0, "/app")

from base_agent import BaseAgent
from llm_client import get_llm_client

VALID_RELATION_TYPES = {
    "is_a", "part_of", "causes", "enables", "requires",
    "uses", "implements", "related_to", "contrasts_with", "produces",
}

SYSTEM_PROMPT = """You are a relationship extraction engine for knowledge graphs.

Identify directed semantic relationships between concepts in the text.

Allowed relation_type values (use EXACTLY these strings):
  is_a | part_of | causes | enables | requires | uses | implements | related_to | contrasts_with | produces

Rules:
- source and target must be snake_case concept IDs found in the text
- Confidence 0.0-1.0, only include relationships with confidence >= 0.45
- Extract 3 to 10 relationships per chunk
- label = short verb phrase (e.g. "is a subset of", "requires training data")

Respond with ONLY valid JSON, no markdown:
{
  "relationships": [
    {"source": "deep_learning", "target": "neural_network", "relation_type": "uses",
     "label": "uses multilayer networks", "confidence": 0.92}
  ]
}"""

USER_TMPL = """Identify semantic relationships between concepts in this text:

--- TEXT ---
{text}
--- END ---

Output only the JSON object."""


class RelationshipAgent(BaseAgent):

    def __init__(self):
        super().__init__(agent_type="relationship")
        self.llm = get_llm_client()

    async def process_chunk(self, data: Dict[str, Any]) -> Dict[str, Any]:
        chunk_id     = data.get("chunk_id",     str(uuid.uuid4()))
        document_id  = data.get("document_id",  "")
        chunk_index  = int(data.get("chunk_index",  0))
        total_chunks = int(data.get("total_chunks", 1))
        text         = data.get("text", "").strip()

        if not text:
            return self._empty(chunk_id, document_id, chunk_index, total_chunks)

        try:
            result = await self.llm.complete_json(
                SYSTEM_PROMPT,
                USER_TMPL.format(text=text[:2500]),
            )
        except Exception as exc:
            self.log.error("llm_call_failed", chunk_index=chunk_index, error=str(exc))
            raise

        def normalise_id(raw: str) -> str:
            cid = raw.lower().strip().replace(" ", "_").replace("-", "_").replace(".", "_")
            return re.sub(r"[^\w]", "_", cid).strip("_")

        rels = []
        for r in result.get("relationships", []):
            src = normalise_id(str(r.get("source", "")))
            tgt = normalise_id(str(r.get("target", "")))
            if not src or not tgt or src == tgt:
                continue
            conf = min(max(float(r.get("confidence", 0.6)), 0.0), 1.0)
            if conf < 0.45:
                continue
            rel_type = r.get("relation_type", "related_to")
            if rel_type not in VALID_RELATION_TYPES:
                rel_type = "related_to"
            rels.append({
                "source":          src,
                "target":          tgt,
                "relation_type":   rel_type,
                "label":           str(r.get("label", rel_type.replace("_", " "))).strip(),
                "confidence":      conf,
                "source_chunk_id": chunk_id,
            })

        avg_conf = (sum(r["confidence"] for r in rels) / len(rels)) if rels else 0.5

        return {
            "agent_id":           self.agent_id,
            "agent_type":         "relationship",
            "document_id":        document_id,
            "chunk_id":           chunk_id,
            "chunk_index":        chunk_index,
            "total_chunks":       total_chunks,
            "concepts":           [],
            "relationships":      rels,
            "summary":            None,
            "confidence_overall": avg_conf,
        }

    def _empty(self, chunk_id, document_id, chunk_index, total_chunks):
        return {
            "agent_id": self.agent_id, "agent_type": "relationship",
            "document_id": document_id, "chunk_id": chunk_id,
            "chunk_index": chunk_index, "total_chunks": total_chunks,
            "concepts": [], "relationships": [], "summary": None,
            "confidence_overall": 0.0,
        }


if __name__ == "__main__":
    asyncio.run(RelationshipAgent().run())
