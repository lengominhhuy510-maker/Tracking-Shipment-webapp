"""QA-02 — ETA Engine (REPORT-ONLY, evidence-based).

Truth:
  - Spec §6.3 — guard 3b (step 3b), wrap-around 0/360 (step 6), guard 9b
    (step 9b), deviation sign + threshold (steps 10-11).
  - IC§5.1 — recompute_eta contract + skipped_reason enum
    {sog_below_min, no_valid_atd, no_position, no_pod_coords}.
  - IC§7 — env coefficients + defaults (SOG_MIN_KNOT=1.5,
    ETA_DEVIATION_THRESHOLD_PCT=10, CURRENT_AGAINST_THRESHOLD_KN=1.0/PCT=8,
    WIND_AGAINST_THRESHOLD_KN=25/PCT=5, ETA_RECOMPUTE_DEBOUNCE_SECONDS=60,
    ETA_HISTORY_MIN_DELTA_MINUTES=15).

Two surfaces:
  A. Pure engine — app.core.eta_engine.compute_eta / _angular_delta
     (items 1-6: skipped_reason, deviation sign, wrap-around, guard 9b/3b).
  B. Service glue — app.services.eta_service.recompute_eta
     (item 3 alert-threshold >=, item 6 keep-eta_current, item 7 debounce +
     eta_history min-delta).

No app code is modified. freezegun is NOT installed → the service clock
(`datetime.now(UTC)`) is pinned by monkeypatching `eta_service.datetime` with a
frozen-clock object exposing `.now(tz)`. The outer boundary `geocode_port`
(POD lat/lon) and the WS `broadcast_*` coroutines are the only mocks; async
mocks use real `async def` recorders so the awaited call path is exercised.
All coefficients are read from `settings` (IC§7), never hardcoded, so an env
override would move the assertions with the code.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.core.eta_engine import (
    EnvInput,
    ETAComputeResult,
    ETAInput,
    _angular_delta,
    compute_eta,
)
from app.core.geo import haversine_nm
from app.db.base import Base
from app.db.models import EtaHistory, Shipment
from app.services import eta_service

UTC = timezone.utc
NOW = datetime(2026, 7, 21, 12, 0, 0, tzinfo=UTC)

# Equator geometry: (0,0)->(0,1) == ~60.04 nm (1° of longitude on equator).
POS = {"current_lat": 0.0, "current_lon": 0.0}
POD = {"pod_lat": 0.0, "pod_lon": 1.0}
DIST_NM = haversine_nm(0.0, 0.0, 0.0, 1.0)


def _input(**overrides) -> ETAInput:
    base = dict(
        now=NOW,
        **POS,
        **POD,
        sog_window=[10.0],
        cog=90.0,
        eta_original=NOW + timedelta(hours=5),  # planned arrival
        atd=NOW - timedelta(hours=5),  # departed → planned window 10h, eta_original>atd
        env=None,
    )
    base.update(overrides)
    return ETAInput(**base)


# =========================================================================== #
# ITEM 1 — four skipped_reason values, each its OWN case (IC§5.1 enum)
# =========================================================================== #
def test_item1_skipped_reason_no_position():
    """current_lat/lon null → 'no_position', nothing computed (IC§5.1)."""
    r = compute_eta(_input(current_lat=None, current_lon=None))
    assert r.skipped_reason == "no_position"
    assert r.eta_tier1 is None and r.eta_tier2 is None
    assert r.deviation_pct is None


def test_item1_skipped_reason_no_pod_coords():
    """POD lat/lon null → 'no_pod_coords', skip recompute (IC§5.1)."""
    r = compute_eta(_input(pod_lat=None, pod_lon=None))
    assert r.skipped_reason == "no_pod_coords"
    assert r.eta_tier1 is None and r.eta_tier2 is None


def test_item1_skipped_reason_sog_below_min():
    """avg SOG < SOG_MIN_KNOT → 'sog_below_min' (guard 3b, §6.3)."""
    below = settings.SOG_MIN_KNOT - 0.5
    r = compute_eta(_input(sog_window=[below, below]))
    assert r.skipped_reason == "sog_below_min"
    assert r.eta_tier1 is None and r.eta_tier2 is None
    assert r.avg_sog_kn == pytest.approx(below)


def test_item1_skipped_reason_no_valid_atd():
    """atd null → 'no_valid_atd' (guard 9b) — distinct from the other three."""
    r = compute_eta(_input(atd=None))
    assert r.skipped_reason == "no_valid_atd"


def test_item1_four_reasons_are_distinct_not_merged():
    """The 4 conditions map to 4 different strings — none collapsed together."""
    reasons = {
        compute_eta(_input(current_lat=None, current_lon=None)).skipped_reason,
        compute_eta(_input(pod_lat=None, pod_lon=None)).skipped_reason,
        compute_eta(_input(sog_window=[0.1])).skipped_reason,
        compute_eta(_input(atd=None)).skipped_reason,
    }
    assert reasons == {"no_position", "no_pod_coords", "sog_below_min", "no_valid_atd"}


# =========================================================================== #
# ITEM 2 — deviation sign (§6.3 step 10): positive = LATE, negative = EARLY,
#          computed in epoch/UTC seconds.
# =========================================================================== #
def test_item2_positive_deviation_means_late():
    """Slow SOG → eta_tier2 later than eta_original → deviation > 0 (LATE)."""
    r = compute_eta(_input(sog_window=[5.0]))  # 5kn over ~60nm ≈ 12h vs planned 5h
    assert r.skipped_reason is None
    assert r.eta_tier2 > NOW + timedelta(hours=5), "ETA slipped past planned arrival"
    assert r.deviation_pct > 0


def test_item2_negative_deviation_means_early():
    """Fast SOG → eta_tier2 earlier than eta_original → deviation < 0 (EARLY)."""
    r = compute_eta(_input(sog_window=[30.0]))  # ~2h vs planned 5h
    assert r.deviation_pct < 0


def test_item2_deviation_is_epoch_utc_ratio():
    """deviation_pct == 100*(eta_tier2−eta_original)/(eta_original−atd), all in
    epoch seconds via total_seconds() (§6.3/IC§15)."""
    r = compute_eta(_input(sog_window=[5.0]))
    eta_original = NOW + timedelta(hours=5)
    atd = NOW - timedelta(hours=5)
    planned_s = (eta_original - atd).total_seconds()
    delta_s = (r.eta_tier2 - eta_original).total_seconds()
    assert r.deviation_pct == pytest.approx(100.0 * delta_s / planned_s)


# =========================================================================== #
# ITEM 3 — threshold boundary (§6.3 step 11): |deviation_pct| == threshold
#          fires alert (>= not >); BOTH late and early past threshold alert.
#          This is a SERVICE decision (eta_service line ~172), isolated by
#          stubbing the pure engine result to hit the knife-edge exactly.
# =========================================================================== #
async def test_item3_alert_fires_when_abs_equals_threshold(service_env):
    """deviation == +threshold → alert MUST fire (proves >=, not >)."""
    sid, calls, set_result = service_env
    set_result(_crafted(deviation_pct=settings.ETA_DEVIATION_THRESHOLD_PCT))
    async with _factory() as s:
        await eta_service.recompute_eta(s, sid)
    assert len(calls["deviation"]) == 1, "boundary '==' must alert (>= semantics)"


async def test_item3_alert_fires_for_early_past_threshold(service_env):
    """deviation == −threshold (EARLY) → alert fires by ABSOLUTE value."""
    sid, calls, set_result = service_env
    set_result(_crafted(deviation_pct=-settings.ETA_DEVIATION_THRESHOLD_PCT))
    async with _factory() as s:
        await eta_service.recompute_eta(s, sid)
    assert len(calls["deviation"]) == 1, "early deviation past threshold must alert"


async def test_item3_no_alert_just_below_threshold(service_env):
    """|deviation| just below threshold → NO alert (confirms boundary is the cut)."""
    sid, calls, set_result = service_env
    set_result(_crafted(deviation_pct=settings.ETA_DEVIATION_THRESHOLD_PCT - 0.001))
    async with _factory() as s:
        await eta_service.recompute_eta(s, sid)
    assert calls["deviation"] == []


# =========================================================================== #
# ITEM 4 — wrap-around 0/360 (§6.3 step 6, MANDATORY v0.9.12):
#          delta = min(|a−b|, 360−|a−b|). COG 359 vs current 1 → 2°, NOT 358°.
#          Test BOTH sides of the seam.
# =========================================================================== #
def test_item4_angular_delta_wraps_both_seam_sides():
    """Direct helper check: seam distance is 2°, not 358°, either order."""
    assert _angular_delta(359.0, 1.0) == pytest.approx(2.0)
    assert _angular_delta(1.0, 359.0) == pytest.approx(2.0)
    assert _angular_delta(359.0, 179.0) == pytest.approx(180.0)


def test_item4_wraparound_seam_classified_with_flow():
    """COG 359 vs current 1 → delta 2° → WITH flow → no current penalty."""
    env = EnvInput(current_speed_kn=2.0, current_direction_deg=1.0)
    r = compute_eta(_input(cog=359.0, env=env))
    assert r.factors_applied == []
    assert r.eta_tier2 == r.eta_tier1


def test_item4_wraparound_other_seam_side_with_flow():
    """Mirror side: COG 1 vs current 359 → delta 2° → WITH flow, no penalty."""
    env = EnvInput(current_speed_kn=2.0, current_direction_deg=359.0)
    r = compute_eta(_input(cog=1.0, env=env))
    assert r.factors_applied == []


def test_item4_naive_diff_would_misclassify_against():
    """Sanity: a真-against pair (delta 180°) DOES penalise → proves the seam
    cases above are not just 'penalty never applies'."""
    env = EnvInput(current_speed_kn=2.0, current_direction_deg=179.0)
    r = compute_eta(_input(cog=359.0, env=env))
    assert r.factors_applied == [f"current_against_-{settings.CURRENT_AGAINST_PENALTY_PCT:g}%"]


# =========================================================================== #
# ITEM 5 — guard 9b (§6.3 step 9b): atd null AND/OR eta_original <= atd →
#          NO div-by-zero/crash, ETA still computed, deviation hidden.
# =========================================================================== #
def test_item5_guard9b_atd_null_no_crash_eta_computed():
    r = compute_eta(_input(atd=None))
    assert r.skipped_reason == "no_valid_atd"
    assert r.eta_tier1 is not None and r.eta_tier2 is not None
    assert r.deviation_pct is None


def test_item5_guard9b_eta_original_le_atd_no_div_zero():
    """eta_original == atd would make denominator 0 → guard must skip step 10."""
    r = compute_eta(_input(eta_original=NOW, atd=NOW))  # denominator (eta-atd)=0
    assert r.skipped_reason == "no_valid_atd"
    assert r.eta_tier2 is not None
    assert r.deviation_pct is None


def test_item5_guard9b_eta_original_before_atd_hidden():
    """Dirty manual data eta_original < atd → deviation hidden, ETA still shown."""
    r = compute_eta(_input(eta_original=NOW - timedelta(hours=6)))
    assert r.skipped_reason == "no_valid_atd"
    assert r.deviation_pct is None


# =========================================================================== #
# ITEM 6 — guard 3b (§6.3 step 3b): avg SOG < SOG_MIN_KNOT → keep eta_current
#          AND previous alert state, skip steps 4-11.
# =========================================================================== #
def test_item6_guard3b_engine_skips_steps_4_to_11():
    """Engine side: no tier1/tier2, no deviation; distance (step 2) still known."""
    r = compute_eta(_input(sog_window=[0.4, 0.6]))
    assert r.skipped_reason == "sog_below_min"
    assert r.eta_tier1 is None and r.eta_tier2 is None
    assert r.deviation_pct is None
    assert r.distance_remaining_nm == pytest.approx(DIST_NM, rel=0.01)


def test_item6_guard3b_empty_window_is_below_min():
    r = compute_eta(_input(sog_window=[]))
    assert r.skipped_reason == "sog_below_min"
    assert r.eta_tier1 is None


async def test_item6_guard3b_service_keeps_eta_current_and_no_alert(service_env_real):
    """Service side: SOG below min → eta_current UNCHANGED, no eta_history row,
    no deviation alert broadcast (previous alert state preserved)."""
    sid, calls, clock, set_position = service_env_real
    kept = datetime(2026, 1, 1, 0, 0)  # naive UTC (SQLite round-trip strips tz)
    async with _factory() as s:
        ship = await s.get(Shipment, sid)
        ship.eta_current = kept
        ship.current_sog = settings.SOG_MIN_KNOT - 1.0  # below guard 3b
        ship.current_lat, ship.current_lon = 0.0, 0.5
        await s.commit()
    async with _factory() as s:
        r = await eta_service.recompute_eta(s, sid)
    assert r.skipped_reason == "sog_below_min"
    async with _factory() as s:
        ship = await s.get(Shipment, sid)
        rows = (await s.execute(select(EtaHistory).where(EtaHistory.shipment_id == sid))).all()
    assert ship.eta_current == kept, "guard 3b must keep previous eta_current"
    assert rows == [], "guard 3b must not write eta_history"
    assert calls["deviation"] == [], "guard 3b must not fire deviation alert"


# =========================================================================== #
# ITEM 7 — debounce (< ETA_RECOMPUTE_DEBOUNCE_SECONDS → skip) + eta_history
#          min-delta (ETA shift < ETA_HISTORY_MIN_DELTA_MINUTES → no new row).
# =========================================================================== #
async def test_item7_debounce_second_call_within_window_skips(service_env_real):
    """Two calls closer than ETA_RECOMPUTE_DEBOUNCE_SECONDS → 2nd returns None."""
    sid, calls, clock, set_position = service_env_real
    await set_position(lat=0.0, lon=0.5, sog=10.0)
    async with _factory() as s:
        first = await eta_service.recompute_eta(s, sid)
    clock.advance(settings.ETA_RECOMPUTE_DEBOUNCE_SECONDS - 1)  # still inside window
    async with _factory() as s:
        second = await eta_service.recompute_eta(s, sid)
    assert first is not None and first.skipped_reason is None
    assert second is None, "debounce must skip the 2nd call inside the window"


async def test_item7_debounce_releases_after_window(service_env_real):
    """Past the debounce window → recompute runs again (proves it was debounce,
    not a hard stop)."""
    sid, calls, clock, set_position = service_env_real
    await set_position(lat=0.0, lon=0.5, sog=10.0)
    async with _factory() as s:
        await eta_service.recompute_eta(s, sid)
    clock.advance(settings.ETA_RECOMPUTE_DEBOUNCE_SECONDS + 1)
    async with _factory() as s:
        again = await eta_service.recompute_eta(s, sid)
    assert again is not None and again.skipped_reason is None


async def test_item7_history_small_shift_no_new_row(service_env_real):
    """ETA shift < ETA_HISTORY_MIN_DELTA_MINUTES between recomputes → the 2nd
    recompute writes NO extra eta_history row (only the 1st row persists)."""
    sid, calls, clock, set_position = service_env_real
    await set_position(lat=0.0, lon=0.5, sog=10.0)
    async with _factory() as s:
        await eta_service.recompute_eta(s, sid)  # writes row #1
    # advance only past debounce; ETA moves ~ that many seconds (<< 15 min)
    clock.advance(settings.ETA_RECOMPUTE_DEBOUNCE_SECONDS + 1)
    async with _factory() as s:
        await eta_service.recompute_eta(s, sid)  # ETA shifted ~61s < 15 min
    async with _factory() as s:
        rows = (await s.execute(select(EtaHistory).where(EtaHistory.shipment_id == sid))).all()
    assert len(rows) == 1, "sub-threshold ETA shift must not add an eta_history row"


async def test_item7_history_large_shift_writes_new_row(service_env_real):
    """Positive control: ETA shift >> min-delta → a new eta_history row IS added."""
    sid, calls, clock, set_position = service_env_real
    await set_position(lat=0.0, lon=0.5, sog=10.0)
    async with _factory() as s:
        await eta_service.recompute_eta(s, sid)  # row #1, dist ~30nm
    clock.advance(settings.ETA_RECOMPUTE_DEBOUNCE_SECONDS + 1)
    await set_position(lat=0.0, lon=3.0, sog=10.0)  # dist ~180nm → ETA jumps ~15h
    async with _factory() as s:
        await eta_service.recompute_eta(s, sid)
    async with _factory() as s:
        rows = (await s.execute(select(EtaHistory).where(EtaHistory.shipment_id == sid))).all()
    assert len(rows) == 2, "supra-threshold ETA shift must add a new eta_history row"


# =========================================================================== #
# Service harness — in-memory SQLite, frozen clock, mocked outer boundary.
# =========================================================================== #
# NOTE: sqlite+aiosqlite drops tzinfo on round-trip, so DB-read datetimes come
# back NAIVE. Production is Postgres (uniformly tz-aware). To keep the harness
# self-consistent (and avoid a false tz TypeError that would never occur on
# Postgres), the frozen clock + seeded timestamps are all NAIVE UTC here.
_factory: async_sessionmaker | None = None
NOW_N = NOW.replace(tzinfo=None)  # naive mirror for the SQLite service harness


class _FrozenClock:
    """Stand-in for `datetime` inside eta_service: only `.now(tz)` is called."""

    def __init__(self, t: datetime) -> None:
        self.t = t

    def now(self, tz=None) -> datetime:  # noqa: ARG002 — signature parity
        return self.t

    def advance(self, seconds: float) -> None:
        self.t = self.t + timedelta(seconds=seconds)


def _crafted(deviation_pct: float) -> ETAComputeResult:
    """A full tier-2 result so the service proceeds to the alert decision, with a
    precise deviation_pct to probe the >= boundary."""
    eta = NOW_N + timedelta(hours=3)
    return ETAComputeResult(
        eta_tier1=eta,
        eta_tier2=eta,
        avg_sog_kn=10.0,
        distance_remaining_nm=50.0,  # > ARRIVAL_RADIUS so no arrival suggestion
        factors_applied=[],
        skipped_reason=None,
        deviation_pct=deviation_pct,
    )


async def _seed_shipment() -> int:
    ship = Shipment(
        bl_number="BL-QA02",
        container_no="CSQU3054383",
        incoterm="FOB",
        shipment_direction="import",
        monitoring_mode="auto_email",
        carrier="Maersk",
        vessel_name="QA VESSEL",
        pol="SGSIN Singapore",
        pod="VNCLI Cat Lai",
        status="on_sea",
        onboarding_status="resolved",
        current_lat=0.0,
        current_lon=0.5,
        current_sog=10.0,
        current_cog=90.0,
        atd=NOW_N - timedelta(hours=10),
        eta_original=NOW_N + timedelta(hours=10),
        eta_current=NOW_N,
    )
    async with _factory() as s:
        s.add(ship)
        await s.commit()
        return ship.id


@pytest.fixture
async def _db(monkeypatch):
    global _factory
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    _factory = async_sessionmaker(engine, expire_on_commit=False)

    # Outer boundary: POD geocode → fixed coords (0,0). No CSV, deterministic dist.
    monkeypatch.setattr(eta_service, "geocode_port", lambda pod: (0.0, 0.0, "VNCLI"))

    # WS broadcasts are the only other boundary — real async recorders.
    calls: dict[str, list] = {"deviation": [], "eta": [], "arrival": []}

    async def rec_dev(sid, data):
        calls["deviation"].append((sid, data))

    async def rec_eta(sid, data):
        calls["eta"].append((sid, data))

    async def rec_arr(sid, data):
        calls["arrival"].append((sid, data))

    monkeypatch.setattr(eta_service, "broadcast_deviation_alert", rec_dev)
    monkeypatch.setattr(eta_service, "broadcast_eta_update", rec_eta)
    monkeypatch.setattr(eta_service, "broadcast_status_change_suggested", rec_arr)

    eta_service.reset_state()
    yield calls
    eta_service.reset_state()
    _factory = None
    await engine.dispose()


@pytest.fixture
async def service_env(_db, monkeypatch):
    """Item 3: stub the pure engine so deviation_pct lands exactly on the
    boundary; the code under test is the service's `>=` alert decision."""
    calls = _db
    sid = await _seed_shipment()

    def set_result(result: ETAComputeResult):
        monkeypatch.setattr(eta_service, "compute_eta", lambda state: result)
        eta_service.reset_state()  # clear debounce so each sub-case runs

    return sid, calls, set_result


@pytest.fixture
async def service_env_real(_db, monkeypatch):
    """Items 6-7: real engine, frozen clock, awaitable position/SOG setter."""
    calls = _db
    sid = await _seed_shipment()
    clock = _FrozenClock(NOW_N)
    monkeypatch.setattr(eta_service, "datetime", clock)

    async def set_position(lat: float, lon: float, sog: float) -> None:
        async with _factory() as s:
            ship = await s.get(Shipment, sid)
            ship.current_lat, ship.current_lon, ship.current_sog = lat, lon, sog
            await s.commit()

    return sid, calls, clock, set_position
