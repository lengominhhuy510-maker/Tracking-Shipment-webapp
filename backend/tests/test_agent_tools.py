"""TDD tests for Agent A tools (TASK-08, IC§5.1) — DB reads only, no LLM."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agents import tools
from app.config import settings
from app.db.base import Base
from app.db.models import EnvConditions, Shipment
from app.services import eta_service


@pytest.fixture
async def db(monkeypatch: pytest.MonkeyPatch):
    wpi = Path(__file__).parents[1] / "data" / "wpi_ports.csv"
    monkeypatch.setattr(settings, "WPI_DATA_PATH", str(wpi))
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(tools, "async_session_factory", factory)
    eta_service.reset_state()
    yield factory
    eta_service.reset_state()
    await engine.dispose()


def _shipment(bl: str = "BL-1", **overrides) -> Shipment:
    fields = dict(
        bl_number=bl,
        container_no="CSQU3054383",
        incoterm="FOB",
        shipment_direction="import",
        monitoring_mode="auto_email",
        carrier="Maersk",
        vessel_name="TEST VESSEL",
        pol="SGSIN Singapore",
        pod="VNCLI Cat Lai",
        status="on_sea",
        onboarding_status="resolved",
        current_lat=8.5,
        current_lon=106.2,
        current_sog=12.4,
        current_cog=310.0,
        atd=datetime(2026, 7, 18, 6, tzinfo=UTC),
        eta_original=datetime(2026, 7, 22, 12, tzinfo=UTC),
        eta_current=datetime(2026, 7, 21, 12, tzinfo=UTC),
    )
    fields.update(overrides)
    return Shipment(**fields)


_EXTREMES = [
    {"time": "2026-07-21T12:00:00Z", "height": 2.1, "type": "high"},
    {"time": "2026-07-21T18:00:00Z", "height": 0.4, "type": "low"},
]


async def _seed_one(factory, shipment: Shipment, env: EnvConditions | None = None) -> int:
    async with factory() as session:
        session.add(shipment)
        await session.flush()
        if env is not None:
            env.shipment_id = shipment.id
            session.add(env)
        await session.commit()
        return shipment.id


async def test_get_shipment_state_returns_state_and_route_key(db) -> None:
    shipment_id = await _seed_one(db, _shipment(), EnvConditions(wind_speed_kn=18.0))

    view = await tools.get_shipment_state(shipment_id)

    assert view.shipment_id == shipment_id
    assert view.status == "on_sea"
    assert view.current_lat == 8.5
    assert view.current_lon == 106.2
    assert view.sog == 12.4
    assert view.cog == 310.0
    assert view.atd == datetime(2026, 7, 18, 6, tzinfo=UTC)
    assert view.eta_original == datetime(2026, 7, 22, 12, tzinfo=UTC)
    assert view.eta_current == datetime(2026, 7, 21, 12, tzinfo=UTC)
    assert view.route_key == "SGSIN-VNCLI"
    assert view.env is not None
    assert view.env.wind_speed_kn == 18.0


async def test_get_shipment_state_without_env_row(db) -> None:
    shipment_id = await _seed_one(db, _shipment())

    view = await tools.get_shipment_state(shipment_id)

    assert view.env is None


async def test_get_shipment_state_unknown_id_raises(db) -> None:
    with pytest.raises(ValueError, match="9999"):
        await tools.get_shipment_state(9999)


async def test_get_tide_window_reads_env_conditions(db) -> None:
    fetched_at = datetime.now(UTC) - timedelta(hours=3)
    shipment_id = await _seed_one(
        db,
        _shipment(eta_current=datetime(2026, 7, 21, 13, tzinfo=UTC)),
        EnvConditions(
            tide_extremes=_EXTREMES,
            tide_station_name="Vung Tau",
            tide_fetched_at=fetched_at,
        ),
    )

    result = await tools.get_tide_window(shipment_id)

    assert result.extremes == _EXTREMES
    assert result.eta_falls_in_window is True  # 13:00 within 2h of 12:00 high
    assert result.station_name == "Vung Tau"
    assert result.data_age_hours == pytest.approx(3.0, abs=0.1)


async def test_get_tide_window_outside_window_is_false(db) -> None:
    shipment_id = await _seed_one(
        db,
        _shipment(eta_current=datetime(2026, 7, 21, 17, tzinfo=UTC)),
        EnvConditions(tide_extremes=_EXTREMES, tide_station_name="Vung Tau"),
    )

    result = await tools.get_tide_window(shipment_id)

    assert result.eta_falls_in_window is False
    assert result.data_age_hours is None


async def test_get_tide_window_without_env_returns_empty(db) -> None:
    shipment_id = await _seed_one(db, _shipment())

    result = await tools.get_tide_window(shipment_id)

    assert result.extremes == []
    assert result.eta_falls_in_window is None
    assert result.station_name is None
    assert result.data_age_hours is None


async def test_recompute_eta_wrapper_no_position(db) -> None:
    shipment_id = await _seed_one(db, _shipment(current_lat=None, current_lon=None))

    result = await tools.recompute_eta(shipment_id)

    assert result.skipped_reason == "no_position"


async def test_recompute_eta_wrapper_reports_debounce(db) -> None:
    shipment_id = await _seed_one(db, _shipment(current_lat=None, current_lon=None))

    first = await tools.recompute_eta(shipment_id)
    second = await tools.recompute_eta(shipment_id)

    assert first.skipped_reason == "no_position"
    assert second.skipped_reason == "debounced"


async def test_request_research_delegates_to_research_service(db, monkeypatch) -> None:
    # TASK-09 replaced the TASK-08 stub: the tool now routes to research_service.
    from app.services import research_service

    shipment_id = await _seed_one(db, _shipment())
    calls: list[tuple[int, str | None]] = []

    async def fake_request_research(sid: int, focus: str | None = None):
        calls.append((sid, focus))
        return tools.ResearchFindingOut(
            event="delegated",
            relevance="thap",
            route_impact="",
            confidence="thap",
            sources=["https://example.invalid/delegated"],
        )

    monkeypatch.setattr(research_service, "request_research", fake_request_research)

    finding = await tools.request_research(shipment_id, focus="eo Malacca 48h")

    assert calls == [(shipment_id, "eo Malacca 48h")]
    assert finding.event == "delegated"


# --- reasoning_service: note write + endpoint key-gate ---


class _FakeRunner:
    def __init__(self, text: str = "Nhận định: ETA ổn định.") -> None:
        self.text = text

    async def run(self, message: str) -> str:
        return self.text


@pytest.fixture
def reasoning(db, monkeypatch: pytest.MonkeyPatch):
    from app.services import reasoning_service

    monkeypatch.setattr(reasoning_service, "async_session_factory", db)
    monkeypatch.setattr(reasoning_service.agent_a, "build_agent_a", lambda: _FakeRunner())
    return reasoning_service


async def test_run_agent_a_inserts_note_row_when_no_history(db, reasoning) -> None:
    shipment_id = await _seed_one(db, _shipment())

    note = await reasoning.run_agent_a(shipment_id)

    assert note == "Nhận định: ETA ổn định."
    async with db() as session:
        from sqlalchemy import select

        from app.db.models import EtaHistory, Shipment

        row = (await session.execute(select(EtaHistory))).scalar_one()
        assert row.shipment_id == shipment_id
        assert row.source == "weather_adjusted"
        assert row.note == note
        # agent never overrides the baseline number (§6.3b)
        shipment = await session.get(Shipment, shipment_id)
        assert shipment.eta_current == datetime(2026, 7, 21, 12)


async def test_run_agent_a_updates_last_note_when_eta_unchanged(db, reasoning) -> None:
    from sqlalchemy import select

    from app.db.models import EtaHistory

    shipment_id = await _seed_one(db, _shipment())
    async with db() as session:
        session.add(
            EtaHistory(
                shipment_id=shipment_id,
                eta_value=datetime(2026, 7, 21, 12, tzinfo=UTC),
                source="weather_adjusted",
                note="cũ",
            )
        )
        await session.commit()

    await reasoning.run_agent_a(shipment_id)

    async with db() as session:
        rows = (await session.execute(select(EtaHistory))).scalars().all()
        assert len(rows) == 1  # updated in place, no new row (IC§5.2)
        assert rows[0].note == "Nhận định: ETA ổn định."


async def test_analyze_endpoint_without_key_returns_clear_error(db, monkeypatch) -> None:
    from httpx import ASGITransport, AsyncClient

    from app.api.deps import get_session
    from app.main import app

    monkeypatch.setattr(settings, "LLM_API_KEY", "")
    shipment_id = await _seed_one(db, _shipment())

    async def override_session():
        async with db() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post(f"/api/v1/shipments/{shipment_id}/analyze")
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "LLM_NOT_CONFIGURED"
