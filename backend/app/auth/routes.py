"""Auth routes at root (no /api/v1 prefix — matches registered redirect URIs).

Flow per Spec §3.8 + IC§10: login → Authlib redirect (state+PKCE automatic) →
callback verifies code → id_token claims → upsert users on (provider,
provider_sub) → issue session JWT → HttpOnly cookie → 302 /.
"""

from datetime import datetime, timezone

from authlib.integrations.base_client import OAuthError
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_session
from app.api.errors import raise_api_error
from app.auth.jwt import issue_token
from app.auth.oauth import PROVIDERS, oauth, redirect_uri
from app.config import settings
from app.db.models import User

router = APIRouter(prefix="/auth", tags=["auth"])

COOKIE_NAME = "session_token"


def _check_provider(provider: str) -> None:
    if provider not in PROVIDERS:
        raise_api_error(404, "UNKNOWN_PROVIDER", f"Provider không hỗ trợ: {provider}")


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=settings.SESSION_JWT_EXPIRE_HOURS * 3600,
        path="/",
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
    )


@router.get("/login/{provider}")
async def login(provider: str, request: Request):
    _check_provider(provider)
    client = oauth.create_client(provider)
    return await client.authorize_redirect(request, redirect_uri(provider))


@router.get("/callback/{provider}")
async def callback(provider: str, request: Request, session: AsyncSession = Depends(get_session)):
    _check_provider(provider)
    client = oauth.create_client(provider)
    try:
        token = await client.authorize_access_token(request)
    except OAuthError:
        raise_api_error(
            401, "UNAUTHENTICATED", "OAuth callback bị từ chối (state/token không hợp lệ)"
        )
    userinfo = token.get("userinfo")
    if not userinfo or not userinfo.get("sub"):
        raise_api_error(401, "UNAUTHENTICATED", "OAuth callback thiếu id_token claims")

    provider_sub = str(userinfo["sub"])
    email = userinfo.get("email") or ""
    name = userinfo.get("name")

    result = await session.execute(
        select(User).where(User.provider == provider, User.provider_sub == provider_sub)
    )
    user = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if user is None:
        user = User(
            email=email,
            name=name,
            provider=provider,
            provider_sub=provider_sub,
            role="user",
            last_login_at=now,
        )
        session.add(user)
    else:
        user.email = email
        user.name = name
        user.last_login_at = now
    await session.commit()
    await session.refresh(user)

    response = RedirectResponse(url="/", status_code=302)
    set_session_cookie(response, issue_token(user.id, user.role))
    return response


@router.get("/me")
async def me(user: User = Depends(get_current_user)) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "provider": user.provider,
    }


@router.post("/logout", status_code=204)
async def logout() -> Response:
    response = Response(status_code=204)
    response.delete_cookie(COOKIE_NAME, path="/")
    return response
