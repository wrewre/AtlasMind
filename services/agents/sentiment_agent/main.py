"""
Sentiment Analysis Agent
========================
Assigns sentiment scores to the text chunk and to individual concepts.
Enriches graph nodes with tonal context.
Scale: -1.0 (very negative) to +1.0 (very positive).
"""
from __future__ import annotations

import asyncio
import sys
import uuid
from typing import Any, Dict

sys.path.insert(0, "/app")

from base_agent import BaseAgent
from llm_client import get_llm_client

SYSTEM_PROMPT = """You are a sentiment analysis engine specialised in concept-level sentiment.

Analyse the overall sentiment AND how specific concepts are framed in the text.
Sentiment scale: -1.0 (very negative) to +1.0 (very positive), 0.0 = neutral.
Labels: positive | neutral | negative | mixed

Respond with ONLY valid JSON, no markdown:
{
  "overall_sentiment": 0.2,
  "overall_label": "neutral",
  "concept_sentiments": [
    {"concept_id": "machine_learning", "sentiment": 0.8, "label": "positive"}
  ],
  "confidence": 0.85
}"""

USER_TMPL = """Analyse sentiment in this text:

--- TEXT ---
{text}
--- END ---

Output only the JSON object."""


class SentimentAgent(BaseAgent):

    def __init__(self):
        super().__init__(agent_type="sentiment")
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
                USER_TMPL.format(text=text[:2000]),
                max_tokens=400,
            )
        except Exception as exc:
            self.log.error("llm_call_failed", chunk_index=chunk_index, error=str(exc))
            raise

        overall = result.get("overall_sentiment", 0.0)
        try:
            overall = min(max(float(overall), -1.0), 1.0)
        except (TypeError, ValueError):
            overall = 0.0

        concept_sentiments = []
        for cs in result.get("concept_sentiments", []):
            cid = str(cs.get("concept_id", "")).strip()
            if not cid:
                continue
            try:
                s = min(max(float(cs.get("sentiment", 0.0)), -1.0), 1.0)
            except (TypeError, ValueError):
                s = 0.0
            concept_sentiments.append({
                "concept_id": cid.lower().replace(" ", "_"),
                "sentiment":  s,
                "label":      cs.get("label", "neutral"),
            })

        return {
            "agent_id":           self.agent_id,
            "agent_type":         "sentiment",
            "document_id":        document_id,
            "chunk_id":           chunk_id,
            "chunk_index":        chunk_index,
            "total_chunks":       total_chunks,
            "concepts":           [],
            "relationships":      [],
            "summary":            None,
            "sentiment_score":    overall,
            "sentiment_label":    result.get("overall_label", "neutral"),
            "concept_sentiments": concept_sentiments,
            "confidence_overall": min(max(float(result.get("confidence", 0.7)), 0.0), 1.0),
        }

    def _empty(self, chunk_id, document_id, chunk_index, total_chunks):
        return {
            "agent_id": self.agent_id, "agent_type": "sentiment",
            "document_id": document_id, "chunk_id": chunk_id,
            "chunk_index": chunk_index, "total_chunks": total_chunks,
            "concepts": [], "relationships": [], "summary": None,
            "sentiment_score": 0.0, "sentiment_label": "neutral",
            "concept_sentiments": [], "confidence_overall": 0.0,
        }


if __name__ == "__main__":
    asyncio.run(SentimentAgent().run())
