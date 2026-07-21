"""TDD tests for app.core.eta_engine (Spec §6.3 two-tier rule-based ETA, IC§5.1).

Pure-function tests — no DB. Covers tier 1 kinematics, guard 3b (sog_below_min),
guard 9b (no_valid_atd), missing-input skips (no_position / no_pod_coords),
tier 2 env adjustments incl. 0/360 wrap-around, and deviation sign convention
(positive = late, negative = early).
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.core.eta_engine import EnvInput, ETAInput, compute_eta

NOW = datetime(2026, 7, 21, 12, 0, 0, tzinfo=UTC)

# Equator geometry: (0,0) -> (0,1) is 60.04 nm (1 degree of longitude).
POS = {"current_lat": 0.0, "current_lon": 0.0}
POD = {"pod_lat": 0.0, "pod_lon": 1.0}
DIST_NM = 60.04


def _input(**overrides) -> ETAInput:
    base = dict(
        now=NOW,
        **POS,
        **POD,
        sog_window=[10.0],
        cog=90.0,
        eta_original=NOW + timedelta(hours=5),
        atd=NOW - timedelta(hours=5),
        env=None,
    )
    base.update(overrides)
    return ETAInput(**base)


# ---------- skip guards ----------


def test_no_position_skips_recompute():
    result = compute_eta(_input(current_lat=None, current_lon=None))
    assert result.skipped_reason == "no_position"
    assert result.eta_tier1 is None
    assert result.eta_tier2 is None


def test_no_pod_coords_skips_recompute():
    result = compute_eta(_input(pod_lat=None, pod_lon=None))
    assert result.skipped_reason == "no_pod_coords"
    assert result.eta_tier1 is None
    assert result.eta_tier2 is None


def test_sog_below_min_skips_eta_and_deviation():
    result = compute_eta(_input(sog_window=[0.4, 0.6]))
    assert result.skipped_reason == "sog_below_min"
    assert result.eta_tier1 is None
    assert result.eta_tier2 is None
    assert result.deviation_pct is None
    # distance (step 2) is still computed before guard 3b
    assert result.distance_remaining_nm == pytest.approx(DIST_NM, rel=0.01)
    assert result.avg_sog_kn == pytest.approx(0.5)


def test_empty_sog_window_treated_as_sog_below_min():
    result = compute_eta(_input(sog_window=[]))
    assert result.skipped_reason == "sog_below_min"
    assert result.eta_tier1 is None


def test_no_valid_atd_when_atd_null_still_computes_eta():
    result = compute_eta(_input(atd=None))
    assert result.skipped_reason == "no_valid_atd"
    assert result.eta_tier1 is not None
    assert result.eta_tier2 is not None
    assert result.deviation_pct is None


def test_no_valid_atd_when_eta_original_not_after_atd():
    result = compute_eta(_input(eta_original=NOW - timedelta(hours=6)))
    assert result.skipped_reason == "no_valid_atd"
    assert result.eta_tier2 is not None
    assert result.deviation_pct is None


# ---------- tier 1 kinematics ----------


def test_tier1_eta_is_now_plus_distance_over_avg_sog():
    result = compute_eta(_input())
    assert result.skipped_reason is None
    expected = NOW + timedelta(hours=DIST_NM / 10.0)
    assert abs((result.eta_tier1 - expected).total_seconds()) < 60
    assert result.avg_sog_kn == pytest.approx(10.0)
    assert result.distance_remaining_nm == pytest.approx(DIST_NM, rel=0.01)


def test_avg_sog_is_mean_of_window():
    result = compute_eta(_input(sog_window=[8.0, 10.0, 12.0]))
    assert result.avg_sog_kn == pytest.approx(10.0)


def test_tier2_equals_tier1_without_env_data():
    result = compute_eta(_input(env=None))
    assert result.eta_tier2 == result.eta_tier1
    assert result.factors_applied == []


# ---------- tier 2 adjustments ----------


def test_current_against_applies_penalty():
    env = EnvInput(current_speed_kn=2.0, current_direction_deg=270.0)  # cog=90 → head-on
    result = compute_eta(_input(env=env))
    assert result.factors_applied == ["current_against_-8%"]
    effective = 10.0 * (1 - 0.08)
    expected = NOW + timedelta(hours=DIST_NM / effective)
    assert abs((result.eta_tier2 - expected).total_seconds()) < 60
    assert result.eta_tier2 > result.eta_tier1


def test_current_with_flow_no_penalty():
    env = EnvInput(current_speed_kn=2.0, current_direction_deg=90.0)  # same as cog
    result = compute_eta(_input(env=env))
    assert result.factors_applied == []
    assert result.eta_tier2 == result.eta_tier1


def test_current_against_below_threshold_no_penalty():
    env = EnvInput(current_speed_kn=0.5, current_direction_deg=270.0)
    result = compute_eta(_input(env=env))
    assert result.factors_applied == []


def test_wraparound_0_360_classifies_with_flow():
    # cog 359 vs current 1 → delta 2° (with flow), NOT 358° (against)
    env = EnvInput(current_speed_kn=2.0, current_direction_deg=1.0)
    result = compute_eta(_input(cog=359.0, env=env))
    assert result.factors_applied == []
    assert result.eta_tier2 == result.eta_tier1


def test_wraparound_0_360_classifies_against():
    # cog 359 vs current 179 → delta 180 → against
    env = EnvInput(current_speed_kn=2.0, current_direction_deg=179.0)
    result = compute_eta(_input(cog=359.0, env=env))
    assert result.factors_applied == ["current_against_-8%"]


def test_wind_above_threshold_applies_penalty():
    env = EnvInput(wind_speed_kn=30.0)
    result = compute_eta(_input(env=env))
    assert result.factors_applied == ["wind_against_-5%"]


def test_combined_current_and_wind_penalties():
    env = EnvInput(wind_speed_kn=30.0, current_speed_kn=2.0, current_direction_deg=270.0)
    result = compute_eta(_input(env=env))
    assert result.factors_applied == ["current_against_-8%", "wind_against_-5%"]
    effective = 10.0 * (1 - 0.08 - 0.05)
    expected = NOW + timedelta(hours=DIST_NM / effective)
    assert abs((result.eta_tier2 - expected).total_seconds()) < 60


def test_current_without_cog_no_classification():
    env = EnvInput(current_speed_kn=2.0, current_direction_deg=270.0)
    result = compute_eta(_input(cog=None, env=env))
    assert result.factors_applied == []


# ---------- deviation (steps 9b-10) ----------


def test_deviation_positive_means_late():
    # planned: atd NOW-5h, eta_original NOW+5h (planned duration 10h)
    # slow sog 5kn → eta_tier2 ≈ NOW+12h → deviation = 7h/10h = +70%
    result = compute_eta(_input(sog_window=[5.0]))
    assert result.skipped_reason is None
    planned_s = (NOW + timedelta(hours=5) - (NOW - timedelta(hours=5))).total_seconds()
    delta_s = (result.eta_tier2 - (NOW + timedelta(hours=5))).total_seconds()
    assert result.deviation_pct == pytest.approx(100 * delta_s / planned_s)
    assert result.deviation_pct > 0


def test_deviation_negative_means_early():
    # fast sog 30kn → eta_tier2 ≈ NOW+2h < eta_original NOW+5h → early
    result = compute_eta(_input(sog_window=[30.0]))
    assert result.deviation_pct < 0
