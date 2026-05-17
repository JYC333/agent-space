"""SourcePointer metadata_json safety — provenance labels only, no raw content.

HTTP JSON deserializes to dict/list/scalars only. Service-layer validation also rejects
tuple, set, bytes, and non-JSON types so internal callers cannot bypass API shape rules.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

# Keys that must never appear in metadata_json at any depth (case-insensitive).
UNSAFE_METADATA_KEYS = frozenset({
    "content",
    "body",
    "raw_content",
    "payload",
    "summary",
    "copied_text",
    "source_snapshot",
    "memory_text",
    "artifact_payload",
})
_UNSAFE_KEYS_FOLDED = frozenset(k.casefold() for k in UNSAFE_METADATA_KEYS)

# Shape/size caps for user-supplied provenance metadata (not source content).
MAX_METADATA_BYTES = 16_384
MAX_METADATA_DEPTH = 8
MAX_METADATA_TOTAL_ITEMS = 256
MAX_METADATA_KEY_LENGTH = 128
MAX_METADATA_STRING_LENGTH = 2_048


class InvalidSourcePointerMetadataError(ValueError):
    """Raised when metadata_json is unsafe, oversized, or too deeply nested."""


def _is_unsafe_key(key: object) -> bool:
    if not isinstance(key, str):
        return False
    return key.casefold() in _UNSAFE_KEYS_FOLDED


def _check_metadata_byte_size(metadata_json: dict) -> None:
    try:
        payload = json.dumps(metadata_json, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise InvalidSourcePointerMetadataError(
            "metadata_json must be JSON-serializable"
        ) from exc
    size = len(payload.encode("utf-8"))
    if size > MAX_METADATA_BYTES:
        raise InvalidSourcePointerMetadataError(
            f"metadata_json exceeds {MAX_METADATA_BYTES} bytes (got {size})"
        )


def _reject_non_json_container(node: object, *, path: str) -> None:
    if isinstance(node, (tuple, set)):
        loc = path or "root"
        raise InvalidSourcePointerMetadataError(
            f"metadata_json must not contain {type(node).__name__} at {loc!r}"
        )
    if isinstance(node, (bytes, bytearray)):
        loc = path or "root"
        raise InvalidSourcePointerMetadataError(
            f"metadata_json must not contain bytes at {loc!r}"
        )


def _validate_metadata_node(
    node: object,
    *,
    path: str,
    depth: int,
    item_count: list[int],
) -> None:
    """Walk dicts/lists recursively; reject forbidden keys and enforce shape limits."""
    _reject_non_json_container(node, path=path)

    if depth > MAX_METADATA_DEPTH:
        raise InvalidSourcePointerMetadataError(
            f"metadata_json nesting exceeds max depth {MAX_METADATA_DEPTH}"
        )

    if isinstance(node, Mapping):
        if isinstance(node, dict):
            mapping = node
        else:
            mapping = dict(node)
        for key, value in mapping.items():
            if not isinstance(key, str):
                loc = f"{path}[{key!r}]" if path else repr(key)
                raise InvalidSourcePointerMetadataError(
                    f"metadata_json object keys must be strings at {loc}"
                )
            if len(key) > MAX_METADATA_KEY_LENGTH:
                loc = f"{path}.{key}" if path else key
                raise InvalidSourcePointerMetadataError(
                    f"metadata_json key exceeds {MAX_METADATA_KEY_LENGTH} characters at {loc!r}"
                )
            if _is_unsafe_key(key):
                loc = f"{path}.{key}" if path else str(key)
                raise InvalidSourcePointerMetadataError(
                    f"metadata_json must not contain content keys at {loc!r}"
                )
            item_count[0] += 1
            if item_count[0] > MAX_METADATA_TOTAL_ITEMS:
                raise InvalidSourcePointerMetadataError(
                    f"metadata_json exceeds {MAX_METADATA_TOTAL_ITEMS} total items"
                )
            child_path = f"{path}.{key}" if path else str(key)
            _validate_metadata_node(
                value, path=child_path, depth=depth + 1, item_count=item_count
            )
    elif isinstance(node, Sequence) and not isinstance(node, (str, bytes, bytearray)):
        for index, item in enumerate(node):
            item_count[0] += 1
            if item_count[0] > MAX_METADATA_TOTAL_ITEMS:
                raise InvalidSourcePointerMetadataError(
                    f"metadata_json exceeds {MAX_METADATA_TOTAL_ITEMS} total items"
                )
            _validate_metadata_node(
                item, path=f"{path}[{index}]", depth=depth + 1, item_count=item_count
            )
    elif node is None or isinstance(node, (bool, int, float)):
        return
    elif isinstance(node, str):
        if len(node) > MAX_METADATA_STRING_LENGTH:
            loc = path or "root"
            raise InvalidSourcePointerMetadataError(
                f"metadata_json string exceeds {MAX_METADATA_STRING_LENGTH} characters at {loc!r}"
            )
    else:
        loc = path or "root"
        raise InvalidSourcePointerMetadataError(
            f"metadata_json contains unsupported type {type(node).__name__} at {loc!r}"
        )


def validate_metadata_json(metadata_json: dict | None) -> None:
    """Reject unsafe keys, oversize payloads, and excessive nesting/item counts."""
    if metadata_json is None:
        return
    if not isinstance(metadata_json, dict):
        raise InvalidSourcePointerMetadataError(
            "metadata_json must be a JSON object at the top level"
        )
    if not metadata_json:
        return
    _validate_metadata_node(metadata_json, path="", depth=1, item_count=[0])
    _check_metadata_byte_size(metadata_json)
