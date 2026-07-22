import pytest

from app.api.deps import get_current_user
from app.db.models import User
from app.main import app
from tests.email_helpers import db  # noqa: F401 — shared in-memory DB fixture


@pytest.fixture
def auth_override():
    """Bypass session-cookie auth (TASK-14) via dependency override — app code untouched.

    Returns a detached User(id=1); suites that seed their own user rely on the
    first-inserted row also getting id=1 in a fresh in-memory SQLite DB.
    """
    user = User(
        id=1,
        email="test-override@example.com",
        provider="google",
        provider_sub="test-override",
        role="user",
    )

    async def override_user() -> User:
        return user

    app.dependency_overrides[get_current_user] = override_user
    yield user
    app.dependency_overrides.pop(get_current_user, None)
