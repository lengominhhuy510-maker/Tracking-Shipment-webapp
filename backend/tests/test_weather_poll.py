"""TDD tests for weather_poll worker (TASK-07): upsert on success, cache kept on failure."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import EnvConditions, Shipment
from app.integrations.errors import ExternalIntegrationError
from app.integrations.open_meteo import WeatherConditions
from app.workers import weather_poll


@pytest.fixture
async def db(monkeypatch: pytest.MonkeyPatch):
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(weather_poll, "async_session_factory", factory)
    yield factory
    await engine.dispose()


def _shipment(bl: str, status: str = "on_sea", lat: float | None = 10.2) -> Shipment:
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
        current_lat=lat,
        current_lon=None if lat is None else 107.3,
    )


def _conditions() -> WeatherConditions:
    return WeatherConditions(
        wind_speed_kn=12.5,
        wave_height_m=1.4,
        current_speed_kn=0.9,
        current_direction_deg=210.0,
        fetched_at=datetime(2026, 7, 21, 12, tzinfo=UTC),
    )


async def _get_env(factory, shipment_id: int) -> EnvConditions | None:
    async with factory() as session:
        return await session.get(EnvConditions, shipment_id)


async def test_poll_updates_weather_fields_for_on_sea_shipment(db, monkeypatch) -> None:
    async with db() as session:
        shipment = _shipment("BL-1")
        session.add(shipment)
        await session.commit()
        shipment_id = shipment.id

    async def fake_fetch(lat: float, lon: float) -> WeatherConditions:
        return _conditions()

    monkeypatch.setattr(weather_poll, "fetch_conditions", fake_fetch)

    assert await weather_poll._poll_once() == 1

    env = await _get_env(db, shipment_id)
    assert env is not None
    assert env.wind_speed_kn == 12.5
    assert env.wave_height_m == 1.4
    assert env.current_speed_kn == 0.9
    assert env.current_direction_deg == 210.0
    assert env.weather_fetched_at is not None


async def test_poll_skips_non_on_sea_and_missing_position(db, monkeypatch) -> None:
    async with db() as session:
        session.add_all(
            [
                _shipment("BL-1", status="new"),
                _shipment("BL-2", status="arrived"),
                _shipment("BL-3", lat=None),
            ]
        )
        await session.commit()

    calls: list[tuple[float, float]] = []

    async def fake_fetch(lat: float, lon: float) -> WeatherConditions:
        calls.append((lat, lon))
        return _conditions()

    monkeypatch.setattr(weather_poll, "fetch_conditions", fake_fetch)

    assert await weather_poll._poll_once() == 0
    assert calls == []


async def test_provider_failure_keeps_cached_values(db, monkeypatch) -> None:
    async with db() as session:
        shipment = _shipment("BL-1")
        session.add(shipment)
        await session.flush()
        session.add(
            EnvConditions(
                shipment_id=shipment.id,
                wind_speed_kn=20.0,
                weather_fetched_at=datetime(2026, 7, 20, 12, tzinfo=UTC),
                tide_station_name="Vung Tau",
            )
        )
        await session.commit()
        shipment_id = shipment.id

    async def fake_fetch(lat: float, lon: float) -> WeatherConditions:
        raise ExternalIntegrationError("boom", retryable=True)

    monkeypatch.setattr(weather_poll, "fetch_conditions", fake_fetch)

    assert await weather_poll._poll_once() == 0

    env = await _get_env(db, shipment_id)
    assert env.wind_speed_kn == 20.0
    assert env.weather_fetched_at is not None
    assert env.tide_station_name == "Vung Tau"


async def test_one_failure_does_not_block_other_shipments(db, monkeypatch) -> None:
    async with db() as session:
        bad = _shipment("BL-BAD")
        good = _shipment("BL-GOOD")
        session.add_all([bad, good])
        await session.commit()
        bad_id, good_id = bad.id, good.id

    async def fake_fetch(lat: float, lon: float) -> WeatherConditions:
        if fake_fetch.calls == 0:
            fake_fetch.calls += 1
            raise ExternalIntegrationError("boom", retryable=True)
        return _conditions()

    fake_fetch.calls = 0
    monkeypatch.setattr(weather_poll, "fetch_conditions", fake_fetch)

    assert await weather_poll._poll_once() == 1

    assert await _get_env(db, bad_id) is None
    assert (await _get_env(db, good_id)).wind_speed_kn == 12.5


async def test_success_preserves_tide_fields(db, monkeypatch) -> None:
    async with db() as session:
        shipment = _shipment("BL-1")
        session.add(shipment)
        await session.flush()
        session.add(
            EnvConditions(
                shipment_id=shipment.id,
                tide_extremes=[{"time": "2026-07-21T12:00:00Z", "type": "high"}],
                tide_station_name="Vung Tau",
                tide_station_distance_km=12.0,
                tide_fetched_at=datetime(2026, 7, 21, 0, tzinfo=UTC),
            )
        )
        await session.commit()
        shipment_id = shipment.id

    async def fake_fetch(lat: float, lon: float) -> WeatherConditions:
        return _conditions()

    monkeypatch.setattr(weather_poll, "fetch_conditions", fake_fetch)

    assert await weather_poll._poll_once() == 1

    env = await _get_env(db, shipment_id)
    assert env.wind_speed_kn == 12.5
    assert env.tide_station_name == "Vung Tau"
    assert env.tide_extremes == [{"time": "2026-07-21T12:00:00Z", "type": "high"}]
    assert env.tide_fetched_at is not None
