"""
Concept Extraction Agent
========================
Extracts key concepts, entities, and topics from each text chunk.
Uses the multi-model cascade: Gemini → Groq.

Handles empty LLM responses gracefully — returns empty concepts list
rather than crashing, so the pipeline always progresses.
"""
from __future__ import annotations

import asyncio
import sys
import uuid
from typing import Any, Dict

sys.path.insert(0, "/app")

from base_agent import BaseAgent
from llm_client import get_llm_client

SYSTEM_PROMPT = """You are a precise concept extraction engine for knowledge graph construction.

Extract key concepts (entities, topics, technologies, ideas, processes) from the given text chunk.

Rules:
- Focus on MEANINGFUL concepts — not stop words or generic terms
- Category must be one of: ENTITY | TECHNOLOGY | PROCESS | CONCEPT | PERSON | ORGANIZATION | LOCATION | EVENT
- Confidence 0.0-1.0: how clearly the concept appears in the text
- ID must be snake_case (e.g. "machine_learning", "neural_network")
- Prefer canonical forms: "AI" becomes "artificial_intelligence"
- Extract 5 to 15 concepts depending on text density

Respond with ONLY valid JSON, no markdown, no explanation:
{
  "concepts": [
    {"id": "concept_id", "label": "Human Label", "category": "CATEGORY", "confidence": 0.95}
  ]
}"""

USER_TMPL = """Extract key concepts from this text chunk:

--- TEXT ---
{text}
--- END ---

Output only the JSON object."""


class ConceptAgent(BaseAgent):

    def __init__(self):
        super().__init__(agent_type="concept")
        self.llm = get_llm_client()

    async def process_chunk(self, data: Dict[str, Any]) -> Dict[str, Any]:
        chunk_id     = data.get("chunk_id",     str(uuid.uuid4()))
        document_id  = data.get("document_id",  "")
        chunk_index  = int(data.get("chunk_index",  0))
        total_chunks = int(data.get("total_chunks", 1))
        text         = data.get("text", "").strip()

        if not text:
            return self._empty(chunk_id, document_id, chunk_index, total_chunks)

        # Truncate to avoid token limit issues
        truncated = text[:2500]

        try:
            result = await self.llm.complete_json(
                SYSTEM_PROMPT,
                USER_TMPL.format(text=truncated),
            )
        except Exception as exc:
            self.log.error("llm_call_failed", chunk_index=chunk_index, error=str(exc))
            raise  # Let base_agent retry/DLQ handle it

        concepts = []
        for c in result.get("concepts", []):
            raw_id = str(c.get("id", "")).strip()
            label  = str(c.get("label", "")).strip()
            if not raw_id or not label:
                continue
            # Normalise ID
            cid = raw_id.lower().replace(" ", "_").replace("-", "_").replace(".", "_")
            # Remove non-alphanumeric except underscore
            import re
            cid = re.sub(r"[^\w]", "_", cid).strip("_")
            if not cid:
                continue
            concepts.append({
                "id":              cid,
                "label":           label,
                "category":        str(c.get("category", "CONCEPT")).upper(),
                "confidence":      min(max(float(c.get("confidence", 0.7)), 0.0), 1.0),
                "source_chunk_id": chunk_id,
            })

        avg_conf = (sum(c["confidence"] for c in concepts) / len(concepts)) if concepts else 0.5

        return {
            "agent_id":           self.agent_id,
            "agent_type":         "concept",
            "document_id":        document_id,
            "chunk_id":           chunk_id,
            "chunk_index":        chunk_index,
            "total_chunks":       total_chunks,
            "concepts":           concepts,
            "relationships":      [],
            "summary":            None,
            "sentiment_score":    None,
            "confidence_overall": avg_conf,
        }

    def _empty(self, chunk_id, document_id, chunk_index, total_chunks):
        return {
            "agent_id": self.agent_id, "agent_type": "concept",
            "document_id": document_id, "chunk_id": chunk_id,
            "chunk_index": chunk_index, "total_chunks": total_chunks,
            "concepts": [], "relationships": [], "summary": None,
            "confidence_overall": 0.0,
        }


if __name__ == "__main__":
    asyncio.run(ConceptAgent().run())
