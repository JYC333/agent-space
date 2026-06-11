"""Validation for PersonalMemoryGrant memory_filter and event metadata.

memory_filter validation:
  Allowed top-level keys: schema_version, memory_layers, memory_kinds, max_items, namespaces
  Rejected keys: scope_types, semantic, preference, memory_ids, raw_query, content_query,
    include_restricted, include_highly_restricted, and any content-bearing keys.

Event metadata validation:
  Rejects content-bearing keys recursively (superset of SourcePointer unsafe keys).
  No raw memory text, generated summaries, or personal memory IDs may be stored.
"""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence


# ---------------------------------------------------------------------------
# memory_filter_json validation
# ---------------------------------------------------------------------------

REJECTED_FILTER_KEYS = frozenset({
    "scope_types",
    "semantic",
    "preference",
    "memory_ids",
    "raw_query",
    "content_query",
    "include_restricted",
    "include_highly_restricted",
    # content-bearing keys not appropriate in a filter spec
    "content",
    "body",
    "raw_content",
    "payload",
    "summary",
    "copied_text",
    "source_snapshot",
    "memory_text",
    "artifact_payload",
    "generated_summary",
    "personal_memory_text",
})
_REJECTED_FILTER_KEYS_FOLDED = frozenset(k.casefold() for k in REJECTED_FILTER_KEYS)

MIN_MAX_ITEMS = 1
MAX_MAX_ITEMS = 20

SUPPORTED_SCHEMA_VERSIONS = frozenset({1})


class InvalidGrantFilterError(ValueError):
    """Raised when memory_filter_json contains rejected or invalid fields."""


def validate_memory_filter(memory_filter: dict | None) -> None:
    """Reject unsafe or unsupported filter keys; validate max_items range."""
    if memory_filter is None:
        return
    if not isinstance(memory_filter, dict):
        raise InvalidGrantFilterError("memory_filter must be a JSON object")

    if "schema_version" not in memory_filter:
        raise InvalidGrantFilterError(
            "memory_filter must include schema_version (supported: 1)"
        )
    sv = memory_filter["schema_version"]
    if sv not in SUPPORTED_SCHEMA_VERSIONS:
        raise InvalidGrantFilterError(
            f"memory_filter.schema_version {sv!r} is not supported; "
            f"supported versions: {sorted(SUPPORTED_SCHEMA_VERSIONS)}"
        )

    for key in memory_filter:
        if not isinstance(key, str):
            continue
        if key.casefold() in _REJECTED_FILTER_KEYS_FOLDED:
            raise InvalidGrantFilterError(
                f"memory_filter key {key!r} is not supported; "
                "rejected keys include: scope_types, semantic, preference, memory_ids"
            )

    if "max_items" in memory_filter:
        v = memory_filter["max_items"]
        if not isinstance(v, int) or isinstance(v, bool):
            raise InvalidGrantFilterError("memory_filter.max_items must be an integer")
        if not (MIN_MAX_ITEMS <= v <= MAX_MAX_ITEMS):
            raise InvalidGrantFilterError(
                f"memory_filter.max_items must be between {MIN_MAX_ITEMS} and {MAX_MAX_ITEMS}"
            )


# ---------------------------------------------------------------------------
# Event metadata_json validation
# ---------------------------------------------------------------------------

# Superset of SourcePointer UNSAFE_METADATA_KEYS; includes grant-specific additions.
UNSAFE_EVENT_METADATA_KEYS = frozenset({
    "content",
    "body",
    "raw_content",
    "payload",
    "summary",
    "copied_text",
    "source_snapshot",
    "memory_text",
    "artifact_payload",
    "generated_summary",
    "personal_memory_text",
})
_UNSAFE_EVENT_KEYS_FOLDED = frozenset(k.casefold() for k in UNSAFE_EVENT_METADATA_KEYS)

MAX_EVENT_METADATA_BYTES = 16_384
MAX_EVENT_METADATA_DEPTH = 8
MAX_EVENT_METADATA_TOTAL_ITEMS = 256
MAX_EVENT_METADATA_KEY_LENGTH = 128
MAX_EVENT_METADATA_STRING_LENGTH = 2_048


class InvalidGrantEventMetadataError(ValueError):
    """Raised when event metadata_json is unsafe, oversized, or too deeply nested."""


def _check_event_metadata_byte_size(metadata: dict) -> None:
    try:
        payload = json.dumps(metadata, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise InvalidGrantEventMetadataError(
            "metadata_json must be JSON-serializable"
        ) from exc
    size = len(payload.encode("utf-8"))
    if size > MAX_EVENT_METADATA_BYTES:
        raise InvalidGrantEventMetadataError(
            f"metadata_json exceeds {MAX_EVENT_METADATA_BYTES} bytes (got {size})"
        )


def _validate_event_metadata_node(node: object, *, path: str, depth: int, item_count: list[int]) -> None:
    if isinstance(node, (tuple, set)):
        raise InvalidGrantEventMetadataError(
            f"metadata_json must not contain {type(node).__name__} at {path!r}"
        )
    if isinstance(node, (bytes, bytearray)):
        raise InvalidGrantEventMetadataError(
            f"metadata_json must not contain bytes at {path!r}"
        )
    if depth > MAX_EVENT_METADATA_DEPTH:
        raise InvalidGrantEventMetadataError(
            f"metadata_json nesting exceeds max depth {MAX_EVENT_METADATA_DEPTH}"
        )
    if isinstance(node, Mapping):
        mapping = dict(node) if not isinstance(node, dict) else node
        for key, value in mapping.items():
            if not isinstance(key, str):
                raise InvalidGrantEventMetadataError(
                    f"metadata_json object keys must be strings at {path!r}"
                )
            if len(key) > MAX_EVENT_METADATA_KEY_LENGTH:
                raise InvalidGrantEventMetadataError(
                    f"metadata_json key exceeds {MAX_EVENT_METADATA_KEY_LENGTH} chars at {path!r}"
                )
            if key.casefold() in _UNSAFE_EVENT_KEYS_FOLDED:
                loc = f"{path}.{key}" if path else key
                raise InvalidGrantEventMetadataError(
                    f"metadata_json must not contain content keys at {loc!r}"
                )
            item_count[0] += 1
            if item_count[0] > MAX_EVENT_METADATA_TOTAL_ITEMS:
                raise InvalidGrantEventMetadataError(
                    f"metadata_json exceeds {MAX_EVENT_METADATA_TOTAL_ITEMS} total items"
                )
            child_path = f"{path}.{key}" if path else key
            _validate_event_metadata_node(value, path=child_path, depth=depth + 1, item_count=item_count)
    elif isinstance(node, Sequence) and not isinstance(node, (str, bytes, bytearray)):
        for index, item in enumerate(node):
            item_count[0] += 1
            if item_count[0] > MAX_EVENT_METADATA_TOTAL_ITEMS:
                raise InvalidGrantEventMetadataError(
                    f"metadata_json exceeds {MAX_EVENT_METADATA_TOTAL_ITEMS} total items"
                )
            _validate_event_metadata_node(item, path=f"{path}[{index}]", depth=depth + 1, item_count=item_count)
    elif node is None or isinstance(node, (bool, int, float)):
        return
    elif isinstance(node, str):
        if len(node) > MAX_EVENT_METADATA_STRING_LENGTH:
            raise InvalidGrantEventMetadataError(
                f"metadata_json string exceeds {MAX_EVENT_METADATA_STRING_LENGTH} chars at {path!r}"
            )
    else:
        raise InvalidGrantEventMetadataError(
            f"metadata_json contains unsupported type {type(node).__name__} at {path!r}"
        )


def validate_grant_event_metadata(metadata: dict | None) -> None:
    """Reject unsafe keys, content fields, oversized payloads, and excessive nesting."""
    if metadata is None:
        return
    if not isinstance(metadata, dict):
        raise InvalidGrantEventMetadataError(
            "metadata_json must be a JSON object at the top level"
        )
    if not metadata:
        return
    _validate_event_metadata_node(metadata, path="", depth=1, item_count=[0])
    _check_event_metadata_byte_size(metadata)
