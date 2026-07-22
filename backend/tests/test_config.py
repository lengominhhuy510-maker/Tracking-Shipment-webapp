"""TASK-00 tests: Settings defaults, devtest template key set, health endpoint."""

from pathlib import Path

import httpx
from httpx import ASGITransport

from app.config import Settings
from app.main import app

_ROOT = Path(__file__).resolve().parents[2]
_DEVTEST_TEMPLATE = _ROOT / ".env.devtest2"


def _parse_env_template(path: Path) -> dict[str, str]:
    """Parse simple KEY=VALUE lines; strip inline comments after the value."""
    result: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if "#" in value:
            value = value.split("#", 1)[0]
        result[key] = value.strip()
    return result


def test_settings_defaults() -> None:
    s = Settings(_env_file=None)
    assert s.APP_PORT == 1476
    assert s.APP_BASE_URL == "http://localhost:1476"
    assert s.DATABASE_URL == "postgresql+asyncpg://app:app@db:5432/shipment_demo"
    assert s.REDIS_URL == "redis://redis:6379/0"
    assert s.AIS_MODE == "live"
    assert s.SEARCH_API_PROVIDER == "tavily"
    assert s.WPI_DATA_PATH == "/app/data/wpi_ports.csv"
    assert s.SESSION_JWT_EXPIRE_HOURS == 72
    assert s.COOKIE_SECURE is False
    assert s.EMAIL_POLL_INTERVAL_MINUTES == 5
    assert "maersk.com" in s.CARRIER_EMAIL_DOMAINS
    assert s.SOG_MIN_KNOT == 1.5
    assert s.ETA_DEVIATION_THRESHOLD_PCT == 10
    assert s.CURRENT_AGAINST_THRESHOLD_KN == 1.0
    assert s.CURRENT_AGAINST_PENALTY_PCT == 8
    assert s.WIND_AGAINST_THRESHOLD_KN == 25
    assert s.WIND_AGAINST_PENALTY_PCT == 5
    assert s.AVG_SOG_WINDOW_MSGS == 10
    assert s.ETA_RECOMPUTE_DEBOUNCE_SECONDS == 60
    assert s.ETA_HISTORY_MIN_DELTA_MINUTES == 15
    assert s.ARRIVAL_RADIUS_KM == 5
    assert s.TIDAL_WINDOW_HOURS == 2
    assert s.WEATHER_POLL_HOURS == 6
    assert s.TIDE_POLL_HOURS == 12
    assert s.RESEARCH_CADENCE_HOURS == 12
    assert s.TRAIL_SNAPSHOT_HOURS == 6
    assert s.AIS_RESUBSCRIBE_POLL_SECONDS == 60
    assert s.SCRAPE_REST_PORT == 3000
    assert s.MCP_SSE_PORT == 3001
    assert s.SCRAPE_CONCURRENCY == 2
    assert s.SCRAPE_JOB_TIMEOUT_SECONDS == 90


def test_devtest_template_keys_and_replay_mode() -> None:
    """.env.devtest2 (tracked dev/test template) must carry the full IC§7 key set
    and intentionally override AIS_MODE=replay."""
    assert _DEVTEST_TEMPLATE.exists(), f"missing tracked template: {_DEVTEST_TEMPLATE}"
    env = _parse_env_template(_DEVTEST_TEMPLATE)

    assert env.get("AIS_MODE") == "replay"

    settings_fields = set(Settings.model_fields.keys())
    missing = settings_fields - set(env.keys())
    assert not missing, f".env.devtest2 missing keys present in Settings: {sorted(missing)}"


async def test_health_endpoint(auth_override) -> None:
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
