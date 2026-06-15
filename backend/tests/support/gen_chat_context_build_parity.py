"""Generate the cross-language chat context build parity fixture.

Runs the real Python ``apply_context_budget`` (the cumulative budget/dedup loop
extracted from ``ChatContextBuilder.build``) over a representative matrix of
candidate lists + caps, and emits ``{input, expected}`` cases. The TS
``buildChatContext`` must produce identical selection + retrieval_trace over the
same input — that equivalence is the Stage 6 slice-4 flip gate.

Usage (from backend/):
    .venv/bin/python -m tests.support.gen_chat_context_build_parity \
        > ../control-plane/test/fixtures/chat_context_build_parity.json
"""

import json
import sys

sys.path.insert(0, ".")

from app.memory.chat_context import apply_context_budget  # noqa: E402
from app.schemas import ContextBundleItem  # noqa: E402

ITEM_FIELDS = [
    "item_type",
    "item_id",
    "title",
    "excerpt",
    "score",
    "reason",
    "token_count",
    "metadata",
]


def _item(**kw):
    """A candidate item dict with the wire defaults filled in."""
    base = {
        "item_type": kw["item_type"],
        "item_id": kw.get("item_id"),
        "title": kw.get("title"),
        "excerpt": kw.get("excerpt"),
        "score": kw.get("score"),
        "reason": kw.get("reason"),
        "token_count": kw.get("token_count", 0),
        "metadata": kw.get("metadata", {}),
    }
    return base


# Each case is a ChatContextCandidatesResult-shaped input.
cases = [
    # 1. Empty candidates → empty selection, not truncated.
    {
        "allowed_sources": [],
        "max_tokens": 4000,
        "max_items": 20,
        "context_policy_applied": True,
        "items": [],
    },
    # 2. A few items under both caps → all selected.
    {
        "allowed_sources": ["memory", "workspace"],
        "max_tokens": 4000,
        "max_items": 20,
        "context_policy_applied": True,
        "items": [
            _item(item_type="workspace", item_id="ws-1", title="WS", excerpt="desc", score=0.9, reason="current_workspace", token_count=5),
            _item(item_type="memory", item_id="m-1", title="Mem", excerpt="content", score=0.8, reason="approved_memory", token_count=7),
        ],
    },
    # 3. max_items cap reached → prefix selected, truncated.
    {
        "allowed_sources": ["memory"],
        "max_tokens": 100000,
        "max_items": 2,
        "context_policy_applied": True,
        "items": [
            _item(item_type="memory", item_id="m-1", token_count=1),
            _item(item_type="memory", item_id="m-2", token_count=1),
            _item(item_type="memory", item_id="m-3", token_count=1),
        ],
    },
    # 4. max_tokens cap reached → prefix selected, truncated.
    {
        "allowed_sources": ["source"],
        "max_tokens": 10,
        "max_items": 50,
        "context_policy_applied": False,
        "items": [
            _item(item_type="source", item_id="s-1", token_count=6, excerpt="aaa"),
            _item(item_type="source", item_id="s-2", token_count=6, excerpt="bbb"),
            _item(item_type="source", item_id="s-3", token_count=6, excerpt="ccc"),
        ],
    },
    # 5. Dedup by (item_type, item_id): the second duplicate is dropped.
    {
        "allowed_sources": ["memory", "knowledge_item"],
        "max_tokens": 4000,
        "max_items": 20,
        "context_policy_applied": True,
        "items": [
            _item(item_type="memory", item_id="dup", title="first", token_count=3),
            _item(item_type="memory", item_id="dup", title="second", token_count=3),
            _item(item_type="knowledge_item", item_id="dup", title="other-type", token_count=3),
        ],
    },
    # 6. Null item_id (manual_context) items are never deduped together.
    {
        "allowed_sources": ["manual_context"],
        "max_tokens": 4000,
        "max_items": 20,
        "context_policy_applied": True,
        "items": [
            _item(item_type="manual_context", item_id=None, title="a", excerpt="aa", score=1.0, reason="explicit_selection", token_count=2, metadata={"id": None}),
            _item(item_type="manual_context", item_id=None, title="b", excerpt="bb", score=1.0, reason="explicit_selection", token_count=2, metadata={"id": None}),
        ],
    },
    # 7. Mixed sources in priority order, token cap stops mid-stream.
    {
        "allowed_sources": ["activity_record", "knowledge_item", "memory", "project", "source", "workspace"],
        "max_tokens": 12,
        "max_items": 20,
        "context_policy_applied": True,
        "items": [
            _item(item_type="manual_context", item_id="mc-1", token_count=4, excerpt="x"),
            _item(item_type="workspace", item_id="ws-1", token_count=4, excerpt="y"),
            _item(item_type="project", item_id="pr-1", token_count=4, excerpt="z"),
            _item(item_type="memory", item_id="m-1", token_count=4, excerpt="w"),
        ],
    },
]


def _serialize_item(item: ContextBundleItem) -> dict:
    return {
        "item_type": item.item_type,
        "item_id": item.item_id,
        "title": item.title,
        "excerpt": item.excerpt,
        "score": item.score,
        "reason": item.reason,
        "token_count": item.token_count,
        "metadata": item.metadata or {},
    }


out = []
for case in cases:
    candidates = [ContextBundleItem(**raw) for raw in case["items"]]
    bundle = apply_context_budget(
        candidates,
        allowed_sources=case["allowed_sources"],
        max_tokens=case["max_tokens"],
        max_items=case["max_items"],
        context_policy_applied=case["context_policy_applied"],
    )
    expected = {
        "items": [_serialize_item(i) for i in bundle.items],
        "token_count": bundle.token_count,
        "truncated": bundle.truncated,
        "retrieval_trace": bundle.retrieval_trace,
    }
    out.append({"input": case, "expected": expected})

print(json.dumps(out, indent=2))
