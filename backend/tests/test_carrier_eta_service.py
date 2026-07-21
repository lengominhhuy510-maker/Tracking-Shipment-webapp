"""TASK-12 — carrier ETA service: mock agent/MCP → correct DB writes + boundary."""

import ast
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agents import carrier_eta_agent
from app.db.base import Base
from app.db.models import EtaHistory, Shipment
from app.integrations.errors import ExternalIntegrationError
from app.services import carrier_eta_service
from app.services.carrier_eta_service import fetch_carrier_eta, parse_agent_eta


@pytest.fixture
async def db(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(carrier_eta_service, "async_session_factory", factory)
    yield factory
    await engine.dispose()


async def _seed_shipment(db, **overrides) -> int:
    fields = dict(
        bl_number="BL-CETA-1",
        container_no="CSQU3054383",
        incoterm="FOB",
        shipment_direction="import",
        carrier="Maersk",
        vessel_name="EVER GIVEN",
        voyage_no="V001",
        pol="SGSIN",
        pod="VNCLI",
        monitoring_mode="auto_email",
        onboarding_status="resolved",
        imo="9321483",
        mmsi="477220100",
    )
    fields.update(overrides)
    async with db() as session:
        shipment = Shipment(**fields)
        session.add(shipment)
        await session.commit()
        return shipment.id


AGENT_OK_TEXT = (
    "Đã mở trang tracking Maersk, điền B/L, đọc bảng lịch trình.\n"
    "ETA_FOUND: 2026-08-01T10:00:00+00:00\n"
)


def _as_utc_naive(value: datetime) -> datetime:
    """SQLite trả naive UTC — chuẩn hoá cả hai vế để so sánh."""
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


async def test_fetch_writes_eta_original_carrier_scrape_and_history(db, monkeypatch):
    """Mock MCP/agent trả trang giả có ETA → ghi đúng field + source + history."""
    shipment_id = await _seed_shipment(db)
    monkeypatch.setattr(
        carrier_eta_agent, "run_carrier_eta_agent", AsyncMock(return_value=AGENT_OK_TEXT)
    )

    await fetch_carrier_eta(shipment_id)

    async with db() as session:
        shipment = await session.get(Shipment, shipment_id)
        expected = datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)
        assert _as_utc_naive(shipment.eta_original) == _as_utc_naive(expected)
        assert shipment.eta_original_source == "carrier_scrape"
        assert shipment.eta_current is None  # KHÔNG BAO GIỜ đụng eta_current

        rows = (
            await session.execute(
                select(EtaHistory).where(EtaHistory.shipment_id == shipment_id)
            )
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].source == "original"
        assert _as_utc_naive(rows[0].eta_value) == _as_utc_naive(expected)


async def test_fetch_skips_when_eta_original_already_set(db, monkeypatch):
    """eta_original đã có (nhập tay) → không gọi agent, không ghi đè."""
    manual_eta = datetime(2026, 7, 30, 8, 0, tzinfo=timezone.utc)
    shipment_id = await _seed_shipment(
        db, eta_original=manual_eta, eta_original_source="manual"
    )
    agent = AsyncMock(return_value=AGENT_OK_TEXT)
    monkeypatch.setattr(carrier_eta_agent, "run_carrier_eta_agent", agent)

    await fetch_carrier_eta(shipment_id)

    agent.assert_not_awaited()
    async with db() as session:
        shipment = await session.get(Shipment, shipment_id)
        assert _as_utc_naive(shipment.eta_original) == _as_utc_naive(manual_eta)
        assert shipment.eta_original_source == "manual"


async def test_manual_entry_during_agent_run_wins(db, monkeypatch):
    """User nhập tay trong lúc agent chạy → nhập tay thắng, agent không ghi đè."""
    shipment_id = await _seed_shipment(db)
    manual_eta = datetime(2026, 7, 29, 6, 0, tzinfo=timezone.utc)

    async def agent_that_races(**kwargs) -> str:
        async with db() as session:
            shipment = await session.get(Shipment, shipment_id)
            shipment.eta_original = manual_eta
            shipment.eta_original_source = "manual"
            await session.commit()
        return AGENT_OK_TEXT

    monkeypatch.setattr(carrier_eta_agent, "run_carrier_eta_agent", agent_that_races)

    await fetch_carrier_eta(shipment_id)

    async with db() as session:
        shipment = await session.get(Shipment, shipment_id)
        assert _as_utc_naive(shipment.eta_original) == _as_utc_naive(manual_eta)
        assert shipment.eta_original_source == "manual"
        rows = (
            await session.execute(
                select(EtaHistory).where(EtaHistory.shipment_id == shipment_id)
            )
        ).scalars().all()
        assert rows == []


async def test_fetch_not_found_marker_writes_nothing(db, monkeypatch):
    shipment_id = await _seed_shipment(db)
    monkeypatch.setattr(
        carrier_eta_agent,
        "run_carrier_eta_agent",
        AsyncMock(return_value="Trang bắt đăng nhập.\nETA_NOT_FOUND: login_required\n"),
    )

    await fetch_carrier_eta(shipment_id)

    async with db() as session:
        shipment = await session.get(Shipment, shipment_id)
        assert shipment.eta_original is None
        assert shipment.eta_original_source is None


def test_parse_agent_eta_variants():
    assert parse_agent_eta("ETA_FOUND: 2026-08-01T10:00:00+00:00") == datetime(
        2026, 8, 1, 10, 0, tzinfo=timezone.utc
    )
    # Z suffix + naive (coi là UTC) + offset khác quy về UTC
    assert parse_agent_eta("ETA_FOUND: 2026-08-01T10:00:00Z") == datetime(
        2026, 8, 1, 10, 0, tzinfo=timezone.utc
    )
    assert parse_agent_eta("ETA_FOUND: 2026-08-01T10:00:00") == datetime(
        2026, 8, 1, 10, 0, tzinfo=timezone.utc
    )
    assert parse_agent_eta("ETA_FOUND: 2026-08-01T17:00:00+07:00") == datetime(
        2026, 8, 1, 10, 0, tzinfo=timezone.utc
    )
    assert parse_agent_eta("ETA_NOT_FOUND: captcha") is None
    assert parse_agent_eta("ETA_FOUND: không rõ") is None
    assert parse_agent_eta("") is None


def test_unsupported_carrier_returns_not_found_marker():
    assert carrier_eta_agent._tracking_url("Hãng Lạ") is None
    assert carrier_eta_agent._tracking_url("Maersk Line") is not None
    assert carrier_eta_agent._tracking_url("MSC") is not None
    assert carrier_eta_agent._tracking_url("") is None


def test_mcp_import_confined_to_gateway():
    """Boundary (validation check 3): chỉ browser_agent_client.py import ``mcp``."""
    app_dir = Path(__file__).resolve().parents[1] / "app"
    offenders = []
    for path in app_dir.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            if any(n == "mcp" or n.startswith("mcp.") for n in names):
                offenders.append(path.name)
    assert set(offenders) == {"browser_agent_client.py"}, offenders


async def test_gateway_call_tool_outside_context_raises_nonretryable():
    from app.integrations.browser_agent_client import BrowserAgentClient

    client = BrowserAgentClient(url="http://localhost:0/sse")
    with pytest.raises(ExternalIntegrationError) as excinfo:
        await client.call_tool("browser_navigate", {"url": "x"})
    assert excinfo.value.retryable is False
