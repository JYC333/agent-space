from __future__ import annotations
import urllib.parse

import httpx

from ..config import settings

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


def is_configured() -> bool:
    return bool(settings.google_client_id and settings.google_client_secret)


def build_auth_url(state: str) -> str:
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
    }
    return GOOGLE_AUTH_URL + "?" + urllib.parse.urlencode(params)


def exchange_code(code: str) -> dict:
    with httpx.Client(timeout=10) as client:
        resp = client.post(GOOGLE_TOKEN_URL, data={
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": settings.google_redirect_uri,
            "grant_type": "authorization_code",
        })
    resp.raise_for_status()
    return resp.json()


def get_userinfo(access_token: str) -> dict:
    with httpx.Client(timeout=10) as client:
        resp = client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
    resp.raise_for_status()
    return resp.json()
