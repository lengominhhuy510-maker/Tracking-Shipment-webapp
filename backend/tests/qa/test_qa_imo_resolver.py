"""QA-13 — IMO resolver Python boundary (Spec §6.7a, IC§3.3, IC§4.1, IC§9).

WHERE THE LOGIC LIVES (grep-verified): HTML→imo/mmsi parsing + dedup +
ambiguous_name/not_found all live in TypeScript
``playwright-mcp/src/jobs/imo_resolve.ts`` (IC§0.1). Python only:
  (a) re-validates the Node result against ``IMOResolverResult`` (Pydantic, IC§4.1),
  (b) maps ``status=failed``/``error_code`` and validation failures to ``ScrapeError``,
  (c) routes a ``ScrapeError`` to ``mark_leg_manual`` → leg ``manual_required`` +
      ``onboarding_error`` (the §6.7a fallback — **Python writes, not Node**).

So this Python suite tests ONLY that boundary. Parse/dedup coverage is in the
TS sibling ``playwright-mcp/tests/qa/imo_resolver.qa.test.ts``. No real network:
the poll HTTP layer is driven by an in-memory async fake with the correct async
signature (no RuntimeWarning), and the DB is the shared in-memory SQLite fixture.

RUN (from backend/, replay mode):
  $env:AIS_MODE="replay"; python -m pytest tests/qa/test_qa_imo_resolver.py -v
"""

from __future__ import annotations

import warnings

import pytest
from pydantic import HttpUrl, ValidationError

from app.db.models import Shipment, ShipmentLeg
from app.services import scrape_client
from app.services.leg_service import mark_leg_manual

# ---------------------------------------------------------------------------
# IC§4.1 — IMOResolverResult validation is the Python "strict boundary".
# ---------------------------------------------------------------------------

VALID_RESULT = {
    "vessel_name": "ever   given",  # not yet normalized — validator must normalize
    "imo": "9811000",
    "mmsi": "235095435",
    "matched_voyage": "V123",
    "confidence": "cao",
    "source_url": "https://www.vesselfinder.com/vessels/details/9811000",
}


def test_result_accepts_valid_and_normalizes_name():
    r = scrape_client.IMOResolverResult.model_validate(VALID_RESULT)
    assert r.imo == "9811000"
    assert r.mmsi == "235095435"
    # vessel_name goes through normalize_vessel_name (IC§9): collapse ws + upper.
    assert r.vessel_name == "EVER GIVEN"
    assert r.confidence == "cao"
    assert isinstance(r.source_url, HttpUrl)


def test_result_mmsi_optional_none_is_valid():
    payload = {**VALID_RESULT, "mmsi": None}
    r = scrape_client.IMOResolverResult.model_validate(payload)
    assert r.mmsi is None


@pytest.mark.parametrize("bad_imo", ["981100", "98110000", "abcdefg", "981100X", ""])
def test_result_rejects_imo_not_exactly_7_digits(bad_imo):
    """IC§4.1 imo ^\\d{7}$ — 6/8/non-digit must be rejected (no invented identity)."""
    with pytest.raises(ValidationError):
        scrape_client.IMOResolverResult.model_validate({**VALID_RESULT, "imo": bad_imo})


@pytest.mark.parametrize("bad_mmsi", ["23509543", "2350954351", "23509543X"])
def test_result_rejects_mmsi_not_exactly_9_digits(bad_mmsi):
    """IC§4.1 mmsi ^\\d{9}$ when present (8/10/non-digit rejected)."""
    with pytest.raises(ValidationError):
        scrape_client.IMOResolverResult.model_validate({**VALID_RESULT, "mmsi": bad_mmsi})


@pytest.mark.parametrize("bad_conf", ["high", "medium", "CAO", "unknown", ""])
def test_result_rejects_confidence_outside_literal(bad_conf):
    """IC§4.1 confidence ∈ {cao, trung_binh, thap} — anything else rejected."""
    with pytest.raises(ValidationError):
        scrape_client.IMOResolverResult.model_validate({**VALID_RESULT, "confidence": bad_conf})


def test_result_rejects_non_http_source_url():
    with pytest.raises(ValidationError):
        scrape_client.IMOResolverResult.model_validate({**VALID_RESULT, "source_url": "not a url"})


# ---------------------------------------------------------------------------
# Async HTTP fake — correct signatures so no coroutine-never-awaited warnings.
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:  # httpx.Response.raise_for_status is sync
        return None

    def json(self) -> dict:
        return self._payload


class _FakePollClient:
    """Minimal async stand-in for httpx.AsyncClient covering only GET poll."""

    def __init__(self, bodies: list[dict]):
        self._bodies = list(bodies)
        self.gets = 0

    async def get(self, _url: str) -> _FakeResponse:
        self.gets += 1
        body = self._bodies[min(self.gets - 1, len(self._bodies) - 1)]
        return _FakeResponse(body)


async def _no_sleep(_seconds: float) -> None:
    return None


# ---------------------------------------------------------------------------
# IC§3.3 — poll result routing: succeeded/failed/validation → typed outcome.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_poll_succeeded_returns_validated_result():
    client = _FakePollClient([{"status": "succeeded", "result": VALID_RESULT}])
    out = await scrape_client.poll_imo_job("job-1", client=client, sleep=_no_sleep)
    assert isinstance(out, scrape_client.IMOResolverResult)
    assert out.imo == "9811000"
    assert out.vessel_name == "EVER GIVEN"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error_code",
    ["captcha", "not_found", "ambiguous_name", "timeout", "login_required"],
)
async def test_poll_failed_maps_error_code_1to1(error_code):
    """IC§3.3 error_code ↔ onboarding_error — pass-through, no remap."""
    client = _FakePollClient([{"status": "failed", "error_code": error_code}])
    out = await scrape_client.poll_imo_job("job-1", client=client, sleep=_no_sleep)
    assert isinstance(out, scrape_client.ScrapeError)
    assert out.error_code == error_code


@pytest.mark.asyncio
async def test_poll_failed_unknown_error_code_coerced_to_timeout():
    client = _FakePollClient([{"status": "failed", "error_code": "wormhole"}])
    out = await scrape_client.poll_imo_job("job-1", client=client, sleep=_no_sleep)
    assert isinstance(out, scrape_client.ScrapeError)
    assert out.error_code == "timeout"


@pytest.mark.asyncio
async def test_poll_succeeded_with_bad_imo_becomes_not_found_not_fabricated():
    """A Node result that slips a 6-digit imo must NOT be trusted — validation
    failure maps to ScrapeError('not_found'), never a fabricated identity."""
    bad = {**VALID_RESULT, "imo": "981100"}  # 6 digits
    client = _FakePollClient([{"status": "succeeded", "result": bad}])
    out = await scrape_client.poll_imo_job("job-1", client=client, sleep=_no_sleep)
    assert isinstance(out, scrape_client.ScrapeError)
    assert out.error_code == "not_found"


@pytest.mark.asyncio
async def test_poll_running_then_succeeded_polls_again():
    client = _FakePollClient(
        [{"status": "running"}, {"status": "succeeded", "result": VALID_RESULT}]
    )
    out = await scrape_client.poll_imo_job("job-1", client=client, sleep=_no_sleep)
    assert isinstance(out, scrape_client.IMOResolverResult)
    assert client.gets == 2  # polled twice: running → succeeded


@pytest.mark.asyncio
async def test_poll_timeout_when_never_terminal():
    client = _FakePollClient([{"status": "running"}])
    out = await scrape_client.poll_imo_job(
        "job-1", client=client, sleep=_no_sleep, poll_interval_s=1.0, timeout_s=3.0
    )
    assert isinstance(out, scrape_client.ScrapeError)
    assert out.error_code == "timeout"


# ---------------------------------------------------------------------------
# §6.7a fallback — Python writes leg manual_required + onboarding_error.
# ---------------------------------------------------------------------------


class _FakeSignal:
    def __init__(self) -> None:
        self.set_called = 0

    def set(self) -> None:
        self.set_called += 1


@pytest.mark.asyncio
async def test_scrape_error_routes_to_mark_leg_manual_fallback(db):
    """failed + error_code → leg.onboarding_status='manual_required' with the
    error_code recorded, mirrored to the active shipment (Spec §6.7a). This is
    the Python write path — Node never touches Postgres (IC§0.1)."""
    factory = db
    async with factory() as session:
        async with session.begin():
            ship = Shipment(
                bl_number="MAEU123456789",
                container_no="MSKU0000000",
                incoterm="FOB",
                shipment_direction="import",
                carrier="MAERSK",
                vessel_name="EVER GIVEN",
                pol="VNSGN",
                pod="NLRTM",
                monitoring_mode="auto_email",
                onboarding_status="pending",
            )
            session.add(ship)
            await session.flush()
            leg = ShipmentLeg(
                shipment_id=ship.id,
                leg_no=1,
                vessel_name="EVER GIVEN",
                voyage_no="V123",
                pol="VNSGN",
                pod="NLRTM",
                onboarding_status="pending",
                is_active_leg=True,
            )
            session.add(leg)
            await session.flush()
            leg_id = leg.id
            ship_id = ship.id

        # Simulate the resolver terminal failure surfaced by poll.
        err = scrape_client.ScrapeError("ambiguous_name")

        fake_signal = _FakeSignal()
        broadcasts: list[tuple[int, dict]] = []

        async def fake_broadcast(shipment_id: int, data: dict) -> None:
            broadcasts.append((shipment_id, data))

        # Exactly the wiring app/api/shipments.py uses on ScrapeError.
        with warnings.catch_warnings():
            warnings.simplefilter("error")  # any RuntimeWarning -> test failure
            await mark_leg_manual(
                session,
                leg_id,
                err.error_code,
                resubscribe_signal=fake_signal,  # type: ignore[arg-type]
                broadcast=fake_broadcast,
            )

    # Re-read in a fresh session to confirm the committed write.
    async with factory() as session:
        leg = await session.get(ShipmentLeg, leg_id)
        ship = await session.get(Shipment, ship_id)
        assert leg is not None and ship is not None
        assert leg.onboarding_status == "manual_required"
        assert leg.onboarding_error == "ambiguous_name"
        # Active leg mirrors down to shipments (§6.7a mirror rule).
        assert ship.onboarding_status == "manual_required"
        assert ship.onboarding_error == "ambiguous_name"

    assert fake_signal.set_called == 1
    assert broadcasts == [
        (
            ship_id,
            {
                "onboarding_status": "manual_required",
                "onboarding_error": "ambiguous_name",
                "leg_id": leg_id,
            },
        )
    ]
