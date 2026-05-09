"""
Provider catalog — describes litellm open format.

No hardcoded provider list. Any litellm-compatible model name works.
"""

from typing import TypedDict


class ProviderInfo(TypedDict):
    id: str
    name: str
    description: str
    model_hint: str


CATALOG: list[ProviderInfo] = [
    {
        "id": "litellm",
        "name": "LiteLLM (Open Format)",
        "description": (
            "支持 100+ 供应商。填写任意 litellm 模型名，如 openai/gpt-4o、"
            "anthropic/claude-3-5-sonnet-20241022、deepseek/deepseek-chat 等。"
        ),
        "model_hint": "任意 litellm 支持的 model name，格式：provider/model 或纯 model 名",
    },
]


def get_catalog() -> list[ProviderInfo]:
    return CATALOG