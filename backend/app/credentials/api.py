from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional

from ..auth import get_identity
from ..config import settings
from .broker import CredentialBroker, CredentialProfile

router = APIRouter(prefix="/credentials/cli", tags=["cli-credentials"])

broker = CredentialBroker()


class CredentialProfileOut(BaseModel):
    id: str
    runtime: str
    name: str
    source_path: str
    target_path: str
    readonly: bool
    notes: str
    source_exists: bool


def _profile_out(p: CredentialProfile) -> CredentialProfileOut:
    from pathlib import Path
    return CredentialProfileOut(
        id=p.id,
        runtime=p.runtime,
        name=p.name,
        source_path=p.source_path,
        target_path=p.target_path,
        readonly=p.readonly,
        notes=p.notes,
        source_exists=Path(p.source_path).exists(),
    )


@router.get("/profiles", response_model=list[CredentialProfileOut])
def list_profiles(
    runtime: Optional[str] = Query(None),
    ids: tuple[str, str] = Depends(get_identity),
):
    """List configured CLI credential profiles. Reloads from disk on each request."""
    broker._reload()
    return [_profile_out(p) for p in broker.list_profiles(runtime=runtime)]


@router.get("/profiles/{profile_id:path}", response_model=CredentialProfileOut)
def get_profile(
    profile_id: str,
    ids: tuple[str, str] = Depends(get_identity),
):
    p = broker.get_profile(profile_id)
    if not p:
        raise HTTPException(status_code=404, detail=f"Profile '{profile_id}' not found")
    return _profile_out(p)


@router.post("/profiles/{profile_id:path}/detect", response_model=dict)
def detect_profile(
    profile_id: str,
    ids: tuple[str, str] = Depends(get_identity),
):
    """Return detection info for a profile (source_path exists + file count)."""
    broker._reload()
    p = broker.get_profile(profile_id)
    if not p:
        raise HTTPException(status_code=404, detail=f"Profile '{profile_id}' not found")
    src = Path(p.source_path)
    exists = src.exists()
    files = list(src.iterdir()) if exists else []
    return {
        "profile_id": profile_id,
        "source_path": p.source_path,
        "exists": exists,
        "non_empty": len(files) > 0,
        "file_count": len(files),
        "target_path": p.target_path,
        "readonly": p.readonly,
    }


# ── Login methods ─────────────────────────────────────────────────────────────

@router.get("/methods")
def list_methods(ids: tuple[str, str] = Depends(get_identity)):
    """Return the CLI login method for each supported runtime."""
    from .login import list_login_methods
    return list_login_methods()


# ── CLI login SSE stream ──────────────────────────────────────────────────────

@router.get("/login/stream")
async def login_stream(
    runtime: str = Query(..., description="Adapter runtime id, e.g. claude_code"),
    ids: tuple[str, str] = Depends(get_identity),
):
    """
    Stream the output of the CLI login command as Server-Sent Events.

    Each event is a JSON object:
      {"type": "output"|"error"|"warning"|"hint"|"synced"|"done", "text": "...", ...}

    The stream ends with a {"type": "done", "exit_code": N} event.
    On success (exit_code 0) the credentials are copied to the managed profile dir
    and a {"type": "synced", "profile_id": "..."} event is emitted first.
    """
    from .login import stream_cli_login
    profile_dir = Path(settings.cli_credentials_dir) / runtime / "default"

    async def generate():
        async for chunk in stream_cli_login(runtime, profile_dir):
            yield chunk
        broker._reload()   # invalidate profile cache after login

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Send input to active CLI login process ────────────────────────────────────

class LoginInputRequest(BaseModel):
    input: str


@router.post("/login/input")
async def login_input(
    runtime: str = Query(...),
    body: LoginInputRequest = ...,
    ids: tuple[str, str] = Depends(get_identity),
):
    """
    Write a line of text (e.g. an OAuth code) to an active PTY login session
    started by /login/stream. Returns 404 when no active login process exists
    for that runtime.
    """
    from .login import send_login_input
    delivered = await send_login_input(runtime, body.input)
    if not delivered:
        raise HTTPException(status_code=404, detail=f"No active login session for runtime '{runtime}'")
    return {"status": "sent"}


# ── Credential status summary ─────────────────────────────────────────────────

@router.get("/status")
def credential_status(ids: tuple[str, str] = Depends(get_identity)):
    """
    Return logged-in status for every supported runtime.
    Used by the Credentials panel in the frontend to show which CLIs have
    credentials stored in the managed profile dir.
    """
    from .login_adapters import RUNTIME_LOGIN_CONFIG
    broker._reload()
    result = []
    for runtime, cfg in RUNTIME_LOGIN_CONFIG.items():
        profile = broker.get_default_profile(runtime)
        src_exists = profile is not None and Path(profile.source_path).exists()
        file_count = len(list(Path(profile.source_path).iterdir())) if src_exists else 0
        result.append({
            "runtime": runtime,
            "label": cfg.get("label", runtime),
            "method": cfg["method"],
            "profile_id": profile.id if profile else None,
            "logged_in": src_exists and file_count > 0,
            "file_count": file_count,
        })
    return result
