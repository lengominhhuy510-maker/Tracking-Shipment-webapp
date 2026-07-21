from datetime import datetime
from typing import Any


def _high_tide_times(extremes: list[dict[str, Any]]) -> list[datetime]:
    highs: list[datetime] = []
    for extreme in extremes:
        tide_type = extreme.get("type", "high")
        if not isinstance(tide_type, str) or "high" not in tide_type.lower():
            continue
        value = extreme.get("time")
        if not isinstance(value, str):
            continue
        try:
            highs.append(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            continue
    return highs


def nearest_high_tide(
    eta: datetime | None, extremes: list[dict[str, Any]]
) -> datetime | None:
    if eta is None or not extremes:
        return None
    highs = _high_tide_times(extremes)
    if not highs:
        return None
    return min(highs, key=lambda tide: abs((eta - tide).total_seconds()))


def eta_in_tidal_window(
    eta: datetime | None,
    extremes: list[dict[str, Any]],
    window_hours: float,
) -> bool | None:
    if eta is None or not extremes or window_hours < 0:
        return None

    high_tides = _high_tide_times(extremes)
    if not high_tides:
        return None

    window_seconds = window_hours * 3600
    return any(abs((eta - tide).total_seconds()) <= window_seconds for tide in high_tides)
