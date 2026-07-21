"""Session JWT issue/verify (IC§10): HS256, claims sub/role/iat/exp, no refresh."""

from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError
from jose import jwt as jose_jwt

from app.config import settings

_ALGORITHM = "HS256"


def issue_token(user_id: int, role: str) -> str:
    now = datetime.now(timezone.utc)
    iat = int(now.timestamp())
    exp = int((now + timedelta(hours=settings.SESSION_JWT_EXPIRE_HOURS)).timestamp())
    claims = {"sub": str(user_id), "role": role, "iat": iat, "exp": exp}
    return jose_jwt.encode(claims, settings.SESSION_JWT_SECRET, algorithm=_ALGORITHM)


def verify_token(token: str) -> dict[str, Any] | None:
    try:
        return jose_jwt.decode(token, settings.SESSION_JWT_SECRET, algorithms=[_ALGORITHM])
    except JWTError:
        return None
