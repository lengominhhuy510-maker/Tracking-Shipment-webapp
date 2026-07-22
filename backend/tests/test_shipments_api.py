"""Smoke + logic tests for shipments REST API — SQLite async in-memory, seeded 4 lô."""

from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.deps import get_session
from app.db.base import Base
from app.db.models import ShipmentLeg
from app.db.seed import seed
from app.main import app


@pytest.fixture
async def db():
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
async def client(db, auth_override):
    async def override_session():
        async with db() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


def _create_payload(**overrides) -> dict:
    payload = {
        "bl_number": "BL-API-1",
        "container_no": "csqu 305438-3",
        "shipment_direction": "import",
        "incoterm": "FOB",
        "carrier": "Maersk",
        "vessel_name": "  api  Test vessel ",
        "voyage_no": "V.900N",
        "pol": "SGSIN Singapore",
        "pod": "VNCLI Cat Lai",
    }
    payload.update(overrides)
    return payload


async def test_list_returns_4_seed_shipments(client):
    r = await client.get("/api/v1/shipments/")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 4
    assert {s["bl_number"] for s in body} == {
        "SEED-BL-0001", "SEED-BL-0002", "SEED-BL-0003", "SEED-BL-0004",
    }


async def test_list_filters_status_and_direction(client):
    r = await client.get("/api/v1/shipments/", params={"direction": "export"})
    assert r.status_code == 200
    assert [s["bl_number"] for s in r.json()] == ["SEED-BL-0003"]

    r = await client.get("/api/v1/shipments/", params={"status": "new"})
    assert r.status_code == 200
    assert r.json() == []


async def test_post_import_fob_201_auto_email(client):
    r = await client.post("/api/v1/shipments/", json=_create_payload())
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["monitoring_mode"] == "auto_email"
    assert body["container_no"] == "CSQU3054383"  # normalized
    assert body["vessel_name"] == "API TEST VESSEL"  # normalized
    assert body["status"] == "new"
    assert len(body["legs"]) == 1
    leg = body["legs"][0]
    assert leg["leg_no"] == 1
    assert leg["is_active_leg"] is True
    assert leg["onboarding_status"] == "pending"


async def test_post_export_fob_400_unsupported(client):
    r = await client.post(
        "/api/v1/shipments/",
        json=_create_payload(shipment_direction="export", incoterm="FOB"),
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "UNSUPPORTED_INCOTERM_COMBINATION"


async def test_post_bad_check_digit_400_invalid_container(client):
    r = await client.post(
        "/api/v1/shipments/", json=_create_payload(container_no="CSQU3054384")
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "INVALID_CONTAINER_NO"


async def test_post_with_imo_mmsi_resolves_inline(client, db):
    r = await client.post(
        "/api/v1/shipments/", json=_create_payload(imo="9321483", mmsi="477220100")
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["onboarding_status"] == "resolved"
    assert body["imo"] == "9321483"
    assert body["imo_resolved_via"] == "manual"
    # mirror also on the leg
    async with db() as s:
        leg = (
            await s.execute(
                select(ShipmentLeg).where(ShipmentLeg.shipment_id == body["id"])
            )
        ).scalar_one()
        assert leg.imo == "9321483"
        assert leg.onboarding_status == "resolved"


async def test_get_detail_embeds_legs_env_history(client):
    r = await client.get("/api/v1/shipments/1")
    assert r.status_code == 200
    body = r.json()
    assert body["bl_number"] == "SEED-BL-0001"
    assert len(body["legs"]) == 1
    assert body["env"] is None
    assert body["recent_eta_history"] == []


async def test_get_404(client):
    r = await client.get("/api/v1/shipments/9999")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "SHIPMENT_NOT_FOUND"


async def test_patch_imo_400_immutable(client):
    r = await client.patch("/api/v1/shipments/1", json={"imo": "9999999"})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "IMMUTABLE_FIELD"


@pytest.mark.parametrize("field", ["monitoring_mode", "eta_current", "current_lat", "incoterm"])
async def test_patch_forbidden_fields_400(client, field):
    r = await client.patch("/api/v1/shipments/1", json={field: "x"})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "IMMUTABLE_FIELD"


async def test_patch_atd_flips_new_to_on_sea(client):
    # create a fresh shipment (status=new)
    r = await client.post("/api/v1/shipments/", json=_create_payload(bl_number="BL-ATD"))
    sid = r.json()["id"]
    assert r.json()["status"] == "new"

    atd = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc).isoformat()
    r = await client.patch(f"/api/v1/shipments/{sid}", json={"atd": atd})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "on_sea"


async def test_patch_eta_original_sets_source_manual(client):
    eta = datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc).isoformat()
    r = await client.patch("/api/v1/shipments/1", json={"eta_original": eta})
    assert r.status_code == 200, r.text
    assert r.json()["eta_original_source"] == "manual"


async def test_patch_pol_after_atd_400(client):
    # seed shipment #1 has atd set
    r = await client.patch("/api/v1/shipments/1", json={"pol": "HKHKG"})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "IMMUTABLE_FIELD"


async def test_patch_status_forward_and_backward(client):
    # on_sea → arrived (allowed)
    r = await client.patch("/api/v1/shipments/1", json={"status": "arrived"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "arrived"
    # arrived → on_sea (backward, allowed per IC§0.3)
    r = await client.patch("/api/v1/shipments/1", json={"status": "on_sea"})
    assert r.status_code == 200
    assert r.json()["status"] == "on_sea"


async def test_patch_status_delivered_sets_delivered_at(client):
    r = await client.patch("/api/v1/shipments/1", json={"status": "delivered"})
    assert r.status_code == 200
    assert r.json()["delivered_at"] is not None


async def test_resolve_manual(client):
    r = await client.post(
        "/api/v1/shipments/2/resolve-manual",
        json={"imo": "9321483", "mmsi": "477220100"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["imo"] == "9321483"
    assert body["onboarding_status"] == "resolved"
    assert body["imo_resolved_via"] == "manual"


async def test_retry_onboarding_not_retryable_400(client):
    # seed legs are resolved → not manual_required
    r = await client.post("/api/v1/shipments/1/retry-onboarding")
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "ONBOARDING_NOT_RETRYABLE"


async def test_retry_onboarding_202_when_manual_required(client, db):
    async with db() as s:
        async with s.begin():
            leg = (
                await s.execute(select(ShipmentLeg).where(ShipmentLeg.shipment_id == 1))
            ).scalar_one()
            leg.onboarding_status = "manual_required"
            leg.onboarding_error = "not_found"

    r = await client.post("/api/v1/shipments/1/retry-onboarding")
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["leg_id"] == leg.id
    assert "job_id" in body


async def test_trail_and_eta_history_empty(client):
    r = await client.get("/api/v1/shipments/1/trail")
    assert r.status_code == 200
    assert r.json() == []
    r = await client.get("/api/v1/shipments/1/eta-history")
    assert r.status_code == 200
    assert r.json() == []
