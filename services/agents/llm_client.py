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


# Detect if we should use direct fallback (no LiteLLM proxy)
USE_DIRECT_FALLBACK = False
if os.getenv("GEMINI_API_KEY") or os.getenv("GROQ_API_KEY") or os.getenv("OPENROUTER_API_KEY"):
    if os.getenv("LITELLM_URL") is None or "litellm:4000" in LITELLM_URL:
        USE_DIRECT_FALLBACK = True


def _map_to_groq_model(model_tier: str) -> str:
    if model_tier == _MODEL_FAST:
        return "llama-3.1-8b-instant"
    return "llama-3.3-70b-versatile"


class LLMClient:
    """
    Thin wrapper around LiteLLM proxy.
    LiteLLM handles all provider routing, retries, rate limiting, and caching.
    If LiteLLM is not available, it cascades directly to Groq, Gemini, OpenRouter, or Ollama.
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

    async def _complete_groq_direct(
        self,
        system: str,
        user: str,
        max_tokens: int,
        model: str,
    ) -> Tuple[str, str]:
        """Call Groq API directly using round-robin rotation over configured keys."""
        keys = [
            os.getenv("GROQ_API_KEY"),
            os.getenv("GROQ_API_KEY_2"),
            os.getenv("GROQ_API_KEY_3"),
            os.getenv("GROQ_API_KEY_4"),
        ]
        active_keys = [k for k in keys if k]
        if not active_keys:
            raise RuntimeError("No GROQ_API_KEY is configured")

        last_exc = None
        for key in active_keys:
            try:
                resp = await self._http.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user",   "content": user},
                        ],
                        "max_tokens": max_tokens,
                        "temperature": 0.1,
                    },
                    timeout=30.0,
                )
                resp.raise_for_status()
                data = resp.json()
                text = data["choices"][0]["message"]["content"]
                return text, f"groq/{model} (direct)"
            except Exception as exc:
                last_exc = exc
                log.warning("groq_key_failed_trying_next", error=str(exc))
                continue
                
        raise RuntimeError(f"All Groq keys failed: {last_exc}")

    async def _complete_openrouter_direct(
        self,
        system: str,
        user: str,
        max_tokens: int,
        model: str = "openrouter/free",
    ) -> Tuple[str, str]:
        """Call OpenRouter API directly using OPENROUTER_API_KEY."""
        key = os.getenv("OPENROUTER_API_KEY")
        if not key:
            raise RuntimeError("OPENROUTER_API_KEY is not set")
            
        resp = await self._http.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/wrewre/AtlasMind",
                "X-Title": "AtlasMind",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user",   "content": user},
                ],
                "max_tokens": max_tokens,
                "temperature": 0.1,
            },
            timeout=45.0,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        return text, f"openrouter/{model} (direct)"

    async def _complete_ollama_direct(
        self,
        system: str,
        user: str,
        max_tokens: int,
        model: str = "llama3.2",
    ) -> Tuple[str, str]:
        """Call Ollama API directly using OLLAMA_HOST."""
        host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        resp = await self._http.post(
            f"{host}/api/generate",
            json={
                "model": model,
                "system": system,
                "prompt": user,
                "stream": False,
                "options": {
                    "temperature": 0.1,
                    "num_predict": max_tokens,
                }
            },
            timeout=120.0,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data.get("response", "")
        return text, f"ollama/{model} (direct)"

    async def complete(
        self,
        system: str,
        user: str,
        max_tokens: int = 1200,
        force_fast: bool = False,
        summary: bool = False,
    ) -> Tuple[str, str]:
        """
        Send a completion request. Cascades through:
        1. Direct Groq (Fastest & Free)
        2. Direct Gemini
        3. Direct OpenRouter (Free backup)
        4. Direct Ollama (Offline local backup)
        5. LiteLLM proxy (standard/local fallback if active)
        """
        model_tier = _pick_model(user, force_fast=force_fast, summary=summary)

        # Direct fallback cascade if LiteLLM is not running
        if USE_DIRECT_FALLBACK:
            errors = []
            
            # 1. Groq Direct
            if os.getenv("GROQ_API_KEY"):
                try:
                    groq_model = _map_to_groq_model(model_tier)
                    return await self._complete_groq_direct(system, user, max_tokens, groq_model)
                except Exception as exc:
                    errors.append(f"Groq: {exc}")
                    log.warning("direct_groq_failed_trying_gemini", error=str(exc))
            
            # 2. Gemini Direct
            if os.getenv("GEMINI_API_KEY"):
                try:
                    return await self._complete_gemini_direct(system, user, max_tokens)
                except Exception as exc:
                    errors.append(f"Gemini: {exc}")
                    log.warning("direct_gemini_failed_trying_openrouter", error=str(exc))

            # 3. OpenRouter Direct (Free models)
            if os.getenv("OPENROUTER_API_KEY"):
                try:
                    or_model = "openrouter/free"
                    return await self._complete_openrouter_direct(system, user, max_tokens, or_model)
                except Exception as exc:
                    errors.append(f"OpenRouter: {exc}")
                    log.warning("direct_openrouter_failed_trying_ollama", error=str(exc))

            # 4. Ollama Direct
            ollama_host = os.getenv("OLLAMA_HOST")
            if ollama_host and "ollama:11434" not in ollama_host:
                try:
                    ollama_model = os.getenv("OLLAMA_MODEL", "llama3.2")
                    return await self._complete_ollama_direct(system, user, max_tokens, ollama_model)
                except Exception as exc:
                    errors.append(f"Ollama: {exc}")
                    log.error("direct_ollama_failed", error=str(exc))

            raise RuntimeError(f"All direct LLM fallbacks failed: {'; '.join(errors)}")

        try:
            resp = await self._http.post(
                f"{LITELLM_URL}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {LITELLM_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model_tier,
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
            provider = data.get("model", model_tier)
            log.info("llm_success", model=model_tier, provider=provider)
            return text, provider

        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.HTTPStatusError, RuntimeError) as exc:
            # Fallback path if LiteLLM connection failed/unreachable
            if os.getenv("GROQ_API_KEY"):
                log.info("trying_direct_groq_fallback")
                try:
                    groq_model = _map_to_groq_model(model_tier)
                    return await self._complete_groq_direct(system, user, max_tokens, groq_model)
                except Exception as gr_exc:
                    log.error("direct_groq_fallback_failed", error=str(gr_exc))

            if os.getenv("GEMINI_API_KEY"):
                log.info("litellm_failed_falling_back_to_direct_gemini", error=str(exc))
                try:
                    return await self._complete_gemini_direct(system, user, max_tokens)
                except Exception as g_exc:
                    log.warning("direct_gemini_fallback_failed_trying_openrouter", error=str(g_exc))
            
            if os.getenv("OPENROUTER_API_KEY"):
                try:
                    or_model = "openrouter/free"
                    return await self._complete_openrouter_direct(system, user, max_tokens, or_model)
                except Exception as or_exc:
                    log.error("direct_openrouter_fallback_failed", error=str(or_exc))

            # Re-raise original error if no fallback worked
            if isinstance(exc, httpx.HTTPStatusError):
                body = exc.response.text[:300]
                log.error("litellm_http_error", status=exc.response.status_code, body=body)
                raise RuntimeError(f"LiteLLM {exc.response.status_code}: {body}") from exc
            raise RuntimeError(f"LiteLLM call failed: {exc}") from exc
        except httpx.TimeoutException:
            log.error("litellm_timeout", model=model_tier)
            raise RuntimeError(f"LiteLLM timeout for model '{model_tier}'")

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
