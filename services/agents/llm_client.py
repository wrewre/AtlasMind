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


# Detect if we should use direct Gemini fallback
USE_DIRECT_GEMINI = False
gemini_key = os.getenv("GEMINI_API_KEY")
if gemini_key:
    # On Railway, we don't have LiteLLM container running, so bypass to avoid 10s timeouts
    if os.getenv("LITELLM_URL") is None or "litellm:4000" in LITELLM_URL:
        USE_DIRECT_GEMINI = True


class LLMClient:
    """
    Thin wrapper around LiteLLM proxy.
    LiteLLM handles all provider routing, retries, rate limiting, and caching.
    If LiteLLM is not available, it falls back to direct Gemini API calls.
    """

    def __init__(self):
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(90.0, connect=10.0),
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
        )

    async def _complete_gemini_direct(
        self,
        system: str,
        user: str,
        max_tokens: int,
    ) -> Tuple[str, str]:
        """Call Gemini API directly using GEMINI_API_KEY (bypassing LiteLLM)."""
        key = os.getenv("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("GEMINI_API_KEY is not set")
            
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={key}"
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": user}]
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": max_tokens
            }
        }
        if system:
            payload["systemInstruction"] = {
                "parts": [{"text": system}]
            }

        resp = await self._http.post(
            url,
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=60.0,
        )
        resp.raise_for_status()
        data = resp.json()
        
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            return text, "gemini-2.0-flash (direct)"
        except (KeyError, IndexError):
            log.error("gemini_direct_parse_error", response=data)
            raise RuntimeError("Failed to parse direct Gemini API response")

    async def complete(
        self,
        system: str,
        user: str,
        max_tokens: int = 1200,
        force_fast: bool = False,
        summary: bool = False,
    ) -> Tuple[str, str]:
        """
        Send a completion request to LiteLLM proxy.
        If the proxy is not running or fails, falls back to direct Gemini API.
        """
        model = _pick_model(user, force_fast=force_fast, summary=summary)

        # Direct call if detected (e.g. on Railway free tier)
        if USE_DIRECT_GEMINI:
            try:
                return await self._complete_gemini_direct(system, user, max_tokens)
            except Exception as exc:
                log.warning("direct_gemini_failed_trying_litellm", error=str(exc))

        try:
            resp = await self._http.post(
                f"{LITELLM_URL}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {LITELLM_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
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
            log.info("llm_success", model=model, provider=provider)
            return text, provider

        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.HTTPStatusError, RuntimeError) as exc:
            # Automatic fallback to direct Gemini if LiteLLM proxy connection failed
            if os.getenv("GEMINI_API_KEY") and not USE_DIRECT_GEMINI:
                log.info("litellm_failed_falling_back_to_direct_gemini", error=str(exc))
                try:
                    return await self._complete_gemini_direct(system, user, max_tokens)
                except Exception as g_exc:
                    raise RuntimeError(f"Direct Gemini fallback failed: {g_exc}") from exc
            
            # Re-raise or format error if fallback not available
            if isinstance(exc, httpx.HTTPStatusError):
                body = exc.response.text[:300]
                log.error("litellm_http_error", status=exc.response.status_code, body=body)
                raise RuntimeError(f"LiteLLM {exc.response.status_code}: {body}") from exc
            raise RuntimeError(f"LiteLLM call failed: {exc}") from exc
        except httpx.TimeoutException:
            log.error("litellm_timeout", model=model)
            raise RuntimeError(f"LiteLLM timeout for model '{model}'")

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
