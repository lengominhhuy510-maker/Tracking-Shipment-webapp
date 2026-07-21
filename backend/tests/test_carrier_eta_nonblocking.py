"""TASK-12 acceptance (v0.9.12 BẮT BUỘC) — Carrier ETA không bao giờ chặn tracking.

Mock MCP/LLM raise mọi kiểu lỗi → shipment vẫn ``resolved`` (KHÔNG chuyển
``manual_required``), ``eta_current`` không đổi, và lô chỉ có IMO/MMSI (thiếu
``eta_original``) vẫn nằm trong tập subscribe AIS bình thường.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agents import carrier_eta_agent
from app.api.deps import get_session
from app.db.base import Base
from app.db.models import EtaHistory, Shipment, ShipmentLeg
from app.integrations.errors import ExternalIntegrationError
from app.main import app
from app.services import carrier_eta_service
from app.services.carrier_eta_service import fetch_carrier_eta
from app.services.subscription import desired_mmsi_set


def _as_utc_naive(value: datetime) -> datetime:
    """SQLite trả naive UTC — chuẩn hoá cả hai vế để so sánh."""
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


@pytest.fixture
async def db(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(carrier_eta_service, "async_session_factory", factory)
    yield factory
    await engine.dispose()


async def _seed_resolved_shipment(db, *, eta_current=None) -> int:
    """Lô đã resolved (có IMO/MMSI), chưa có eta_original — trạng thái sau TASK-11."""
    async with db() as session:
        shipment = Shipment(
            bl_number="BL-NB-1",
            container_no="CSQU3054383",
            incoterm="FOB",
            shipment_direction="import",
            carrier="MSC",
            vessel_name="EVER GIVEN",
            voyage_no="V001",
            pol="SGSIN",
            pod="VNCLI",
            monitoring_mode="auto_email",
            status="on_sea",
            onboarding_status="resolved",
            imo="9321483",
            mmsi="477220100",
            imo_resolved_via="manual",
            eta_current=eta_current,
        )
        session.add(shipment)
        await session.flush()
        leg = ShipmentLeg(
            shipment_id=shipment.id,
            leg_no=1,
            vessel_name="EVER GIVEN",
            voyage_no="V001",
            pol="SGSIN",
            pod="VNCLI",
            is_active_leg=True,
            onboarding_status="resolved",
            imo="9321483",
            mmsi="477220100",
            imo_resolved_via="manual",
        )
        session.add(leg)
        await session.commit()
        return shipment.id


FAILURES = [
    ExternalIntegrationError("MCP SSE connect/handshake failed", retryable=True),
    ExternalIntegrationError("thiếu LLM_API_KEY/LLM_MODEL", retryable=False),
    ExternalIntegrationError("AG2 chat run failed: timeout", retryable=True),
    RuntimeError("unexpected agent crash"),
]


@pytest.mark.parametrize("failure", FAILURES, ids=lambda e: type(e).__name__ + str(e)[:24])
async def test_agent_failure_keeps_shipment_resolved_and_eta_untouched(
    db, monkeypatch, failure
):
    """Acceptance lõi: agent raise → resolved giữ nguyên, không ghi ETA nào."""
    eta_current = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)
    shipment_id = await _seed_resolved_shipment(db, eta_current=eta_current)
    monkeypatch.setattr(
        carrier_eta_agent, "run_carrier_eta_agent", AsyncMock(side_effect=failure)
    )

    # Không raise xuyên qua service — non-blocking guarantee.
    await fetch_carrier_eta(shipment_id)

    async with db() as session:
        shipment = await session.get(Shipment, shipment_id)
        assert shipment.onboarding_status == "resolved"  # KHÔNG chuyển manual_required
        assert shipment.onboarding_error is None
        assert _as_utc_naive(shipment.eta_current) == _as_utc_naive(eta_current)  # eta_current không đổi
        assert shipment.eta_original is None
        assert shipment.eta_original_source is None

        legs = (
            await session.execute(
                select(ShipmentLeg).where(ShipmentLeg.shipment_id == shipment_id)
            )
        ).scalars().all()
        assert all(leg.onboarding_status == "resolved" for leg in legs)

        history = (
            await session.execute(
                select(EtaHistory).where(EtaHistory.shipment_id == shipment_id)
            )
        ).scalars().all()
        assert history == []


async def test_shipment_without_eta_original_still_ais_tracked(db, monkeypatch):
    """Lô chỉ có IMO/MMSI (thiếu eta_original) vẫn được subscribe AIS bình thường."""
    shipment_id = await _seed_resolved_shipment(db)
    monkeypatch.setattr(
        carrier_eta_agent,
        "run_carrier_eta_agent",
        AsyncMock(side_effect=ExternalIntegrationError("MCP down", retryable=True)),
    )
    await fetch_carrier_eta(shipment_id)

    async with db() as session:
        assert await desired_mmsi_set(session) == {"477220100"}


async def test_resolve_manual_api_ok_when_carrier_eta_agent_raises(db, monkeypatch):
    """Luồng API TASK-11 không bị chặn: resolve-manual trả 200 resolved dù agent nổ."""
    monkeypatch.setattr(
        carrier_eta_agent,
        "run_carrier_eta_agent",
        AsyncMock(side_effect=ExternalIntegrationError("MCP down", retryable=True)),
    )

    async with db() as session:
        shipment = Shipment(
            bl_number="BL-NB-2",
            container_no="CSQU3054383",
            incoterm="FOB",
            shipment_direction="import",
            carrier="Maersk",
            vessel_name="API VESSEL",
            voyage_no="V002",
            pol="SGSIN",
            pod="VNCLI",
            monitoring_mode="auto_email",
        )
        session.add(shipment)
        await session.flush()
        session.add(
            ShipmentLeg(
                shipment_id=shipment.id,
                leg_no=1,
                vessel_name="API VESSEL",
                voyage_no="V002",
                pol="SGSIN",
                pod="VNCLI",
                is_active_leg=True,
            )
        )
        await session.commit()
        shipment_id = shipment.id

    async def override_session():
        async with db() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post(
                f"/api/v1/shipments/{shipment_id}/resolve-manual",
                json={"imo": "9321483", "mmsi": "477220100"},
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["onboarding_status"] == "resolved"

        # Chờ task nền carrier-eta tiêu thụ xong lỗi (không lan ra ngoài).
        import asyncio

        from app.api.shipments import _onboarding_tasks

        pending = [t for t in _onboarding_tasks if not t.done()]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
    finally:
        app.dependency_overrides.clear()

    async with db() as session:
        shipment = await session.get(Shipment, shipment_id)
        assert shipment.onboarding_status == "resolved"
        assert shipment.eta_original is None
