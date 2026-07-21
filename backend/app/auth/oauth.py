"""Authlib OAuth clients for Google + Microsoft OIDC (Spec §3.8).

Authlib 1.7.2 `authorize_redirect`/`authorize_access_token` handle state + PKCE
automatically (code_challenge_method in client_kwargs); do not hand-roll them.
"""

from authlib.integrations.starlette_client import OAuth

from app.config import settings

PROVIDERS = ("google", "microsoft")

# scope: openid is required for OIDC id_token; email profile per Spec §3.8
_CLIENT_KWARGS = {"scope": "openid email profile", "code_challenge_method": "S256"}

oauth = OAuth()

oauth.register(
    name="google",
    client_id=settings.GOOGLE_CLIENT_ID,
    client_secret=settings.GOOGLE_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs=_CLIENT_KWARGS,
)

oauth.register(
    name="microsoft",
    client_id=settings.MICROSOFT_CLIENT_ID,
    client_secret=settings.MICROSOFT_CLIENT_SECRET,
    server_metadata_url=(
        "https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration"
    ),
    client_kwargs=_CLIENT_KWARGS,
)


def redirect_uri(provider: str) -> str:
    return f"{settings.APP_BASE_URL}/auth/callback/{provider}"
