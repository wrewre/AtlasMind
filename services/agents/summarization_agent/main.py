"""
Summarization Agent
===================
Generates concise 1-3 sentence summaries of each chunk.
The consensus engine merges these into a global document summary.
"""
from __future__ import annotations

import asyncio
import sys
import uuid
from typing import Any, Dict

sys.path.insert(0, "/app")

from base_agent import BaseAgent
from llm_client import get_llm_client

SYSTEM_PROMPT = """You are a concise summarization engine for knowledge management.

Summarise the given text chunk in 1-3 sentences.

Rules:
- Be factual and objective
- Include important named entities if present
- Do NOT add opinions or inferences beyond the text
- key_topics: 2-5 short topic strings

Respond with ONLY valid JSON, no markdown:
{
  "summary": "One to three sentence summary.",
  "key_topics": ["topic1", "topic2"],
  "confidence": 0.9
}"""

USER_TMPL = """Summarise this text chunk:

--- TEXT ---
{text}
--- END ---

Output only the JSON object."""


class SummarizationAgent(BaseAgent):

    def __init__(self):
        super().__init__(agent_type="summarization")
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
                max_tokens=400,
            )
        except Exception as exc:
            self.log.error("llm_call_failed", chunk_index=chunk_index, error=str(exc))
            raise

        summary = str(result.get("summary", "")).strip()
        # Fallback: use first 200 chars of text if LLM returned empty
        if not summary:
            summary = text[:200] + ("..." if len(text) > 200 else "")

        return {
            "agent_id":           self.agent_id,
            "agent_type":         "summarization",
            "document_id":        document_id,
            "chunk_id":           chunk_id,
            "chunk_index":        chunk_index,
            "total_chunks":       total_chunks,
            "concepts":           [],
            "relationships":      [],
            "summary":            summary,
            "key_topics":         result.get("key_topics", []),
            "confidence_overall": min(max(float(result.get("confidence", 0.8)), 0.0), 1.0),
        }

    def _empty(self, chunk_id, document_id, chunk_index, total_chunks):
        return {
            "agent_id": self.agent_id, "agent_type": "summarization",
            "document_id": document_id, "chunk_id": chunk_id,
            "chunk_index": chunk_index, "total_chunks": total_chunks,
            "concepts": [], "relationships": [], "summary": "",
            "confidence_overall": 0.0,
        }


if __name__ == "__main__":
    asyncio.run(SummarizationAgent().run())
