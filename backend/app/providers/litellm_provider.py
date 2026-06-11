"""
LiteLLM provider adapter — translates agent-space requests into litellm calls.

Responsibilities:
- translate agent-space model config into LiteLLM model name and params
- call litellm completion/streaming
- normalize output into agent-space response schema
"""

import logging
from typing import AsyncIterator

import litellm

from .models import ChatRequest, ChatResponse, StreamChunk
from .registry import ProviderAdapter

log = logging.getLogger(__name__)


class LiteLLMProvider:
    """
    Implements ProviderAdapter using litellm as the underlying transport.
    """

    async def complete(
        self, api_key: str, api_base: str | None, request: ChatRequest
    ) -> ChatResponse:
        """Synchronous completion via litellm."""
        params = self._build_params(api_key, api_base, request)

        try:
            response = await litellm.acompletion(**params)
        except Exception as exc:
            log.warning("LiteLLM completion failed: %s", exc)
            raise

        return ChatResponse(
            content=response.choices[0].message.content or "",
            provider=response.model.split("/")[0] if "/" in response.model else response.model,
            model=response.model,
            usage={
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            },
        )

    async def stream(
        self, api_key: str, api_base: str | None, request: ChatRequest
    ) -> AsyncIterator[StreamChunk]:
        """Streaming completion via litellm."""
        params = self._build_params(api_key, api_base, request)
        params["stream"] = True

        try:
            response = await litellm.acompletion(**params)
        except Exception as exc:
            log.warning("LiteLLM streaming failed: %s", exc)
            raise

        async for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield StreamChunk(delta=chunk.choices[0].delta.content)

            # Check if streaming is done
            if chunk.choices and getattr(chunk.choices[0], "finish_reason", None):
                yield StreamChunk(
                    delta="",
                    finish_reason=chunk.choices[0].finish_reason,
                )
                break

    def _build_params(
        self, api_key: str, api_base: str | None, request: ChatRequest
    ) -> dict:
        """
        Build litellm params from a ChatRequest.

        LiteLLM model name format: "provider/model" (e.g. "openai/gpt-4o").
        If request.model already contains a slash, use as-is.
        If not, LiteLLM will resolve it using the provider's default.
        """
        model = request.model or "gpt-4o"  # fallback if unspecified

        messages = [{"role": m.role, "content": m.content} for m in request.messages]
        if request.system:
            messages.insert(0, {"role": "system", "content": request.system})

        params: dict = {
            "model": model,
            "api_key": api_key,
            "messages": messages,
        }

        if api_base:
            params["api_base"] = api_base

        if request.temperature is not None:
            params["temperature"] = request.temperature

        if request.max_tokens is not None:
            params["max_tokens"] = request.max_tokens

        return params


# Register the adapter
from .registry import registry

registry.register("litellm", LiteLLMProvider())