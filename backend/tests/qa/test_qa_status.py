"""QA-05 — Status transition + arrival detector (REPORT-ONLY).

Truth: IC§0.3 (status transition table + who decides), Spec §6.3 / IC§7
(ARRIVAL_RADIUS_KM, SOG_MIN_KNOT).

Two surfaces under test:
  A. PATCH /shipments/{id} status transitions (app/api/shipments.py:305-345)
     - atd auto-flips new→on_sea in the SAME request (IC§0.3).
     - arrived→delivered manual; delivered_at auto-set = now() on delivered.
     - backward arrived→on_sea allowed via PATCH (IC§0.3, no hard FSM at MVP).
  B. Arrival detector (app/services/eta_service.py:_check_arrival)
     - within ARRIVAL_RADIUS_KM AND SOG < SOG_MIN_KNOT held >=30' → SUGGESTS
       only (WS status_change_suggested), never auto-PATCHes status.
     - boundary: exact radius edge; SOG fluctuation around threshold (reset).

No app code is modified. Auth is bypassed via conftest.auth_override
(dependency_overrides[get_current_user]). Clock for the detector is pinned by
passing an explicit `now` into _check_arrival (freezegun is not installed);
delivered_at=now() is proven by bounding it between two real wall-clock reads.
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.deps import get_session
from app.config import settings
from app.core.eta_engine import ETAComputeResult
from app.db.base import Base
from app.db.seed import seed
from app.main import app
from app.services import eta_service

UTC = timezone.utc


# --------------------------------------------------------------------------- #
# Fixtures (mirror tests/test_shipments_api.py — SQLite async in-memory + seed)
# --------------------------------------------------------------------------- #
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
        "bl_number": "BL-QA05",
        "container_no": "csqu 305438-3",
        "shipment_direction": "import",
        "incoterm": "FOB",
        "carrier": "Maersk",
        "vessel_name": "QA05 vessel",
        "voyage_no": "V.900N",
        "pol": "SGSIN Singapore",
        "pod": "VNCLI Cat Lai",
    }
    payload.update(overrides)
    return payload


# ============================================================================ #
# PART A — PATCH status transitions (IC§0.3)
# ============================================================================ #
async def test_atd_flips_new_to_on_sea_in_same_request(client):
    """IC§0.3 row 1: nhập atd qua PATCH → hệ tự flip new→on_sea CÙNG request."""
    r = await client.post("/api/v1/shipments/", json=_create_payload(bl_number="BL-QA05-ATD"))
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    assert r.json()["status"] == "new"

    atd = datetime(2026, 7, 20, 12, 0, tzinfo=UTC).isoformat()
    r = await client.patch(f"/api/v1/shipments/{sid}", json={"atd": atd})
    assert r.status_code == 200, r.text
    body = r.json()
    # flip must be visible in the SAME PATCH response, not a later GET
    assert body["status"] == "on_sea"
    assert body["atd"] is not None


async def test_atd_on_already_on_sea_does_not_reflip(client):
    """Flip is guarded by status==new: re-supplying atd on on_sea must NOT
    reset/re-derive status (system only flips the new→on_sea edge)."""
    # seed #1 is already on_sea with an atd
    new_atd = datetime(2026, 7, 21, 0, 0, tzinfo=UTC).isoformat()
    r = await client.patch("/api/v1/shipments/1", json={"atd": new_atd})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "on_sea"


async def test_direct_status_new_to_on_sea_via_patch_blocked(client):
    """IC§0.3: new→on_sea is owned by the ATD trigger, not a free status PATCH.
    status only accepts arrived/delivered or a backward move → forward on_sea
    from new is rejected 400 IMMUTABLE_FIELD (documents current contract)."""
    r = await client.post("/api/v1/shipments/", json=_create_payload(bl_number="BL-QA05-FWD"))
    sid = r.json()["id"]
    assert r.json()["status"] == "new"
    r = await client.patch(f"/api/v1/shipments/{sid}", json={"status": "on_sea"})
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["code"] == "IMMUTABLE_FIELD"


async def test_on_sea_to_arrived_allowed_manual(client):
    """IC§0.3 row 2: user confirms arrival via PATCH status=arrived."""
    r = await client.patch("/api/v1/shipments/1", json={"status": "arrived"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "arrived"
    assert r.json()["delivered_at"] is None  # only delivered sets this


async def test_arrived_to_delivered_manual_sets_delivered_at_now(client):
    """IC§0.3 rows 3-4: arrived→delivered is manual; delivered_at auto = now()."""
    r = await client.patch("/api/v1/shipments/1", json={"status": "arrived"})
    assert r.status_code == 200, r.text

    before = datetime.now(UTC)
    r = await client.patch("/api/v1/shipments/1", json={"status": "delivered"})
    after = datetime.now(UTC)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "delivered"
    assert body["delivered_at"] is not None

    delivered_at = datetime.fromisoformat(body["delivered_at"])
    if delivered_at.tzinfo is None:
        delivered_at = delivered_at.replace(tzinfo=UTC)
    # delivered_at == now(): must fall within the wall-clock bracket of the call
    assert before <= delivered_at <= after, (before, delivered_at, after)


async def test_backward_arrived_to_on_sea_allowed(client):
    """IC§0.3: chuyển ngược arrived→on_sea ĐƯỢC phép qua PATCH (no hard FSM).
    If this is blocked → DRIFT vs IC§0.3."""
    r = await client.patch("/api/v1/shipments/1", json={"status": "arrived"})
    assert r.status_code == 200, r.text
    r = await client.patch("/api/v1/shipments/1", json={"status": "on_sea"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "on_sea"


async def test_backward_delivered_to_arrived_allowed(client):
    """Backward from the terminal state must also be allowed (IC§0.3)."""
    r = await client.patch("/api/v1/shipments/1", json={"status": "delivered"})
    assert r.status_code == 200, r.text
    r = await client.patch("/api/v1/shipments/1", json={"status": "arrived"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "arrived"


# ============================================================================ #
# PART B — Arrival detector: SUGGEST-ONLY, never auto-PATCH (IC§0.3, Spec §6.3)
# ============================================================================ #
@pytest.fixture(autouse=True)
def _reset_detector_state():
    eta_service.reset_state()
    yield
    eta_service.reset_state()


@pytest.fixture
def captured_suggestions(monkeypatch):
    """Capture WS status_change_suggested emissions without touching app code."""
    calls: list[tuple[int, dict]] = []

    async def _fake(shipment_id: int, data: dict) -> None:
        calls.append((shipment_id, data))

    monkeypatch.setattr(eta_service, "broadcast_status_change_suggested", _fake)
    return calls


def _radius_nm() -> float:
    return settings.ARRIVAL_RADIUS_KM / eta_service.KM_PER_NM


def _idle_result(distance_nm: float, sog_kn: float) -> ETAComputeResult:
    return ETAComputeResult(distance_remaining_nm=distance_nm, avg_sog_kn=sog_kn)


async def test_suggest_fires_after_30min_within_radius_and_below_sog(captured_suggestions):
    """Within ARRIVAL_RADIUS_KM AND SOG < SOG_MIN_KNOT held >=30' → suggest."""
    t0 = datetime(2026, 7, 22, 0, 0, tzinfo=UTC)
    res = _idle_result(_radius_nm() - 0.5, settings.SOG_MIN_KNOT - 0.5)

    # first observation only starts the clock — no suggestion yet
    await eta_service._check_arrival(1, res, t0)
    assert captured_suggestions == []

    # exactly 30 minutes later, condition still holds → suggestion fires
    await eta_service._check_arrival(1, res, t0 + timedelta(minutes=30))
    assert len(captured_suggestions) == 1
    sid, data = captured_suggestions[0]
    assert sid == 1
    assert data["suggested"] == "arrived"  # system only proposes 'arrived'
    assert "reason" in data


async def test_no_suggest_before_30min(captured_suggestions):
    """Held only 29 minutes → no suggestion (>=30' threshold)."""
    t0 = datetime(2026, 7, 22, 0, 0, tzinfo=UTC)
    res = _idle_result(_radius_nm() - 0.5, settings.SOG_MIN_KNOT - 0.5)
    await eta_service._check_arrival(1, res, t0)
    await eta_service._check_arrival(1, res, t0 + timedelta(minutes=29))
    assert captured_suggestions == []


async def test_boundary_exact_radius_edge_is_inside(captured_suggestions):
    """distance == radius uses `<=` → counts as inside; distance just beyond →
    outside and never suggests (documents the mép bán kính behavior)."""
    t0 = datetime(2026, 7, 22, 0, 0, tzinfo=UTC)

    # exactly on the edge → inside → suggests at +30'
    edge = _idle_result(_radius_nm(), settings.SOG_MIN_KNOT - 0.5)
    await eta_service._check_arrival(1, edge, t0)
    await eta_service._check_arrival(1, edge, t0 + timedelta(minutes=30))
    assert len(captured_suggestions) == 1

    # just beyond the edge for a different shipment → never suggests
    eta_service.reset_state()
    captured_suggestions.clear()
    outside = _idle_result(_radius_nm() + 0.01, settings.SOG_MIN_KNOT - 0.5)
    await eta_service._check_arrival(2, outside, t0)
    await eta_service._check_arrival(2, outside, t0 + timedelta(minutes=60))
    assert captured_suggestions == []


async def test_boundary_sog_exactly_at_threshold_is_not_idle(captured_suggestions):
    """SOG == SOG_MIN_KNOT is NOT below min (`<` strict) → not idle → no suggest."""
    t0 = datetime(2026, 7, 22, 0, 0, tzinfo=UTC)
    at_threshold = _idle_result(_radius_nm() - 0.5, settings.SOG_MIN_KNOT)
    await eta_service._check_arrival(1, at_threshold, t0)
    await eta_service._check_arrival(1, at_threshold, t0 + timedelta(minutes=60))
    assert captured_suggestions == []


async def test_sog_fluctuation_resets_counter(captured_suggestions):
    """25' below threshold, then SOG spikes above → counter RESET; a later dip
    restarts the 30' clock from the reset (deterministic reset behavior)."""
    t0 = datetime(2026, 7, 22, 0, 0, tzinfo=UTC)
    below = _idle_result(_radius_nm() - 0.5, settings.SOG_MIN_KNOT - 0.5)
    above = _idle_result(_radius_nm() - 0.5, settings.SOG_MIN_KNOT + 2.0)

    await eta_service._check_arrival(1, below, t0)                       # start clock
    await eta_service._check_arrival(1, below, t0 + timedelta(minutes=25))  # 25' held
    assert captured_suggestions == []

    # SOG vọt lên trên ngưỡng → reset đếm
    await eta_service._check_arrival(1, above, t0 + timedelta(minutes=26))
    assert captured_suggestions == []

    # dip again → new first_seen at +27'; +25' more is NOT enough (would be old logic)
    await eta_service._check_arrival(1, below, t0 + timedelta(minutes=27))  # restart
    await eta_service._check_arrival(1, below, t0 + timedelta(minutes=52))  # +25' since restart
    assert captured_suggestions == []

    # 30' after the restart → fires
    await eta_service._check_arrival(1, below, t0 + timedelta(minutes=57))
    assert len(captured_suggestions) == 1
    assert captured_suggestions[0][1]["suggested"] == "arrived"


async def test_leaving_radius_resets_counter(captured_suggestions):
    """Leaving the radius mid-window drops the marker; must re-accumulate 30'."""
    t0 = datetime(2026, 7, 22, 0, 0, tzinfo=UTC)
    inside = _idle_result(_radius_nm() - 0.5, settings.SOG_MIN_KNOT - 0.5)
    outside = _idle_result(_radius_nm() + 5.0, settings.SOG_MIN_KNOT - 0.5)

    await eta_service._check_arrival(1, inside, t0)
    await eta_service._check_arrival(1, outside, t0 + timedelta(minutes=20))  # left radius
    await eta_service._check_arrival(1, inside, t0 + timedelta(minutes=21))   # re-enter
    await eta_service._check_arrival(1, inside, t0 + timedelta(minutes=45))   # only 24' since re-enter
    assert captured_suggestions == []
    await eta_service._check_arrival(1, inside, t0 + timedelta(minutes=51))   # 30' since re-enter
    assert len(captured_suggestions) == 1


async def test_missing_metrics_clears_marker(captured_suggestions):
    """None distance/SOG (no position/sog) clears the marker, never suggests."""
    t0 = datetime(2026, 7, 22, 0, 0, tzinfo=UTC)
    inside = _idle_result(_radius_nm() - 0.5, settings.SOG_MIN_KNOT - 0.5)
    await eta_service._check_arrival(1, inside, t0)
    # a gap with no metrics resets the accumulator
    await eta_service._check_arrival(1, ETAComputeResult(distance_remaining_nm=None, avg_sog_kn=None), t0 + timedelta(minutes=10))
    await eta_service._check_arrival(1, inside, t0 + timedelta(minutes=11))
    await eta_service._check_arrival(1, inside, t0 + timedelta(minutes=39))  # only 28' since restart
    assert captured_suggestions == []


async def test_detector_cannot_auto_patch_status(captured_suggestions):
    """Suggest-only guarantee: _check_arrival takes NO session, returns None,
    and only emits the WS suggestion — there is no path for it to PATCH status.
    System proposes; a human decides (IC§0.3)."""
    import inspect

    sig = inspect.signature(eta_service._check_arrival)
    assert "session" not in sig.parameters  # cannot write to DB by construction

    t0 = datetime(2026, 7, 22, 0, 0, tzinfo=UTC)
    res = _idle_result(_radius_nm() - 0.5, settings.SOG_MIN_KNOT - 0.5)
    ret = await eta_service._check_arrival(1, res, t0 + timedelta(minutes=30))
    await eta_service._check_arrival(1, res, t0 + timedelta(minutes=30))
    # the only side effect is the suggestion; nothing sets status='arrived'
    assert ret is None
    assert all(d["suggested"] == "arrived" for _, d in captured_suggestions)
