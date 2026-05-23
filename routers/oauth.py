"""
OAuth 2.0 login for Google, Microsoft, and GitHub.

Two Google flows are supported:
  Redirect flow (GET /api/auth/google):
    Requires GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET.
    Classic server-side Authorization Code exchange.

  GIS token flow (POST /api/auth/google/token):
    Requires GOOGLE_CLIENT_ID only (no client secret).
    Frontend obtains an id_token via Google Identity Services, POSTs it here,
    and receives a Nexus JWT directly.
"""
import logging
import secrets
import time
import re
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from jwt import PyJWKClient
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.db import get_db
from database.models import User
from lib.auth import create_access_token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["oauth"])

# ── In-memory state store (single-instance; fine for Render free tier) ────────

_state_store: dict[str, float] = {}


def _gen_state() -> str:
    state = secrets.token_hex(20)
    _state_store[state] = time.time() + 300  # 5-min TTL
    # Prune expired entries
    now = time.time()
    expired = [k for k, v in _state_store.items() if v < now]
    for k in expired:
        _state_store.pop(k, None)
    return state


def _verify_state(state: str) -> bool:
    exp = _state_store.pop(state, None)
    return exp is not None and time.time() < exp


# ── Username generation ───────────────────────────────────────────────────────

async def _unique_username(base: str, db: AsyncSession) -> str:
    slug = re.sub(r"[^a-z0-9_-]", "", base.lower())[:20] or "user"
    candidate = slug
    for i in range(1, 100):
        result = await db.execute(select(User).where(User.username == candidate))
        if not result.scalar_one_or_none():
            return candidate
        candidate = f"{slug}{i}"
    return f"{slug}_{secrets.token_hex(4)}"


# ── Find or create user from OAuth ───────────────────────────────────────────

async def _find_or_create(
    provider: str,
    provider_id: str,
    email: str,
    display_name: str,
    db: AsyncSession,
) -> User:
    # 1. Find by (provider, provider_id)
    result = await db.execute(
        select(User).where(User.oauth_provider == provider, User.oauth_id == provider_id)
    )
    user = result.scalar_one_or_none()
    if user:
        return user

    # 2. Find by email — link OAuth to existing account (safe: same address)
    if email:
        result = await db.execute(select(User).where(User.email == email.lower()))
        user = result.scalar_one_or_none()
        if user:
            user.oauth_provider = provider
            user.oauth_id = provider_id
            await db.flush()
            logger.info(f"Linked {provider} OAuth to existing account: {email}")
            return user

    # 3. Create new user
    username = await _unique_username(
        email.split("@")[0] if email else display_name, db
    )
    user = User(
        display_name    = display_name or "User",
        username        = username,
        email           = email.lower() if email else f"{provider}_{provider_id}@oauth.nexus",
        hashed_password = "",   # OAuth users cannot log in with a password
        oauth_provider  = provider,
        oauth_id        = provider_id,
    )
    db.add(user)
    await db.flush()
    logger.info(f"Created new user via {provider} OAuth: {user.email}")
    return user


def _frontend_redirect(token: str) -> RedirectResponse:
    url = f"{settings.frontend_url}/auth/callback?token={token}"
    return RedirectResponse(url, status_code=302)


def _frontend_error(msg: str) -> RedirectResponse:
    url = f"{settings.frontend_url}/login?error={msg}"
    return RedirectResponse(url, status_code=302)


# ── Google ────────────────────────────────────────────────────────────────────

GOOGLE_AUTH_URL  = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_INFO_URL  = "https://www.googleapis.com/oauth2/v2/userinfo"


@router.get("/google")
async def google_login():
    if not settings.google_client_id:
        return _frontend_error("Google+OAuth+not+configured")
    state = _gen_state()
    params = {
        "client_id":     settings.google_client_id,
        "redirect_uri":  f"{settings.backend_url}/api/auth/google/callback",
        "response_type": "code",
        "scope":         "openid email profile",
        "state":         state,
        "access_type":   "online",
    }
    return RedirectResponse(f"{GOOGLE_AUTH_URL}?{urlencode(params)}", status_code=302)


@router.get("/google/callback")
async def google_callback(
    code:  str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: AsyncSession  = Depends(get_db),
):
    if error or not code or not state or not _verify_state(state):
        return _frontend_error("Google+login+failed")

    async with httpx.AsyncClient() as client:
        token_res = await client.post(GOOGLE_TOKEN_URL, data={
            "code":          code,
            "client_id":     settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri":  f"{settings.backend_url}/api/auth/google/callback",
            "grant_type":    "authorization_code",
        })
        if not token_res.is_success:
            logger.warning(f"Google token exchange failed: {token_res.text}")
            return _frontend_error("Google+token+exchange+failed")

        access_token = token_res.json().get("access_token")
        info_res = await client.get(GOOGLE_INFO_URL, headers={"Authorization": f"Bearer {access_token}"})
        if not info_res.is_success:
            return _frontend_error("Google+userinfo+failed")

    info   = info_res.json()
    email  = info.get("email", "")
    name   = info.get("name") or info.get("given_name") or email.split("@")[0]
    gid    = info.get("id", "")

    user  = await _find_or_create("google", gid, email, name, db)
    token = create_access_token(user)
    return _frontend_redirect(token)


# ── Google Identity Services (GIS) token flow — no client secret required ─────
#
# The frontend uses Google's "Sign In With Google" button (GIS library).
# After user consent GIS returns a signed id_token (called `credential`).
# POST that credential here; the backend verifies it against Google's public
# JWKS — GOOGLE_CLIENT_SECRET is NOT needed for this path.

_GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
_google_jwks = PyJWKClient(_GOOGLE_JWKS_URL, lifespan=3600)


class _GoogleCredentialBody(BaseModel):
    credential: str


@router.post("/google/token")
async def google_gis_token(
    body: _GoogleCredentialBody,
    db: AsyncSession = Depends(get_db),
):
    if not settings.google_client_id:
        raise HTTPException(status_code=503, detail="Google OAuth not configured")
    try:
        signing_key = _google_jwks.get_signing_key_from_jwt(body.credential)
        payload = jwt.decode(
            body.credential,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.google_client_id,
            issuer=["accounts.google.com", "https://accounts.google.com"],
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Google credential expired")
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid Google credential: {exc}")

    email = payload.get("email", "")
    name  = payload.get("name") or payload.get("given_name") or email.split("@")[0]
    gid   = payload.get("sub", "")

    user  = await _find_or_create("google", gid, email, name, db)
    token = create_access_token(user)
    return {"token": token}


# ── Microsoft ─────────────────────────────────────────────────────────────────

MS_AUTH_URL  = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
MS_TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
MS_INFO_URL  = "https://graph.microsoft.com/v1.0/me"


@router.get("/microsoft")
async def microsoft_login():
    if not settings.microsoft_client_id:
        return _frontend_error("Microsoft+OAuth+not+configured")
    state = _gen_state()
    params = {
        "client_id":     settings.microsoft_client_id,
        "redirect_uri":  f"{settings.backend_url}/api/auth/microsoft/callback",
        "response_type": "code",
        "scope":         "openid email profile User.Read",
        "state":         state,
        "response_mode": "query",
    }
    return RedirectResponse(f"{MS_AUTH_URL}?{urlencode(params)}", status_code=302)


@router.get("/microsoft/callback")
async def microsoft_callback(
    code:  str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: AsyncSession  = Depends(get_db),
):
    if error or not code or not state or not _verify_state(state):
        return _frontend_error("Microsoft+login+failed")

    async with httpx.AsyncClient() as client:
        token_res = await client.post(MS_TOKEN_URL, data={
            "code":          code,
            "client_id":     settings.microsoft_client_id,
            "client_secret": settings.microsoft_client_secret,
            "redirect_uri":  f"{settings.backend_url}/api/auth/microsoft/callback",
            "grant_type":    "authorization_code",
            "scope":         "openid email profile User.Read",
        })
        if not token_res.is_success:
            logger.warning(f"Microsoft token exchange failed: {token_res.text}")
            return _frontend_error("Microsoft+token+exchange+failed")

        access_token = token_res.json().get("access_token")
        info_res = await client.get(MS_INFO_URL, headers={"Authorization": f"Bearer {access_token}"})
        if not info_res.is_success:
            return _frontend_error("Microsoft+userinfo+failed")

    info  = info_res.json()
    email = info.get("mail") or info.get("userPrincipalName") or ""
    name  = info.get("displayName") or email.split("@")[0] or "User"
    mid   = info.get("id", "")

    user  = await _find_or_create("microsoft", mid, email, name, db)
    token = create_access_token(user)
    return _frontend_redirect(token)


# ── GitHub ────────────────────────────────────────────────────────────────────

GH_AUTH_URL  = "https://github.com/login/oauth/authorize"
GH_TOKEN_URL = "https://github.com/login/oauth/access_token"
GH_INFO_URL  = "https://api.github.com/user"
GH_EMAIL_URL = "https://api.github.com/user/emails"


@router.get("/github")
async def github_login():
    if not settings.github_client_id:
        return _frontend_error("GitHub+OAuth+not+configured")
    state = _gen_state()
    params = {
        "client_id":    settings.github_client_id,
        "redirect_uri": f"{settings.backend_url}/api/auth/github/callback",
        "scope":        "read:user user:email",
        "state":        state,
    }
    return RedirectResponse(f"{GH_AUTH_URL}?{urlencode(params)}", status_code=302)


@router.get("/github/callback")
async def github_callback(
    code:  str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: AsyncSession  = Depends(get_db),
):
    if error or not code or not state or not _verify_state(state):
        return _frontend_error("GitHub+login+failed")

    async with httpx.AsyncClient() as client:
        token_res = await client.post(GH_TOKEN_URL,
            data={
                "code":          code,
                "client_id":     settings.github_client_id,
                "client_secret": settings.github_client_secret,
                "redirect_uri":  f"{settings.backend_url}/api/auth/github/callback",
            },
            headers={"Accept": "application/json"},
        )
        if not token_res.is_success:
            return _frontend_error("GitHub+token+exchange+failed")

        access_token = token_res.json().get("access_token")
        headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}

        info_res  = await client.get(GH_INFO_URL,  headers=headers)
        email_res = await client.get(GH_EMAIL_URL, headers=headers)

    if not info_res.is_success:
        return _frontend_error("GitHub+userinfo+failed")

    info  = info_res.json()
    name  = info.get("name") or info.get("login") or "User"
    ghid  = str(info.get("id", ""))

    # GitHub may not expose email in /user — fall back to /user/emails
    email = info.get("email") or ""
    if not email and email_res.is_success:
        emails = email_res.json()
        primary = next((e for e in emails if e.get("primary") and e.get("verified")), None)
        if primary:
            email = primary.get("email", "")

    user  = await _find_or_create("github", ghid, email, name, db)
    token = create_access_token(user)
    return _frontend_redirect(token)
