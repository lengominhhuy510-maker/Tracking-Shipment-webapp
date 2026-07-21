import json
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import Shipment, ShipmentLeg
from app.services.leg_service import mark_leg_manual, resolve_leg
from app.services.scrape_client import IMOResolverResult, ScrapeError, resolve_imo
from app.services.subscription import ResubscribeSignal


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _seed_leg(db, *, active: bool = True) -> tuple[int, int]:
    async with db() as session:
        shipment = Shipment(
            bl_number="BL-LEG-1",
            container_no="CSQU3054383",
            incoterm="FOB",
            shipment_direction="import",
            carrier="Test Carrier",
            vessel_name="EVER GIVEN",
            voyage_no="V001",
            pol="SGSIN",
            pod="VNCLI",
            monitoring_mode="auto_email",
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
            is_active_leg=active,
        )
        session.add(leg)
        await session.commit()
        return shipment.id, leg.id


async def test_resolve_leg_mirrors_active_leg_atomically(db):
    shipment_id, leg_id = await _seed_leg(db)
    signal = ResubscribeSignal()
    broadcast = AsyncMock()

    async with db() as session:
        await resolve_leg(
            session,
            leg_id,
            "9811000",
            "353136000",
            "deterministic_scrape",
            resubscribe_signal=signal,
            broadcast=broadcast,
        )

    async with db() as session:
        leg = await session.get(ShipmentLeg, leg_id)
        shipment = await session.get(Shipment, shipment_id)
        assert (leg.imo, leg.mmsi, leg.onboarding_status, leg.imo_resolved_via) == (
            "9811000",
            "353136000",
            "resolved",
            "deterministic_scrape",
        )
        assert (
            shipment.imo,
            shipment.mmsi,
            shipment.onboarding_status,
            shipment.imo_resolved_via,
            shipment.onboarding_error,
        ) == ("9811000", "353136000", "resolved", "deterministic_scrape", None)

    assert signal.is_set()
    broadcast.assert_awaited_once_with(
        shipment_id,
        {"onboarding_status": "resolved", "onboarding_error": None, "leg_id": leg_id},
    )


async def test_mark_leg_manual_mirrors_error_and_notifies(db):
    shipment_id, leg_id = await _seed_leg(db)
    signal = ResubscribeSignal()
    broadcast = AsyncMock()

    async with db() as session:
        await mark_leg_manual(
            session,
            leg_id,
            "ambiguous_name",
            resubscribe_signal=signal,
            broadcast=broadcast,
        )

    async with db() as session:
        leg = await session.get(ShipmentLeg, leg_id)
        shipment = await session.get(Shipment, shipment_id)
        assert (leg.onboarding_status, leg.onboarding_error) == (
            "manual_required",
            "ambiguous_name",
        )
        assert (shipment.onboarding_status, shipment.onboarding_error) == (
            "manual_required",
            "ambiguous_name",
        )

    assert signal.is_set()
    broadcast.assert_awaited_once_with(
        shipment_id,
        {
            "onboarding_status": "manual_required",
            "onboarding_error": "ambiguous_name",
            "leg_id": leg_id,
        },
    )


async def test_resolve_inactive_leg_does_not_change_shipment_mirror(db):
    shipment_id, leg_id = await _seed_leg(db, active=False)

    async with db() as session:
        await resolve_leg(
            session,
            leg_id,
            "9811000",
            "353136000",
            "cache_hit",
            broadcast=AsyncMock(),
        )

    async with db() as session:
        leg = await session.get(ShipmentLeg, leg_id)
        shipment = await session.get(Shipment, shipment_id)
        assert leg.onboarding_status == "resolved"
        assert shipment.onboarding_status == "pending"
        assert shipment.imo is None


async def test_resolve_leg_rolls_back_leg_when_mirror_update_fails(db):
    _, leg_id = await _seed_leg(db)

    async with db() as session:
        leg = await session.get(ShipmentLeg, leg_id)
        leg.shipment_id = 999999
        await session.commit()

    async with db() as session:
        with pytest.raises(RuntimeError, match="active leg shipment missing"):
            await resolve_leg(
                session,
                leg_id,
                "9811000",
                "353136000",
                "manual",
                broadcast=AsyncMock(),
            )

    async with db() as session:
        leg = await session.get(ShipmentLeg, leg_id)
        assert leg.onboarding_status == "pending"
        assert leg.imo is None


async def test_scrape_client_posts_normalized_payload_and_polls_to_success():
    seen_requests: list[httpx.Request] = []
    poll_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal poll_count
        seen_requests.append(request)
        if request.method == "POST":
            return httpx.Response(202, json={"job_id": "job-1"})
        poll_count += 1
        if poll_count == 1:
            return httpx.Response(200, json={"job_id": "job-1", "status": "running"})
        return httpx.Response(
            200,
            json={
                "job_id": "job-1",
                "status": "succeeded",
                "result": {
                    "vessel_name": "ever given",
                    "imo": "9811000",
                    "mmsi": "353136000",
                    "matched_voyage": "V001",
                    "confidence": "cao",
                    "source_url": "https://www.vesselfinder.com/vessels/details/9811000",
                },
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://playwright-mcp:3000"
    ) as client:
        result = await resolve_imo(
            "  ever   given ",
            "V001",
            "SGSIN",
            "VNCLI",
            client=client,
            sleep=AsyncMock(),
        )

    assert isinstance(result, IMOResolverResult)
    assert (result.vessel_name, result.imo, result.mmsi, result.confidence) == (
        "EVER GIVEN",
        "9811000",
        "353136000",
        "cao",
    )
    assert [request.method for request in seen_requests] == ["POST", "GET", "GET"]
    assert json.loads(seen_requests[0].content) == {
        "type": "imo_resolve",
        "payload": {
            "vessel_name": "EVER GIVEN",
            "voyage_no": "V001",
            "pol": "SGSIN",
            "pod": "VNCLI",
        },
    }


@pytest.mark.parametrize(
    "error_code",
    ["captcha", "not_found", "ambiguous_name", "timeout", "login_required"],
)
async def test_scrape_client_preserves_terminal_error_codes(error_code):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, json={"job_id": "job-2"})
        return httpx.Response(
            200,
            json={"job_id": "job-2", "status": "failed", "error_code": error_code},
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://playwright-mcp:3000"
    ) as client:
        result = await resolve_imo("EVER GIVEN", client=client, sleep=AsyncMock())

    assert result == ScrapeError(error_code)


async def test_scrape_client_rejects_invalid_success_result():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, json={"job_id": "job-3"})
        return httpx.Response(
            200,
            json={
                "job_id": "job-3",
                "status": "succeeded",
                "result": {
                    "vessel_name": "EVER GIVEN",
                    "imo": "123",
                    "mmsi": None,
                    "matched_voyage": None,
                    "confidence": "cao",
                    "source_url": "https://example.com/vessel",
                },
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://playwright-mcp:3000"
    ) as client:
        result = await resolve_imo("EVER GIVEN", client=client, sleep=AsyncMock())

    assert result == ScrapeError("not_found")


async def test_scrape_client_times_out_after_poll_budget():
    sleep = AsyncMock()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, json={"job_id": "job-4"})
        return httpx.Response(200, json={"job_id": "job-4", "status": "queued"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://playwright-mcp:3000"
    ) as client:
        result = await resolve_imo(
            "EVER GIVEN",
            client=client,
            sleep=sleep,
            poll_interval_s=3,
            timeout_s=6,
        )

    assert result == ScrapeError("timeout")
    assert sleep.await_count == 2
