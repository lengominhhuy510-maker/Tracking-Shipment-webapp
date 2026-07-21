"""TDD for session JWT issue/verify (IC§10: claims sub/role/iat/exp, HS256)."""

from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt as jose_jwt

from app.auth import jwt as session_jwt
from app.config import settings

SECRET = "test-secret-for-jwt"


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch):
    monkeypatch.setattr(settings, "SESSION_JWT_SECRET", SECRET)


async def test_issue_verify_round_trip():
    token = session_jwt.issue_token(user_id=42, role="user")
    claims = session_jwt.verify_token(token)
    assert claims is not None
    assert claims["sub"] == "42"
    assert claims["role"] == "user"
    assert isinstance(claims["iat"], int)
    assert isinstance(claims["exp"], int)
    expected = claims["iat"] + settings.SESSION_JWT_EXPIRE_HOURS * 3600
    assert claims["exp"] == expected


async def test_expired_token_returns_none():
    now = datetime.now(timezone.utc)
    token = jose_jwt.encode(
        {
            "sub": "42",
            "role": "user",
            "iat": int((now - timedelta(hours=100)).timestamp()),
            "exp": int((now - timedelta(hours=1)).timestamp()),
        },
        SECRET,
        algorithm="HS256",
    )
    assert session_jwt.verify_token(token) is None


async def test_wrong_secret_returns_none():
    token = jose_jwt.encode(
        {
            "sub": "42",
            "role": "user",
            "iat": int(datetime.now(timezone.utc).timestamp()),
            "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
        },
        "some-other-secret",
        algorithm="HS256",
    )
    assert session_jwt.verify_token(token) is None


async def test_garbage_token_returns_none():
    assert session_jwt.verify_token("not.a.jwt") is None
    assert session_jwt.verify_token("") is None
