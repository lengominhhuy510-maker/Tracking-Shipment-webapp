"""QA-14 — OAuth callback/state/token/cookie with a MOCKED provider (REPORT-ONLY).

Source of truth: Spec §3.8, IC§3.2 (`/auth/*` at root, callback 302 → `/`),
IC§10 (JWT HS256 claims sub/role/iat/exp; cookie `session_token`, HttpOnly,
SameSite=Lax, Path=/, Max-Age=259200; `get_current_user` → 401 UNAUTHENTICATED
JSON, no redirect).

These tests NEVER call Google/Microsoft. The OAuth provider is mocked at the
token-exchange boundary (`oauth.create_client(...).authorize_access_token`), or
the REAL Authlib client is exercised with an empty handshake session to prove
state/CSRF rejection. This file is READ-ONLY over app code — it asserts the
CONTRACT; where the app diverges the test fails and QA-14.md classifies the red.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from jose import jwt as jose_jwt
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.auth.routes as auth_routes
from app.api.deps import get_session
from app.auth.routes import COOKIE_NAME
from app.config import settings
from app.db.base import Base
from app.db.models import User
from app.main import app

TEST_SECRET = "qa14-test-secret-for-jwt"
ALGO = "HS256"


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch):
    """Pin the signing secret so we can independently forge/verify JWTs."""
    monkeypatch.setattr(settings, "SESSION_JWT_SECRET", TEST_SECRET)


@pytest.fixture
async def db():
    """Fresh in-memory SQLite with the full schema (users table included)."""
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
async def client(db):
    """ASGI client with get_session bound to the in-memory DB.

    NOTE: get_current_user is deliberately NOT overridden here — QA-14 must
    exercise the REAL auth guard (unlike the legacy `auth_override` fixture).
    """

    async def override_session():
        async with db() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


def _mock_provider(monkeypatch, userinfo: dict):
    """Replace oauth.create_client so authorize_access_token returns `userinfo`.

    This bypasses Authlib entirely (no network, no real state check) so the
    happy-path token→user→cookie logic can be exercised in isolation.
    """
    fake_client = MagicMock()
    fake_client.authorize_access_token = AsyncMock(return_value={"userinfo": userinfo})
    monkeypatch.setattr(auth_routes.oauth, "create_client", lambda provider: fake_client)
    return fake_client


def _session_cookie_header(response) -> str | None:
    """Return the raw Set-Cookie header for `session_token`, or None."""
    for raw in response.headers.get_list("set-cookie"):
        if raw.startswith(f"{COOKIE_NAME}="):
            return raw
    return None


def _cookie_attrs(raw: str) -> dict[str, str]:
    """Parse a Set-Cookie line into a lower-cased attribute map."""
    attrs: dict[str, str] = {}
    parts = [p.strip() for p in raw.split(";")]
    # first part is name=value (the JWT)
    name, _, value = parts[0].partition("=")
    attrs["__name__"] = name
    attrs["__value__"] = value
    for p in parts[1:]:
        k, _, v = p.partition("=")
        attrs[k.strip().lower()] = v.strip()
    return attrs


async def _user_count(db) -> int:
    async with db() as s:
        return (await s.execute(select(func.count()).select_from(User))).scalar_one()


# --------------------------------------------------------------------------- #
# 1. State / CSRF — callback missing/wrong state must NOT mint a session/user
# --------------------------------------------------------------------------- #
async def test_callback_forged_state_creates_no_session_no_user(client, db):
    """SECURITY INVARIANT: forged state → no session_token cookie, no user row.

    Uses the REAL Authlib client with an empty handshake session, so Authlib's
    own MismatchingState guard fires. We assert only the security property here
    (no cookie / no user); the rejection *shape* is asserted separately below.
    """
    r = await client.get(
        "/auth/callback/google?code=abc&state=forged", follow_redirects=False
    )
    # No session established:
    assert _session_cookie_header(r) is None
    assert r.headers.get("location") in (None, "")  # not redirected to a logged-in target
    # No user upserted:
    assert await _user_count(db) == 0


async def test_callback_missing_state_creates_no_session_no_user(client, db):
    """SECURITY INVARIANT: state param absent entirely → no cookie, no user."""
    r = await client.get("/auth/callback/google?code=abc", follow_redirects=False)
    assert _session_cookie_header(r) is None
    assert await _user_count(db) == 0


async def test_callback_bad_state_rejects_cleanly_not_500(client):
    """CONTRACT: a bad/forged state should be rejected with a clean 4xx (IC§3.1
    envelope / IC§10 UNAUTHENTICATED), NOT an unhandled 500.

    The security invariant above already holds; this asserts the *shape* of the
    rejection. Expected to FAIL while the app lets MismatchingStateError bubble
    to a 500 (classified in QA-14.md).
    """
    r = await client.get(
        "/auth/callback/google?code=abc&state=forged", follow_redirects=False
    )
    assert r.status_code != 500, (
        "callback with bad state returned 500 (unhandled MismatchingStateError); "
        "expected a clean 4xx per IC§3.1/IC§10"
    )
    assert 400 <= r.status_code < 500


# --------------------------------------------------------------------------- #
# 2. Token → user (mock provider): upsert + cookie flags + JWT claims
# --------------------------------------------------------------------------- #
async def test_valid_token_creates_user_and_sets_cookie(client, db, monkeypatch):
    _mock_provider(
        monkeypatch,
        {"sub": "G-1001", "email": "alice@example.com", "name": "Alice"},
    )
    r = await client.get(
        "/auth/callback/google?code=code&state=state", follow_redirects=False
    )
    # Redirect shape (item 4):
    assert r.status_code == 302
    assert r.headers.get("location") == "/"

    # A user was created and matched on (provider, provider_sub):
    async with db() as s:
        user = (
            await s.execute(
                select(User).where(
                    User.provider == "google", User.provider_sub == "G-1001"
                )
            )
        ).scalar_one()
    assert user.email == "alice@example.com"
    assert user.name == "Alice"
    assert user.role == "user"

    # Cookie present with the correct name:
    raw = _session_cookie_header(r)
    assert raw is not None, "no session_token Set-Cookie on successful callback"


async def test_cookie_attributes_match_ic10(client, db, monkeypatch):
    """IC§10: name=session_token, HttpOnly, SameSite=Lax, Path=/, Max-Age=259200."""
    _mock_provider(monkeypatch, {"sub": "G-2002", "email": "bob@example.com"})
    r = await client.get(
        "/auth/callback/google?code=c&state=s", follow_redirects=False
    )
    raw = _session_cookie_header(r)
    assert raw is not None
    attrs = _cookie_attrs(raw)

    assert attrs["__name__"] == "session_token"
    assert "httponly" in attrs
    assert attrs.get("samesite", "").lower() == "lax"
    assert attrs.get("path") == "/"
    expected_max_age = str(settings.SESSION_JWT_EXPIRE_HOURS * 3600)
    assert attrs.get("max-age") == expected_max_age
    # IC§10 states Max-Age=259200 (=72h) as the canonical value:
    assert attrs.get("max-age") == "259200"


async def test_jwt_claims_shape_and_exp(client, db, monkeypatch):
    """IC§10: JWT HS256 with exactly {sub, role, iat, exp}; exp = iat + EXPIRE*3600."""
    _mock_provider(monkeypatch, {"sub": "G-3003", "email": "carol@example.com"})
    r = await client.get(
        "/auth/callback/google?code=c&state=s", follow_redirects=False
    )
    raw = _session_cookie_header(r)
    token = _cookie_attrs(raw)["__value__"]

    # Verify algorithm HS256 via header, and signature via the pinned secret:
    header = jose_jwt.get_unverified_header(token)
    assert header["alg"] == ALGO

    claims = jose_jwt.decode(token, TEST_SECRET, algorithms=[ALGO])
    assert set(claims.keys()) == {"sub", "role", "iat", "exp"}
    assert claims["role"] == "user"
    assert isinstance(claims["iat"], int)
    assert isinstance(claims["exp"], int)
    assert claims["exp"] == claims["iat"] + settings.SESSION_JWT_EXPIRE_HOURS * 3600

    # sub must be the user's DB id (string):
    async with db() as s:
        user = (
            await s.execute(select(User).where(User.provider_sub == "G-3003"))
        ).scalar_one()
    assert claims["sub"] == str(user.id)


async def test_repeat_callback_upserts_no_duplicate_user(client, db, monkeypatch):
    """Same (provider, provider_sub) twice → single user row; profile fields updated."""
    _mock_provider(
        monkeypatch, {"sub": "G-4004", "email": "dora@old.com", "name": "Dora Old"}
    )
    r1 = await client.get(
        "/auth/callback/google?code=c&state=s", follow_redirects=False
    )
    token1 = _cookie_attrs(_session_cookie_header(r1))["__value__"]
    id1 = jose_jwt.decode(token1, TEST_SECRET, algorithms=[ALGO])["sub"]

    # Second login, same sub, changed email/name:
    _mock_provider(
        monkeypatch, {"sub": "G-4004", "email": "dora@new.com", "name": "Dora New"}
    )
    r2 = await client.get(
        "/auth/callback/google?code=c2&state=s2", follow_redirects=False
    )
    token2 = _cookie_attrs(_session_cookie_header(r2))["__value__"]
    id2 = jose_jwt.decode(token2, TEST_SECRET, algorithms=[ALGO])["sub"]

    assert id1 == id2, "upsert produced a different user id (duplicate?)"
    assert await _user_count(db) == 1

    async with db() as s:
        user = (
            await s.execute(select(User).where(User.provider_sub == "G-4004"))
        ).scalar_one()
    assert user.email == "dora@new.com"
    assert user.name == "Dora New"


async def test_callback_without_sub_rejected_401(client, db, monkeypatch):
    """Missing id_token `sub` → 401 UNAUTHENTICATED, no user, no cookie."""
    _mock_provider(monkeypatch, {"email": "nosub@example.com"})  # no 'sub'
    r = await client.get(
        "/auth/callback/google?code=c&state=s", follow_redirects=False
    )
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "UNAUTHENTICATED"
    assert _session_cookie_header(r) is None
    assert await _user_count(db) == 0


async def test_unknown_provider_404(client):
    """Unknown provider → 404 UNKNOWN_PROVIDER (root /auth/* still guarded)."""
    r = await client.get(
        "/auth/callback/facebook?code=c&state=s", follow_redirects=False
    )
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "UNKNOWN_PROVIDER"


# --------------------------------------------------------------------------- #
# 3. Real guard still bites — cookie handling on protected /api/v1/* routes
# --------------------------------------------------------------------------- #
async def test_no_cookie_api_returns_401_json_not_redirect(client):
    """IC§10: no cookie → protected route → 401 UNAUTHENTICATED JSON, no redirect.

    Confirms the legacy suites' `auth_override` fixture does NOT mask the real
    guard here (this file never installs that override).
    """
    r = await client.get("/api/v1/shipments/", follow_redirects=False)
    assert r.status_code == 401
    assert r.headers.get("location") is None
    assert r.json() == {
        "detail": {"code": "UNAUTHENTICATED", "message": "Yêu cầu đăng nhập"}
    }


async def test_expired_jwt_returns_401_not_500(client):
    """Expired session JWT → 401, never a crash/500."""
    now = datetime.now(timezone.utc)
    token = jose_jwt.encode(
        {
            "sub": "1",
            "role": "user",
            "iat": int((now - timedelta(hours=100)).timestamp()),
            "exp": int((now - timedelta(hours=1)).timestamp()),
        },
        TEST_SECRET,
        algorithm=ALGO,
    )
    r = await client.get(
        "/api/v1/shipments/", cookies={COOKIE_NAME: token}, follow_redirects=False
    )
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "UNAUTHENTICATED"


async def test_wrong_signature_jwt_returns_401_not_500(client):
    """JWT signed with a different secret → 401, no crash."""
    now = datetime.now(timezone.utc)
    token = jose_jwt.encode(
        {
            "sub": "1",
            "role": "user",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=1)).timestamp()),
        },
        "a-totally-different-secret",
        algorithm=ALGO,
    )
    r = await client.get(
        "/api/v1/shipments/", cookies={COOKIE_NAME: token}, follow_redirects=False
    )
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "UNAUTHENTICATED"


async def test_garbage_cookie_returns_401_not_500(client):
    """Non-JWT cookie value → 401, no crash."""
    r = await client.get(
        "/api/v1/shipments/", cookies={COOKIE_NAME: "not.a.jwt"}, follow_redirects=False
    )
    assert r.status_code == 401


async def test_valid_jwt_unknown_user_returns_401(client):
    """Well-signed JWT whose sub has no row → 401 (no user leak / no 500)."""
    now = datetime.now(timezone.utc)
    token = jose_jwt.encode(
        {
            "sub": "999999",
            "role": "user",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=1)).timestamp()),
        },
        TEST_SECRET,
        algorithm=ALGO,
    )
    r = await client.get(
        "/api/v1/shipments/", cookies={COOKIE_NAME: token}, follow_redirects=False
    )
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "UNAUTHENTICATED"


# --------------------------------------------------------------------------- #
# 4. Callback redirect target is the public SPA shell "/" (IC§10 / §3.8(B))
# --------------------------------------------------------------------------- #
async def test_callback_redirects_to_root_not_protected_route(client, monkeypatch):
    _mock_provider(monkeypatch, {"sub": "G-5005", "email": "eve@example.com"})
    r = await client.get(
        "/auth/callback/google?code=c&state=s", follow_redirects=False
    )
    assert r.status_code == 302
    loc = r.headers.get("location")
    assert loc == "/"
    assert not loc.startswith("/api/")  # not a protected route


# --------------------------------------------------------------------------- #
# 5. Logout + /auth/me contract (IC§3.2)
# --------------------------------------------------------------------------- #
async def test_post_logout_204_clears_cookie(client):
    """IC§3.2: POST /auth/logout → 204 + Set-Cookie Max-Age=0.

    Expected to FAIL: app registers logout as GET → 200 (no POST route → 405),
    classified in QA-14.md.
    """
    r = await client.post("/auth/logout")
    assert r.status_code == 204, (
        f"POST /auth/logout returned {r.status_code}; IC§3.2 requires 204"
    )
    raw = _session_cookie_header(r)
    assert raw is not None
    assert _cookie_attrs(raw).get("max-age") == "0"


async def test_logout_clears_cookie_via_actual_route(client):
    """Behavioral probe of the AS-BUILT logout (GET) — documents cookie clearing.

    IC§3.2 expects POST→204; the app exposes GET→200 that deletes the cookie
    with Max-Age=0. This asserts the clearing works on whatever verb the app
    actually serves, to characterise the drift without asserting the wrong verb.
    """
    r = await client.get("/auth/logout", follow_redirects=False)
    # Characterise as-built status (200) and confirm the cookie is cleared:
    assert r.status_code in (200, 204)
    raw = _session_cookie_header(r)
    assert raw is not None, "logout did not emit a session_token Set-Cookie"
    assert _cookie_attrs(raw).get("max-age") == "0"


async def test_get_me_without_login_401(client):
    """IC§3.2: GET /auth/me unauthenticated → 401 UNAUTHENTICATED JSON."""
    r = await client.get("/auth/me", follow_redirects=False)
    assert r.status_code == 401
    assert r.headers.get("location") is None
    assert r.json()["detail"]["code"] == "UNAUTHENTICATED"


async def test_get_me_after_login_returns_profile(client, db, monkeypatch):
    """End-to-end (mock provider): login sets cookie, /auth/me echoes the profile."""
    _mock_provider(
        monkeypatch, {"sub": "G-6006", "email": "frank@example.com", "name": "Frank"}
    )
    r = await client.get(
        "/auth/callback/google?code=c&state=s", follow_redirects=False
    )
    token = _cookie_attrs(_session_cookie_header(r))["__value__"]

    r2 = await client.get("/auth/me", cookies={COOKIE_NAME: token})
    assert r2.status_code == 200
    body = r2.json()
    assert body["email"] == "frank@example.com"
    assert body["name"] == "Frank"
    assert body["role"] == "user"
    assert body["provider"] == "google"
