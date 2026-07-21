"""TDD tests for tide_poll worker (TASK-07): quota, cache, and alerts."""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.db.base import Base
from app.db.models import EnvConditions, Shipment
from app.integrations.errors import ExternalIntegrationError
from app.integrations.stormglass import TideConditions
from app.workers import tide_poll


@pytest.fixture
async def db(monkeypatch: pytest.MonkeyPatch):
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(tide_poll, "async_session_factory", factory)
    monkeypatch.setattr(settings, "STORMGLASS_API_KEY", "test-key")
    tide_poll.reset_quota()
    yield factory
    tide_poll.reset_quota()
    await engine.dispose()


def _shipment(bl: str, *, status: str = "on_sea", eta_hours: int = 4) -> Shipment:
    return Shipment(
        bl_number=bl,
        container_no="CSQU3054383",
        incoterm="FOB",
        shipment_direction="import",
        monitoring_mode="auto_email",
        carrier="Maersk",
        vessel_name="TEST VESSEL",
        pol="SGSIN",
        pod="VNCLI",
        status=status,
        onboarding_status="resolved",
        eta_current=datetime(2026, 7, 21, 12, tzinfo=UTC) + timedelta(hours=eta_hours),
    )


def _conditions() -> TideConditions:
    return TideConditions(
        extremes=[
            {"time": "2026-07-21T12:00:00Z", "height": 2.1, "type": "high"},
            {"time": "2026-07-21T18:00:00Z", "height": 0.4, "type": "low"},
        ],
        station_name="Vung Tau",
        station_distance_km=12.0,
        fetched_at=datetime(2026, 7, 21, 10, tzinfo=UTC),
    )


async def _get_env(factory, shipment_id: int) -> EnvConditions | None:
    async with factory() as session:
        return await session.get(EnvConditions, shipment_id)


async def test_missing_key_skips_without_crashing(db, monkeypatch, caplog) -> None:
    monkeypatch.setattr(settings, "STORMGLASS_API_KEY", "")
    calls = 0

    async def fake_fetch(lat: float, lon: float, api_key: str) -> TideConditions:
        nonlocal calls
        calls += 1
        return _conditions()

    monkeypatch.setattr(tide_poll, "fetch_tide", fake_fetch)

    assert await tide_poll._poll_once() == 0
    assert calls == 0
    assert "thiếu STORMGLASS_API_KEY" in caplog.text


async def test_success_updates_tide_fields_and_preserves_weather(db, monkeypatch) -> None:
    async with db() as session:
        shipment = _shipment("BL-1")
        session.add(shipment)
        await session.flush()
        session.add(EnvConditions(shipment_id=shipment.id, wind_speed_kn=12.0))
        await session.commit()
        shipment_id = shipment.id

    monkeypatch.setattr(tide_poll, "geocode_port", lambda pod: (10.756, 106.75, "VNCLI"))

    async def fake_fetch(lat: float, lon: float, api_key: str) -> TideConditions:
        return _conditions()

    monkeypatch.setattr(tide_poll, "fetch_tide", fake_fetch)
    monkeypatch.setattr(tide_poll, "broadcast_tidal_alert", _noop_broadcast)

    assert await tide_poll._poll_once() == 1

    env = await _get_env(db, shipment_id)
    assert env.wind_speed_kn == 12.0
    assert env.tide_station_name == "Vung Tau"
    assert env.tide_station_distance_km == 12.0
    assert env.tide_extremes == _conditions().extremes
    assert env.tide_fetched_at is not None


async def test_failed_request_keeps_cached_tide(db, monkeypatch) -> None:
    async with db() as session:
        shipment = _shipment("BL-1")
        session.add(shipment)
        await session.flush()
        session.add(
            EnvConditions(
                shipment_id=shipment.id,
                tide_extremes=[{"time": "old"}],
                tide_station_name="Old Station",
                tide_fetched_at=datetime(2026, 7, 20, tzinfo=UTC),
            )
        )
        await session.commit()
        shipment_id = shipment.id

    monkeypatch.setattr(tide_poll, "geocode_port", lambda pod: (10.756, 106.75, "VNCLI"))

    async def fake_fetch(lat: float, lon: float, api_key: str) -> TideConditions:
        raise ExternalIntegrationError("boom", retryable=True)

    monkeypatch.setattr(tide_poll, "fetch_tide", fake_fetch)

    assert await tide_poll._poll_once() == 0

    env = await _get_env(db, shipment_id)
    assert env.tide_extremes == [{"time": "old"}]
    assert env.tide_station_name == "Old Station"


async def test_quota_allows_ten_calls_and_skips_eleventh(db, monkeypatch) -> None:
    async with db() as session:
        session.add_all([_shipment(f"BL-{number}") for number in range(11)])
        await session.commit()

    monkeypatch.setattr(tide_poll, "geocode_port", lambda pod: (10.756, 106.75, "VNCLI"))
    calls = 0

    async def fake_fetch(lat: float, lon: float, api_key: str) -> TideConditions:
        nonlocal calls
        calls += 1
        return _conditions()

    monkeypatch.setattr(tide_poll, "fetch_tide", fake_fetch)
    monkeypatch.setattr(tide_poll, "broadcast_tidal_alert", _noop_broadcast)

    assert await tide_poll._poll_once() == 10
    assert calls == 10


async def test_quota_resets_on_new_utc_day(db, monkeypatch) -> None:
    tide_poll._quota_day = date(2026, 7, 20)
    tide_poll._quota_calls = 10
    monkeypatch.setattr(tide_poll, "_utc_today", lambda: date(2026, 7, 21))

    async with db() as session:
        session.add(_shipment("BL-1"))
        await session.commit()

    monkeypatch.setattr(tide_poll, "geocode_port", lambda pod: (10.756, 106.75, "VNCLI"))

    async def fake_fetch(lat: float, lon: float, api_key: str) -> TideConditions:
        return _conditions()

    monkeypatch.setattr(tide_poll, "fetch_tide", fake_fetch)
    monkeypatch.setattr(tide_poll, "broadcast_tidal_alert", _noop_broadcast)

    assert await tide_poll._poll_once() == 1
    assert tide_poll._quota_calls == 1


async def test_outside_window_broadcasts_after_successful_update(db, monkeypatch) -> None:
    async with db() as session:
        shipment = _shipment("BL-1", eta_hours=4)
        session.add(shipment)
        await session.commit()
        shipment_id = shipment.id

    monkeypatch.setattr(tide_poll, "geocode_port", lambda pod: (10.756, 106.75, "VNCLI"))

    async def fake_fetch(lat: float, lon: float, api_key: str) -> TideConditions:
        return _conditions()

    alerts: list[tuple[int, dict]] = []

    async def fake_broadcast(target_id: int, data: dict) -> None:
        assert await _get_env(db, target_id) is not None
        alerts.append((target_id, data))

    monkeypatch.setattr(tide_poll, "fetch_tide", fake_fetch)
    monkeypatch.setattr(tide_poll, "broadcast_tidal_alert", fake_broadcast)

    assert await tide_poll._poll_once() == 1
    assert alerts == [
        (
            shipment_id,
            {
                "eta_current": "2026-07-21T16:00:00+00:00",
                "nearest_window": "2026-07-21T12:00:00+00:00",
                "message": "có thể phải chờ con nước",
            },
        )
    ]


async def test_inside_window_does_not_broadcast(db, monkeypatch) -> None:
    async with db() as session:
        session.add(_shipment("BL-1", eta_hours=1))
        await session.commit()

    monkeypatch.setattr(tide_poll, "geocode_port", lambda pod: (10.756, 106.75, "VNCLI"))

    async def fake_fetch(lat: float, lon: float, api_key: str) -> TideConditions:
        return _conditions()

    alerts: list[dict] = []

    async def fake_broadcast(shipment_id: int, data: dict) -> None:
        alerts.append(data)

    monkeypatch.setattr(tide_poll, "fetch_tide", fake_fetch)
    monkeypatch.setattr(tide_poll, "broadcast_tidal_alert", fake_broadcast)

    assert await tide_poll._poll_once() == 1
    assert alerts == []


async def _noop_broadcast(shipment_id: int, data: dict) -> None:
    return None
