"""
LLM Client — LiteLLM Proxy Backend
=====================================
All LLM calls route through the LiteLLM proxy which handles:
  - Load balancing: Together.ai → Groq×4 → Gemini → Ollama
  - Per-provider rate limiting via Redis (shared across all containers)
  - Automatic fallbacks on 429/timeout
  - Semantic caching (Redis, 1h TTL)

Model names (defined in litellm_config.yaml):
  "extraction"      → Together.ai qwen2.5-72b → Groq llama-3.3-70b×4 → Gemini → Ollama
  "fast-extraction" → Groq llama-3.1-8b×4 → Ollama  (short/simple chunks)
  "summary"         → Together.ai → Groq → Gemini → Ollama  (once per doc)

Routing rule: chunks < 600 chars → fast-extraction, else → extraction.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Optional, Tuple

import httpx
import structlog

log = structlog.get_logger("llm_client")

# ── LiteLLM proxy config ──────────────────────────────────────────────────────
LITELLM_URL = os.getenv("LITELLM_URL", "http://litellm:4000")
LITELLM_KEY = os.getenv("LITELLM_API_KEY", "sk-mindmap-master-key-2025")

_MODEL_EXTRACTION = "extraction"
_MODEL_FAST       = "fast-extraction"
_MODEL_SUMMARY    = "summary"
_SIMPLE_CHUNK_LEN = 600   # chars — below this, route to fast model


def _pick_model(text: str, force_fast: bool = False, summary: bool = False) -> str:
    """Select model tier based on task type and text length."""
    if summary:
        return _MODEL_SUMMARY
    if force_fast or len(text) < _SIMPLE_CHUNK_LEN:
        return _MODEL_FAST
    return _MODEL_EXTRACTION


class LLMClient:
    """
    Thin wrapper around LiteLLM proxy.
    All routing, retries, rate limiting and caching live in litellm_config.yaml.
    This class is intentionally simple — complexity belongs in the config layer.
    """

    def __init__(self):
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(90.0, connect=10.0),
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
        )

    async def complete(
        self,
        system: str,
        user: str,
        max_tokens: int = 1200,
        force_fast: bool = False,
        summary: bool = False,
    ) -> Tuple[str, str]:
        """
        Send a completion request through LiteLLM proxy.
        Returns (text, model_name_used).
        LiteLLM handles all fallbacks internally — if this raises, all providers failed.
        """
        model = _pick_model(user, force_fast=force_fast, summary=summary)

        try:
            resp = await self._http.post(
                f"{LITELLM_URL}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {LITELLM_KEY}",
                    "Content-Type":  "application/json",
                },
                json={
                    "model":       model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user",   "content": user},
                    ],
                    "max_tokens":  max_tokens,
                    "temperature": 0.1,
                },
            )
            resp.raise_for_status()
            data     = resp.json()
            text     = data["choices"][0]["message"]["content"]
            provider = data.get("model", model)
            log.info("llm_success", model=model, provider=provider,
                     tokens=data.get("usage", {}).get("total_tokens", 0))
            return text, provider

        except httpx.HTTPStatusError as e:
            body = e.response.text[:300]
            log.error("litellm_http_error", status=e.response.status_code, body=body)
            raise RuntimeError(f"LiteLLM {e.response.status_code}: {body}")
        except httpx.TimeoutException:
            log.error("litellm_timeout", model=model)
            raise RuntimeError(f"LiteLLM timeout for model '{model}'")
        except Exception as exc:
            log.error("litellm_error", model=model, error=str(exc)[:200])
            raise RuntimeError(f"LiteLLM call failed: {exc}")

    async def complete_json(
        self,
        system: str,
        user: str,
        max_tokens: int = 1200,
        force_fast: bool = False,
        summary: bool = False,
    ) -> Dict[str, Any]:
        """complete() then parse JSON from the response, with multiple fallback patterns."""
        text, provider = await self.complete(
            system, user, max_tokens, force_fast=force_fast, summary=summary
        )

        clean = re.sub(r"^```(?:json)?\s*", "", text.strip())
        clean = re.sub(r"\s*```\s*$",        "", clean.strip())

        for pattern in [
            lambda s: json.loads(s),
            lambda s: json.loads(re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', s, re.DOTALL).group()),
            lambda s: json.loads(re.search(r'\{.*\}', s, re.DOTALL).group()),
        ]:
            try:
                return pattern(clean)
            except Exception:
                pass

        log.warning("json_parse_failed", provider=provider, preview=text[:200])
        return {}

    async def aclose(self):
        await self._http.aclose()


# ── Singleton ─────────────────────────────────────────────────────────────────
_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
