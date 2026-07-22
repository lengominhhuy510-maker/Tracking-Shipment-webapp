"""TASK-17 — offline deterministic E2E demo chain (Spec §Demo, PROGRESS.md TASK-17).

Full chain in ONE test, no network/keys: seed offline → auth override → list 4 lô
→ tạo lô (IMO/MMSI resolve inline) → AIS replay fixture → recompute ETA + history
→ deviation alert → mail fixture → proposal → approve → WS delta broadcasts.

Determinism: the eta_service clock is FROZEN to ``seed.NOW`` (naive — SQLite
round-trips datetimes naive, so a real aware ``now`` would TypeError against DB
values in the deviation math). With now == seed anchor, deviation_pct depends
only on fixture coords/SOG → identical on every run.
"""

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.api.shipments as shipments_api
import app.services.eta_service as eta_service
from app.api.deps import get_current_user, get_session
from app.api.ws import manager
from app.config import settings
from app.core.geo import haversine_nm
from app.db import seed as seed_module
from app.db.base import Base
from app.db.models import EtaHistory, Shipment, User
from app.db.seed import seed
from app.main import app
from app.services.email_service import poll_once
from app.workers import ais_worker
from tests.email_helpers import fake_extract, load_fixture, make_extraction

ANCHOR = seed_module.NOW.replace(tzinfo=None)  # naive UTC — khớp datetime đọc từ SQLite

# Fixture ais_positions.json — message cuối của MMSI 570000001 (lô 1)
FINAL_LAT, FINAL_LON = 9.51122, 108.20014
SOG_WINDOW = [11.2, 18.1]
# backend/data/wpi_ports.csv — VNCLI Cat Lai
VNCLI_LAT, VNCLI_LON = 10.756, 106.750

NEW_ETA = "2026-08-05T10:00:00+00:00"


class FrozenDatetime(datetime):
    """datetime.now() đóng băng tại ANCHOR (naive) cho eta_service."""

    @classmethod
    def now(cls, tz=None):  # noqa: ARG003 — tz cố ý bỏ qua: DB trả naive
        return ANCHOR


class WsStub:
    """WebSocket giả: gom mọi envelope broadcast vào list."""

    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send_json(self, message: dict) -> None:
        self.messages.append(message)


@pytest.fixture
async def db(monkeypatch):
    # Force seed branch (d) — offline placeholder vessels — regardless of any
    # DEV_SEED_VESSEL_* in the local .env, so shipment #1 keeps the fixture
    # MMSI 570000001 that ais_positions.json replays.
    monkeypatch.setattr(settings, "DEV_SEED_VESSEL_NAME", "")
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        async with s.begin():
            await seed(s)
    yield factory
    await engine.dispose()


@pytest.fixture
async def e2e(db, monkeypatch):
    """Toàn bộ setup E2E: overrides + monkeypatches + WS stub. Yields (client, ws, user)."""
    backend_dir = Path(shipments_api.__file__).resolve().parents[2]
    monkeypatch.setattr(settings, "WPI_DATA_PATH", str(backend_dir / "data" / "wpi_ports.csv"))
    monkeypatch.setattr(settings, "AIS_MODE", "replay")
    monkeypatch.setattr(settings, "ETA_RECOMPUTE_DEBOUNCE_SECONDS", 0)
    monkeypatch.setattr(ais_worker, "async_session_factory", db)
    monkeypatch.setattr(eta_service, "datetime", FrozenDatetime)
    monkeypatch.setattr(shipments_api, "_spawn_carrier_eta_fetch", lambda shipment_id: None)
    eta_service.reset_state()

    # Seed pod "VNCLI Cat Lai" không match geocode (alias chỉ nhận "cat lai"/"vncli")
    # → sửa pod lô 1 thành LOCODE thuần để recompute có tọa độ POD.
    async with db() as session:
        async with session.begin():
            await session.execute(
                update(Shipment).where(Shipment.id == 1).values(pod="VNCLI")
            )
        admin = (
            await session.execute(select(User).where(User.email == "admin@demo"))
        ).scalar_one()

    async def override_session():
        async with db() as session:
            yield session

    async def override_user():
        return admin

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_current_user] = override_user

    ws = WsStub()
    manager.active_connections.append(ws)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, ws, admin

    manager.active_connections.remove(ws)
    app.dependency_overrides.clear()
    eta_service.reset_state()


def _of_type(ws: WsStub, event_type: str, shipment_id: int | None = None) -> list[dict]:
    return [
        m
        for m in ws.messages
        if m["type"] == event_type
        and (shipment_id is None or m["shipment_id"] == shipment_id)
    ]


async def test_e2e_demo_full_chain(e2e, db):
    client, ws, admin = e2e

    # --- 1. Danh sách seed: đúng 4 lô ---
    r = await client.get("/api/v1/shipments/")
    assert r.status_code == 200
    assert len(r.json()) == 4

    # --- 2. Tạo lô mới với IMO+MMSI → resolve inline (mock, không scrape) ---
    r = await client.post(
        "/api/v1/shipments/",
        json={
            "bl_number": "E2E-BL-0100",
            "container_no": "MSKU1234565",
            "shipment_direction": "import",
            "incoterm": "FOB",
            "carrier": "Maersk",
            "vessel_name": "E2E TEST VESSEL",
            "voyage_no": "V.777N",
            "pol": "SGSIN Singapore",
            "pod": "VNCLI Cat Lai",
            "imo": "9321483",
            "mmsi": "477220100",
        },
    )
    assert r.status_code == 201, r.text
    new_id = r.json()["id"]
    assert r.json()["onboarding_status"] == "resolved"
    assert r.json()["imo_resolved_via"] == "manual"
    onboarding = _of_type(ws, "onboarding_update", new_id)
    assert len(onboarding) == 1
    assert onboarding[0]["data"]["onboarding_status"] == "resolved"

    r = await client.get("/api/v1/shipments/")
    assert len(r.json()) == 5

    # --- 3. AIS replay: worker chạy hết fixture rồi tự dừng (generator hữu hạn) ---
    await ais_worker.run()

    async with db() as session:
        s1 = await session.get(Shipment, 1)
        assert s1.current_lat == FINAL_LAT
        assert s1.current_lon == FINAL_LON
        assert s1.current_sog == SOG_WINDOW[-1]

    # 6 message × (1 shipment/MMSI, riêng 570000001 map 2 lô: #1 và #4) = 8 broadcast
    assert len(_of_type(ws, "position_update")) == 8

    # --- 4. Recompute ETA deterministic (clock đóng băng tại ANCHOR) ---
    dist_nm = haversine_nm(FINAL_LAT, FINAL_LON, VNCLI_LAT, VNCLI_LON)
    avg_sog = sum(SOG_WINDOW) / len(SOG_WINDOW)
    expected_eta = ANCHOR + timedelta(hours=dist_nm / avg_sog)
    planned_s = timedelta(days=7).total_seconds()  # eta_original(NOW+5d) − atd(NOW−2d)
    expected_dev = (
        100.0 * (expected_eta - (ANCHOR + timedelta(days=5))).total_seconds() / planned_s
    )
    assert expected_dev < -10  # sớm hơn kế hoạch, vượt ngưỡng cảnh báo

    async with db() as session:
        s1 = await session.get(Shipment, 1)
        assert s1.eta_current == expected_eta
        history = (
            await session.execute(
                select(EtaHistory)
                .where(EtaHistory.shipment_id == 1)
                .order_by(EtaHistory.id)
            )
        ).scalars().all()
        # 2 recompute (2 message MMSI 570000001), delta > 15 phút → 2 dòng
        assert [h.source for h in history] == ["weather_adjusted", "weather_adjusted"]
        assert history[-1].eta_value == expected_eta
        assert history[-1].deviation_pct == pytest.approx(expected_dev)

    # Chỉ lô 1 có POD geocode được → eta_update/deviation_alert chỉ của lô 1
    eta_updates = _of_type(ws, "eta_update")
    assert {m["shipment_id"] for m in eta_updates} == {1}
    assert len(eta_updates) == 2
    alerts = _of_type(ws, "deviation_alert", 1)
    assert len(alerts) == 2  # cả 2 recompute đều lệch quá ngưỡng 10%
    assert alerts[-1]["data"]["deviation_pct"] == pytest.approx(expected_dev)

    # --- 5. Email Agent: fixture .eml → proposal (human-in-the-loop, chưa áp dữ liệu) ---
    imap = AsyncMock()
    imap.fetch_unseen.return_value = [load_fixture("e2e_test.eml")]
    extraction = make_extraction(containers=["CSQU3054383"], new_eta=NEW_ETA)
    processed = await poll_once(
        imap, session_factory=db, extract=fake_extract(extraction)
    )
    assert processed == 1
    imap.store_seen.assert_awaited_once_with(1)

    r = await client.get("/api/v1/agent-proposals", params={"status": "pending"})
    assert r.status_code == 200
    pending = r.json()
    assert len(pending) == 1
    proposal_id = pending[0]["id"]
    assert pending[0]["shipment_id"] == 1
    assert pending[0]["proposed_action"] == "eta_update"

    created = _of_type(ws, "proposal_created", 1)
    assert len(created) == 1
    assert created[0]["data"]["proposal_id"] == proposal_id
    assert created[0]["data"]["container_no"] == "CSQU3054383"

    # eta_current CHƯA đổi — proposal phải chờ người duyệt
    async with db() as session:
        s1 = await session.get(Shipment, 1)
        assert s1.eta_current == expected_eta

    # --- 6. Approve → áp new_eta + eta_history(email_agent); duyệt lần 2 → 409 ---
    r = await client.post(f"/api/v1/agent-proposals/{proposal_id}/approve")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"
    assert r.json()["decided_by"] == admin.id

    approved_eta = datetime(2026, 8, 5, 10, 0)  # naive sau round-trip SQLite
    async with db() as session:
        s1 = await session.get(Shipment, 1)
        assert s1.eta_current == approved_eta
        agent_rows = (
            await session.execute(
                select(EtaHistory)
                .where(EtaHistory.shipment_id == 1)
                .where(EtaHistory.source == "email_agent")
            )
        ).scalars().all()
        assert len(agent_rows) == 1
        assert agent_rows[0].eta_value == approved_eta
        assert f"#{proposal_id}" in agent_rows[0].note

    r = await client.post(f"/api/v1/agent-proposals/{proposal_id}/approve")
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "PROPOSAL_ALREADY_DECIDED"

    r = await client.get("/api/v1/agent-proposals", params={"status": "pending"})
    assert r.json() == []
