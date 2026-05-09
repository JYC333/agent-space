from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..auth import get_identity
from ..schemas import CLIAdapterConfigCreate, CLIAdapterConfigUpdate, CLIAdapterConfigOut, CLIStatusOut
from .service import CLIAdapterService, read_claude_stats, read_quota_cache, refresh_quota_cache

router = APIRouter(prefix="/cli-adapters", tags=["cli-adapters"])


# ---------------------------------------------------------------------------
# Built-in adapter catalog
# ---------------------------------------------------------------------------

@router.get("/catalog", response_model=list[dict])
def list_builtin_adapters(db: Session = Depends(get_db)):
    """List all known built-in CLI adapter types."""
    return CLIAdapterService(db).list_builtin_adapters()


@router.get("/detect", response_model=list[CLIStatusOut])
def detect_all_adapters(db: Session = Depends(get_db)):
    """Probe all built-in CLI adapters and return their detection status."""
    return CLIAdapterService(db).detect_all()


@router.get("/detect/{adapter_id}", response_model=CLIStatusOut)
def detect_adapter(adapter_id: str, db: Session = Depends(get_db)):
    """Probe a single CLI adapter by adapter_id."""
    return CLIAdapterService(db).detect_one(adapter_id)


# ---------------------------------------------------------------------------
# Claude Code usage stats (reads ~/.claude/stats-cache.json)
# ---------------------------------------------------------------------------

@router.get("/usage/claude")
def get_claude_usage(_ids: tuple[str, str] = Depends(get_identity)):
    """Return Claude Code activity stats + cached quota (from stats-cache.json + quota-cache.json)."""
    return read_claude_stats()


@router.post("/usage/claude/quota/refresh")
async def refresh_claude_quota(_ids: tuple[str, str] = Depends(get_identity)):
    """Fetch live subscription quota via PTY, persist the result, and return it."""
    import asyncio
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, refresh_quota_cache)
    return result


# ---------------------------------------------------------------------------
# Per-space config CRUD
# ---------------------------------------------------------------------------

@router.get("", response_model=list[CLIAdapterConfigOut])
def list_configs(
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    return CLIAdapterService(db).list(space_id)


@router.post("", response_model=CLIAdapterConfigOut, status_code=201)
def create_config(
    data: CLIAdapterConfigCreate,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    return CLIAdapterService(db).create(data, space_id)


@router.get("/{config_id}", response_model=CLIAdapterConfigOut)
def get_config(
    config_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    config = CLIAdapterService(db).get(config_id, space_id)
    if not config:
        raise HTTPException(status_code=404, detail="CLI adapter config not found")
    return config


@router.patch("/{config_id}", response_model=CLIAdapterConfigOut)
def update_config(
    config_id: str,
    data: CLIAdapterConfigUpdate,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    config = CLIAdapterService(db).update(config_id, space_id, data)
    if not config:
        raise HTTPException(status_code=404, detail="CLI adapter config not found")
    return config


@router.delete("/{config_id}", status_code=204)
def delete_config(
    config_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    if not CLIAdapterService(db).delete(config_id, space_id):
        raise HTTPException(status_code=404, detail="CLI adapter config not found")


@router.get("/{config_id}/detect", response_model=CLIStatusOut)
def detect_config(
    config_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Run detection for the adapter_id of a saved config."""
    space_id, _ = ids
    config = CLIAdapterService(db).get(config_id, space_id)
    if not config:
        raise HTTPException(status_code=404, detail="CLI adapter config not found")
    return CLIAdapterService(db).detect_one(config.adapter_id)
