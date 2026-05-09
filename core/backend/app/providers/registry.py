"""
Provider registry — maps provider type string to a provider adapter.

Future: register direct implementations (Anthropic SDK, OpenAI SDK, etc.)
when LiteLLM is insufficient for a specific vendor.
"""

from typing import Protocol, AsyncIterator

from .models import ChatRequest, ChatResponse, StreamChunk


class ProviderAdapter(Protocol):
    """Interface for all provider adapters."""

    async def complete(self, api_key: str, api_base: str | None, request: ChatRequest) -> ChatResponse:
        """Synchronous completion — returns full response."""
        ...

    async def stream(self, api_key: str, api_base: str | None, request: ChatRequest) -> AsyncIterator[StreamChunk]:
        """Streaming completion — yields chunks."""
        ...


class ProviderRegistry:
    """Global registry of provider adapters."""

    def __init__(self) -> None:
        self._adapters: dict[str, ProviderAdapter] = {}

    def register(self, name: str, adapter: ProviderAdapter) -> None:
        self._adapters[name] = adapter

    def get(self, name: str) -> ProviderAdapter | None:
        return self._adapters.get(name)

    def list_adapters(self) -> list[str]:
        return list(self._adapters.keys())


# Global registry instance
registry = ProviderRegistry()