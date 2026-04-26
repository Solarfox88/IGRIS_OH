"""LLM Router - routes requests to local, API, or Vast.ai based on complexity."""

from __future__ import annotations

import logging
import time
from enum import Enum

import httpx

from igris.models.config import IgrisConfig, LLMConfig

logger = logging.getLogger("igris.advisory.router")


class LLMTier(str, Enum):
    LOCAL = "local"
    API = "api"
    VASTAI = "vastai"


class LLMResponse:
    """Unified LLM response."""

    def __init__(self, content: str, tier: LLMTier, model: str, tokens_used: int = 0, cost: float = 0.0, latency: float = 0.0):
        self.content = content
        self.tier = tier
        self.model = model
        self.tokens_used = tokens_used
        self.cost = cost
        self.latency = latency


class LLMRouter:
    """Routes LLM requests to the most cost-effective provider."""

    TOKEN_THRESHOLD_LOCAL = 2000
    TOKEN_THRESHOLD_API = 8000

    def __init__(self, config: IgrisConfig):
        self.config = config
        self.local_config = config.local_llm
        self.api_config = config.fallback_llm
        self.vastai_config = config.vastai
        self.total_cost = 0.0
        self.request_count = 0

    def estimate_complexity(self, prompt: str) -> LLMTier:
        prompt_len = len(prompt)
        if prompt_len < 3000:
            return LLMTier.LOCAL
        elif prompt_len < 15000:
            return LLMTier.API
        else:
            return LLMTier.VASTAI

    async def query(
        self,
        prompt: str,
        system_prompt: str = "",
        tier_override: LLMTier | None = None,
        max_tokens: int | None = None,
        messages: list[dict] | None = None,
    ) -> LLMResponse:
        tier = tier_override or self.estimate_complexity(prompt)
        self.request_count += 1
        local_error = None

        if tier == LLMTier.LOCAL:
            try:
                return await self._query_local(prompt, system_prompt, max_tokens, messages=messages)
            except Exception as e:
                local_error = e
                logger.warning(f"Local LLM failed: {e}")
                # Only fall back to API if API key is configured
                if self.api_config.api_key:
                    logger.info("Falling back to API tier")
                    tier = LLMTier.API
                else:
                    # No API key — re-raise if already ConnectionError, otherwise wrap
                    if isinstance(e, ConnectionError):
                        raise
                    err_type = type(e).__name__
                    raise ConnectionError(
                        f"Ollama non risponde ({err_type}: {e}). "
                        "Assicurati che Ollama sia in esecuzione: apri un terminale e lancia 'ollama serve'"
                    ) from e

        if tier == LLMTier.API:
            try:
                return await self._query_api(prompt, system_prompt, max_tokens, messages=messages)
            except Exception as e:
                logger.warning(f"API LLM failed: {e}")
                if self.vastai_config.api_key:
                    tier = LLMTier.VASTAI
                elif local_error:
                    raise ConnectionError(
                        f"Ollama non risponde ({local_error}). "
                        "Assicurati che Ollama sia in esecuzione: apri un terminale e lancia 'ollama serve'"
                    ) from local_error
                else:
                    raise

        if tier == LLMTier.VASTAI:
            return await self._query_vastai(prompt, system_prompt, max_tokens, messages=messages)

        raise RuntimeError("No LLM provider available")

    async def _query_local(
        self, prompt: str, system_prompt: str, max_tokens: int | None, messages: list[dict] | None = None,
    ) -> LLMResponse:
        start = time.time()
        config = self.local_config

        if config.provider == "ollama":
            return await self._query_ollama(prompt, system_prompt, max_tokens, start, messages=messages)
        else:
            return await self._query_openai_compatible(
                config, prompt, system_prompt, max_tokens, start, LLMTier.LOCAL, messages=messages
            )

    def _build_ollama_payload(
        self, prompt: str, system_prompt: str, max_tokens: int | None,
        messages: list[dict] | None = None, stream: bool = False,
    ) -> tuple[str, dict]:
        config = self.local_config
        url = f"{config.base_url}/api/chat"
        if messages:
            chat_messages = list(messages)
        else:
            chat_messages = []
            if system_prompt:
                chat_messages.append({"role": "system", "content": system_prompt})
            chat_messages.append({"role": "user", "content": prompt})

        payload = {
            "model": config.model,
            "messages": chat_messages,
            "stream": stream,
            "options": {
                "temperature": config.temperature,
                "num_predict": max_tokens or config.max_tokens,
            },
        }
        return url, payload

    async def _query_ollama(
        self, prompt: str, system_prompt: str, max_tokens: int | None, start: float,
        messages: list[dict] | None = None,
    ) -> LLMResponse:
        config = self.local_config
        url, payload = self._build_ollama_payload(prompt, system_prompt, max_tokens, messages, stream=False)

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(config.timeout_seconds)) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except (httpx.ConnectError, httpx.TimeoutException, OSError) as e:
            err_type = type(e).__name__
            raise ConnectionError(
                f"Impossibile connettersi a Ollama su {config.base_url} ({err_type}: {e}). "
                "Assicurati che Ollama sia in esecuzione: apri un terminale e lancia 'ollama serve'"
            ) from e

        content = data.get("message", {}).get("content", "")
        latency = time.time() - start
        logger.info(f"Ollama response ({config.model}): {latency:.1f}s, {len(content)} chars")

        return LLMResponse(
            content=content,
            tier=LLMTier.LOCAL,
            model=config.model,
            tokens_used=data.get("eval_count", 0),
            cost=0.0,
            latency=latency,
        )

    async def stream_ollama(
        self, prompt: str, system_prompt: str = "", max_tokens: int | None = None,
        messages: list[dict] | None = None,
    ):
        """Stream tokens from Ollama. Yields (token_str, is_done, metadata_or_none)."""
        import json as _json

        config = self.local_config
        url, payload = self._build_ollama_payload(
            prompt, system_prompt, max_tokens, messages, stream=True,
        )
        start = time.time()
        self.request_count += 1

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(config.timeout_seconds)) as client:
                async with client.stream("POST", url, json=payload) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        chunk = _json.loads(line)
                        token = chunk.get("message", {}).get("content", "")
                        done = chunk.get("done", False)
                        if token:
                            yield token, done, None
                        if done:
                            latency = time.time() - start
                            yield "", True, {
                                "tier": LLMTier.LOCAL.value,
                                "model": config.model,
                                "tokens": chunk.get("eval_count", 0),
                                "cost": 0.0,
                                "latency": round(latency, 2),
                            }
        except (httpx.ConnectError, httpx.TimeoutException, OSError) as e:
            err_type = type(e).__name__
            raise ConnectionError(
                f"Impossibile connettersi a Ollama su {config.base_url} ({err_type}: {e}). "
                "Assicurati che Ollama sia in esecuzione: apri un terminale e lancia 'ollama serve'"
            ) from e

    async def _query_api(
        self, prompt: str, system_prompt: str, max_tokens: int | None, messages: list[dict] | None = None,
    ) -> LLMResponse:
        start = time.time()
        return await self._query_openai_compatible(
            self.api_config, prompt, system_prompt, max_tokens, start, LLMTier.API, messages=messages
        )

    async def _query_openai_compatible(
        self,
        config: LLMConfig,
        prompt: str,
        system_prompt: str,
        max_tokens: int | None,
        start: float,
        tier: LLMTier,
        messages: list[dict] | None = None,
    ) -> LLMResponse:
        url = f"{config.base_url}/chat/completions"
        if messages:
            chat_messages = list(messages)
        else:
            chat_messages = []
            if system_prompt:
                chat_messages.append({"role": "system", "content": system_prompt})
            chat_messages.append({"role": "user", "content": prompt})

        headers = {"Content-Type": "application/json"}
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"

        payload = {
            "model": config.model,
            "messages": chat_messages,
            "max_tokens": max_tokens or config.max_tokens,
            "temperature": config.temperature,
        }

        async with httpx.AsyncClient(timeout=httpx.Timeout(config.timeout_seconds)) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        tokens = usage.get("total_tokens", 0)
        cost = (tokens / 1000) * config.cost_per_1k_tokens
        self.total_cost += cost
        latency = time.time() - start

        logger.info(
            f"API response ({config.model}): {latency:.1f}s, {tokens} tokens, ${cost:.4f}"
        )

        return LLMResponse(
            content=content,
            tier=tier,
            model=config.model,
            tokens_used=tokens,
            cost=cost,
            latency=latency,
        )

    async def _query_vastai(
        self, prompt: str, system_prompt: str, max_tokens: int | None, messages: list[dict] | None = None,
    ) -> LLMResponse:
        """Vast.ai query - provisions GPU instance for heavy inference.

        This is a simplified implementation. In production, this would:
        1. Search for available RTX 4090 instances
        2. Rent the cheapest one
        3. Deploy an inference server (vLLM/TGI)
        4. Query the inference server
        5. Destroy the instance when done
        """
        logger.info("Vast.ai GPU inference requested - falling back to API for now")
        logger.info(
            f"Vast.ai config: GPU={self.vastai_config.gpu_type}, "
            f"max_cost=${self.vastai_config.max_cost_per_hour}/h"
        )
        return await self._query_api(prompt, system_prompt, max_tokens, messages=messages)

    def get_cost_summary(self) -> dict:
        return {
            "total_cost": round(self.total_cost, 4),
            "total_requests": self.request_count,
            "avg_cost_per_request": round(
                self.total_cost / max(self.request_count, 1), 6
            ),
        }
