"""Two-tier rule-based ETA engine (Spec §6.3, IC§5.1) — pure functions, no DB.

Tier 1: kinematics (haversine distance / sliding-mean SOG) with guard 3b
(SOG below minimum → keep previous ETA, skip everything).
Tier 2: environment adjustment via config coefficients (current/wind penalties,
0/360 wrap-around for current-vs-COG classification).
Deviation (steps 9b-10): only when atd is set AND eta_original > atd;
positive = late, negative = early, computed in epoch/UTC seconds.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.config import settings
from app.core.geo import haversine_nm


@dataclass(frozen=True)
class EnvInput:
    """Subset of env_conditions relevant to tier 2 (IC§0.2)."""

    wind_speed_kn: float | None = None
    wave_height_m: float | None = None
    current_speed_kn: float | None = None
    current_direction_deg: float | None = None


@dataclass(frozen=True)
class ETAInput:
    now: datetime
    current_lat: float | None
    current_lon: float | None
    pod_lat: float | None
    pod_lon: float | None
    sog_window: list[float] = field(default_factory=list)
    cog: float | None = None
    eta_original: datetime | None = None
    atd: datetime | None = None
    env: EnvInput | None = None


@dataclass(frozen=True)
class ETAComputeResult:
    """Breakdown per IC§5.1 — LLM/UI can see WHY the number came out."""

    eta_tier1: datetime | None = None
    eta_tier2: datetime | None = None
    avg_sog_kn: float | None = None
    distance_remaining_nm: float | None = None
    factors_applied: list[str] = field(default_factory=list)
    skipped_reason: str | None = None
    deviation_pct: float | None = None


def _angular_delta(a: float, b: float) -> float:
    """Smallest angle between two bearings, wrap-around 0/360 (v0.9.12)."""
    raw = abs(a - b) % 360.0
    return min(raw, 360.0 - raw)


def _tier2_factors(env: EnvInput | None, cog: float | None) -> list[str]:
    """Ordered penalty factors from env conditions (§6.3 steps 5-7)."""
    factors: list[str] = []
    if env is None:
        return factors
    if (
        env.current_speed_kn is not None
        and env.current_direction_deg is not None
        and cog is not None
        and env.current_speed_kn > settings.CURRENT_AGAINST_THRESHOLD_KN
        and _angular_delta(env.current_direction_deg, cog) > 90.0
    ):
        factors.append(f"current_against_-{settings.CURRENT_AGAINST_PENALTY_PCT:g}%")
    if env.wind_speed_kn is not None and env.wind_speed_kn > settings.WIND_AGAINST_THRESHOLD_KN:
        factors.append(f"wind_against_-{settings.WIND_AGAINST_PENALTY_PCT:g}%")
    return factors


def _penalty_pct(factor: str) -> float:
    if factor.startswith("current_against"):
        return settings.CURRENT_AGAINST_PENALTY_PCT
    return settings.WIND_AGAINST_PENALTY_PCT


def compute_eta(state: ETAInput) -> ETAComputeResult:
    if state.current_lat is None or state.current_lon is None:
        return ETAComputeResult(skipped_reason="no_position")
    if state.pod_lat is None or state.pod_lon is None:
        return ETAComputeResult(skipped_reason="no_pod_coords")

    distance_nm = haversine_nm(state.current_lat, state.current_lon, state.pod_lat, state.pod_lon)
    avg_sog = sum(state.sog_window) / len(state.sog_window) if state.sog_window else 0.0

    # Guard 3b: anchored/berthing vessel — keep previous ETA, skip steps 4-11.
    if avg_sog < settings.SOG_MIN_KNOT:
        return ETAComputeResult(
            avg_sog_kn=avg_sog,
            distance_remaining_nm=distance_nm,
            skipped_reason="sog_below_min",
        )

    eta_tier1 = state.now + timedelta(hours=distance_nm / avg_sog)

    factors = _tier2_factors(state.env, state.cog)
    effective_sog = avg_sog * (1 - sum(_penalty_pct(f) for f in factors) / 100.0)
    eta_tier2 = state.now + timedelta(hours=distance_nm / effective_sog)

    # Guard 9b: deviation only when atd is set AND eta_original > atd.
    if state.atd is None or state.eta_original is None or state.eta_original <= state.atd:
        return ETAComputeResult(
            eta_tier1=eta_tier1,
            eta_tier2=eta_tier2,
            avg_sog_kn=avg_sog,
            distance_remaining_nm=distance_nm,
            factors_applied=factors,
            skipped_reason="no_valid_atd",
        )

    planned_s = (state.eta_original - state.atd).total_seconds()
    delta_s = (eta_tier2 - state.eta_original).total_seconds()
    deviation_pct = 100.0 * delta_s / planned_s  # positive = late, negative = early

    return ETAComputeResult(
        eta_tier1=eta_tier1,
        eta_tier2=eta_tier2,
        avg_sog_kn=avg_sog,
        distance_remaining_nm=distance_nm,
        factors_applied=factors,
        deviation_pct=deviation_pct,
    )
