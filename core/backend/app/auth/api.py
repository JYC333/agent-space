from __future__ import annotations
import secrets
import urllib.parse

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from .api_key import ApiKeyService, get_identity
from .google import build_auth_url, exchange_code, get_userinfo, is_configured
from .service import UserService
from .session import (
    SESSION_COOKIE, OAUTH_STATE_COOKIE,
    UserSessionService, get_current_user,
)
from ..config import settings
from ..schemas import ApiKeyCreate, ApiKeyOut, ApiKeyCreatedOut

POST_LOGIN_NEXT_COOKIE = "post_login_next"


def _safe_next_url(raw: str) -> str:
    """Return `raw` only if it is a safe relative redirect target.

    Rejects absolute URLs and protocol-relative URLs (//...) to prevent
    open-redirect attacks. Only paths starting with a single '/' are allowed.
    """
    if not raw or not raw.startswith("/") or raw.startswith("//"):
        return ""
    return raw

router = APIRouter(prefix="/auth", tags=["auth"])
me_router = APIRouter(prefix="/me", tags=["me"])

# Expose both routers so the module registry can register both
extra_routers = [me_router]


# ── API Key routes (existing) ─────────────────────────────────────────────────

@router.post("/keys", response_model=ApiKeyCreatedOut, status_code=201)
def create_api_key(
    data: ApiKeyCreate,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    svc = ApiKeyService(db)
    key_record, raw_key = svc.create(
        space_id=space_id,
        owner_user_id=user_id,
        name=data.name,
        scope=data.scope,
        expires_at=data.expires_at,
    )
    return ApiKeyCreatedOut(
        id=key_record.id,
        space_id=key_record.space_id,
        owner_user_id=key_record.owner_user_id,
        name=key_record.name,
        scope=key_record.scope,
        status=key_record.status,
        last_used_at=key_record.last_used_at,
        expires_at=key_record.expires_at,
        created_at=key_record.created_at,
        raw_key=raw_key,
    )


@router.get("/keys", response_model=list[ApiKeyOut])
def list_api_keys(
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    return ApiKeyService(db).list(space_id=space_id, owner_user_id=user_id)


@router.delete("/keys/{key_id}", status_code=204)
def revoke_api_key(
    key_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    if not ApiKeyService(db).revoke(key_id, space_id):
        raise HTTPException(status_code=404, detail="API key not found")


# ── Google OAuth flow ─────────────────────────────────────────────────────────

@router.get("/google")
def google_login(next_url: str = Query(default="", alias="next")):
    if not is_configured():
        raise HTTPException(status_code=501, detail="Google OAuth not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.")
    state = secrets.token_hex(16)
    url = build_auth_url(state)
    response = RedirectResponse(url=url)
    response.set_cookie(
        key=OAUTH_STATE_COOKIE,
        value=state,
        max_age=300,
        httponly=True,
        samesite="lax",
        secure=not settings.debug,
    )
    safe = _safe_next_url(next_url)
    if safe:
        response.set_cookie(
            key=POST_LOGIN_NEXT_COOKIE,
            value=safe,
            max_age=300,
            httponly=True,
            samesite="lax",
            secure=not settings.debug,
            path="/",
        )
    return response


def _login_error(reason: str, clear_state: bool = False) -> RedirectResponse:
    """Redirect to the login page with a safe, URL-encoded error code."""
    url = f"{settings.frontend_url}/login?error={urllib.parse.quote(reason, safe='')}"
    resp = RedirectResponse(url=url)
    if clear_state:
        resp.delete_cookie(key=OAUTH_STATE_COOKIE, path="/")
    return resp


@router.get("/google/callback")
def google_callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
    db: Session = Depends(get_db),
):
    if error:
        return _login_error("provider_error", clear_state=True)

    expected_state = request.cookies.get(OAUTH_STATE_COOKIE)
    # Constant-time comparison to avoid timing oracle on the CSRF state
    if not expected_state or not secrets.compare_digest(expected_state, state):
        return _login_error("csrf", clear_state=True)

    try:
        tokens = exchange_code(code)
        userinfo = get_userinfo(tokens["access_token"])
    except Exception:
        return _login_error("google_failed", clear_state=True)

    google_sub = userinfo.get("sub")
    email = userinfo.get("email", "")
    display_name = userinfo.get("name") or email.split("@")[0]
    avatar_url = userinfo.get("picture")

    if not google_sub or not email:
        return _login_error("incomplete_profile", clear_state=True)

    if not userinfo.get("email_verified"):
        return _login_error("email_not_verified", clear_state=True)

    user = UserService(db).find_or_create_from_google(google_sub, email, display_name, avatar_url)
    _, raw_token = UserSessionService(db).create(user.id)

    pending_next = request.cookies.get(POST_LOGIN_NEXT_COOKIE, "")
    safe_next = _safe_next_url(pending_next)
    redirect_to = f"{settings.frontend_url}{safe_next}" if safe_next else settings.frontend_url

    response = RedirectResponse(url=redirect_to)
    response.set_cookie(
        key=SESSION_COOKIE,
        value=raw_token,
        max_age=settings.session_expire_days * 86400,
        httponly=True,
        samesite="lax",
        secure=not settings.debug,
        path="/",
    )
    response.delete_cookie(key=OAUTH_STATE_COOKIE)
    response.delete_cookie(key=POST_LOGIN_NEXT_COOKIE, path="/")
    return response


@router.post("/logout", status_code=204)
def logout(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        UserSessionService(db).delete(token)
    response = Response(status_code=204)
    response.delete_cookie(
        key=SESSION_COOKIE,
        path="/",
        httponly=True,
        samesite="lax",
        secure=not settings.debug,
    )
    return response


# ── /me routes ────────────────────────────────────────────────────────────────

@me_router.get("")
def get_me(user: User = Depends(get_current_user)):
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "avatar_url": user.avatar_url,
        "default_space_id": user.default_space_id,
        "created_at": user.created_at.isoformat(),
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
    }


@me_router.get("/spaces")
def get_my_spaces(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return UserService(db).get_user_spaces(user.id)
