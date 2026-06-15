"""HTTP contract: public CLI credential API wire shapes.

Pins the `/api/v1/credentials/cli/*` read responses to the shared TS contract
(packages/protocol/src/credentials.ts). CLI login state is the ADR 0010 second
credential channel: responses carry profile metadata and paths only — never the
login files' contents or any raw secret material. Adding or renaming a response
field must update both sides together.
"""

from __future__ import annotations

from app.credentials.api import broker


CLI_PROFILE_WIRE_CONTRACT: dict[str, tuple[type, ...]] = {
    "id": (str,),
    "runtime": (str,),
    "name": (str,),
    "source_path": (str,),
    "target_path": (str,),
    "readonly": (bool,),
    "notes": (str,),
    "source_exists": (bool,),
}

CLI_DETECT_WIRE_CONTRACT: dict[str, tuple[type, ...]] = {
    "profile_id": (str,),
    "source_path": (str,),
    "exists": (bool,),
    "non_empty": (bool,),
    "file_count": (int,),
    "target_path": (str,),
    "readonly": (bool,),
}

CLI_METHOD_WIRE_CONTRACT: dict[str, tuple[type, ...]] = {
    "runtime": (str,),
    "method": (str,),
    "label": (str,),
    "hint_cli": (str,),
    "supports_cli": (bool,),
}

CLI_STATUS_WIRE_CONTRACT: dict[str, tuple[type, ...]] = {
    "runtime": (str,),
    "label": (str,),
    "method": (str,),
    "profile_id": (str, type(None)),
    "logged_in": (bool,),
    "file_count": (int,),
}

_SECRET_MARKER = "cli-login-secret-material"


def _assert_wire_shape(data: dict, contract: dict[str, tuple[type, ...]]) -> None:
    assert set(data.keys()) == set(contract.keys())
    for field, allowed in contract.items():
        assert isinstance(data[field], allowed), f"{field}={data[field]!r}"
    forbidden = {"api_key", "secret_ref", "encrypted_key", "credential_secret_ref"}
    assert forbidden.isdisjoint(data.keys())


def _seed_profile(runtime: str = "claude_code", name: str = "default"):
    profile_dir = broker._creds_root / runtime / name
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / ".credentials.json").write_text(_SECRET_MARKER)
    broker._reload()
    return profile_dir


def test_cli_credential_read_responses_match_shared_wire_contract(
    api_client, db, cross_space_pair
):
    _seed_profile()
    a = cross_space_pair["space_a_id"]
    client = cross_space_pair["client_a"]
    params = {"space_id": a}
    db.commit()

    profiles = client.get("/api/v1/credentials/cli/profiles", params=params)
    assert profiles.status_code == 200
    listing = profiles.json()
    assert isinstance(listing, list) and listing
    for item in listing:
        _assert_wire_shape(item, CLI_PROFILE_WIRE_CONTRACT)
        assert _SECRET_MARKER not in str(item)
    seeded = next(p for p in listing if p["id"] == "claude_code/default")
    assert seeded["source_exists"] is True

    detail = client.get(
        "/api/v1/credentials/cli/profiles/claude_code/default", params=params
    )
    assert detail.status_code == 200
    _assert_wire_shape(detail.json(), CLI_PROFILE_WIRE_CONTRACT)

    detect = client.post(
        "/api/v1/credentials/cli/profiles/claude_code/default/detect", params=params
    )
    assert detect.status_code == 200
    detect_body = detect.json()
    _assert_wire_shape(detect_body, CLI_DETECT_WIRE_CONTRACT)
    assert detect_body["non_empty"] is True
    assert _SECRET_MARKER not in str(detect_body)


def test_cli_credential_methods_and_status_match_shared_wire_contract(
    api_client, db, cross_space_pair
):
    _seed_profile()
    a = cross_space_pair["space_a_id"]
    client = cross_space_pair["client_a"]
    params = {"space_id": a}
    db.commit()

    methods = client.get("/api/v1/credentials/cli/methods", params=params)
    assert methods.status_code == 200
    method_list = methods.json()
    assert isinstance(method_list, list) and method_list
    for item in method_list:
        _assert_wire_shape(item, CLI_METHOD_WIRE_CONTRACT)
        assert item["method"] == "cli"

    status = client.get("/api/v1/credentials/cli/status", params=params)
    assert status.status_code == 200
    status_list = status.json()
    assert isinstance(status_list, list) and status_list
    for item in status_list:
        _assert_wire_shape(item, CLI_STATUS_WIRE_CONTRACT)
        assert _SECRET_MARKER not in str(item)
    claude = next(s for s in status_list if s["runtime"] == "claude_code")
    assert claude["logged_in"] is True
