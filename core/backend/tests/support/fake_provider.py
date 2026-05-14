"""Deterministic async provider double for unit tests (no ``litellm`` / network)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.providers.models import ChatRequest, ChatResponse, StreamChunk


@dataclass
class FakeProviderConfig:
    content: str = "fake-provider-content"
    provider: str = "fake"
    model: str = "fake/test-model"
    usage: dict[str, int] = field(
        default_factory=lambda: {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3}
    )
    fail: bool = False
    failure_message: str = "fake provider failure"


class DeterministicFakeProvider:
    """Drop-in style test double with ``async complete`` / ``async stream``."""

    def __init__(self, config: FakeProviderConfig | None = None) -> None:
        self.config = config or FakeProviderConfig()

    async def complete(
        self, api_key: str, api_base: str | None, request: ChatRequest
    ) -> ChatResponse:
        del api_key, api_base
        if self.config.fail:
            raise RuntimeError(self.config.failure_message)
        model = request.model or self.config.model
        return ChatResponse(
            content=self.config.content,
            provider=self.config.provider,
            model=model,
            usage=dict(self.config.usage),
        )

    async def stream(
        self, api_key: str, api_base: str | None, request: ChatRequest
    ):
        del request
        if self.config.fail:
            raise RuntimeError(self.config.failure_message)
        del api_key, api_base
        yield StreamChunk(delta=self.config.content)
        yield StreamChunk(delta="", finish_reason="stop")
