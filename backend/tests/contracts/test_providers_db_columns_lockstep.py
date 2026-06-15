"""Schema-drift ratchet for the provider DB reader.

The TS control plane SELECTs exactly the columns listed in
`packages/protocol/src/providersDb.ts`. This test asserts that list matches
the `ModelProvider` ORM table, so adding, renaming, or dropping a column fails
tests on this side instead of breaking the TS reader at request time.
Python/alembic remains the exclusive schema owner.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.models import ModelProvider

_PROVIDERS_DB_TS = (
    Path(__file__).resolve().parents[3] / "packages" / "protocol" / "src" / "providersDb.ts"
)


def _parse_ts_const_string_array(source: str, const_name: str) -> list[str]:
    match = re.search(rf"{const_name}\s*=\s*\[(.*?)\]", source, re.DOTALL)
    assert match, (
        f"Could not find `{const_name} = [...]` in {_PROVIDERS_DB_TS}; "
        "if the file format changed, update this parser together with it."
    )
    return re.findall(r'"([A-Za-z0-9_]+)"', match.group(1))


def test_ts_read_allowlist_matches_model_provider_orm_columns():
    source = _PROVIDERS_DB_TS.read_text()

    table_match = re.search(r'MODEL_PROVIDERS_TABLE\s*=\s*"([A-Za-z0-9_]+)"', source)
    assert table_match, f"MODEL_PROVIDERS_TABLE not found in {_PROVIDERS_DB_TS}"
    assert table_match.group(1) == ModelProvider.__tablename__

    ts_columns = _parse_ts_const_string_array(source, "MODEL_PROVIDERS_READ_COLUMNS")
    orm_columns = {column.name for column in ModelProvider.__table__.columns}
    assert set(ts_columns) == orm_columns, (
        "TS provider read allowlist and ModelProvider ORM columns diverged; "
        "update packages/protocol/src/providersDb.ts and the TS reader together "
        f"(ts={sorted(set(ts_columns))}, orm={sorted(orm_columns)})"
    )
    assert len(ts_columns) == len(set(ts_columns)), "duplicate column in TS allowlist"
