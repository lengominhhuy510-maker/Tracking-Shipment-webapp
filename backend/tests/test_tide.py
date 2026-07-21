from datetime import UTC, datetime, timedelta

from app.core.tide import eta_in_tidal_window, nearest_high_tide


BASE = datetime(2026, 7, 21, 12, tzinfo=UTC)
EXTREMES = [
    {"time": "2026-07-21T09:00:00+00:00", "height": 0.4, "type": "low"},
    {"time": "2026-07-21T12:00:00Z", "height": 2.2, "type": "high"},
]


def test_eta_inside_high_tide_window() -> None:
    assert eta_in_tidal_window(BASE + timedelta(hours=1), EXTREMES, 2) is True


def test_eta_on_window_boundary_is_inside() -> None:
    assert eta_in_tidal_window(BASE + timedelta(hours=2), EXTREMES, 2) is True


def test_eta_outside_high_tide_window() -> None:
    assert eta_in_tidal_window(BASE + timedelta(hours=3), EXTREMES, 2) is False


def test_low_tide_does_not_define_arrival_window() -> None:
    assert eta_in_tidal_window(BASE.replace(hour=9), EXTREMES, 1) is False


def test_untyped_extremes_are_accepted() -> None:
    extremes = [{"time": "2026-07-21T12:00:00Z", "height": 2.2}]
    assert eta_in_tidal_window(BASE, extremes, 1) is True


def test_missing_or_invalid_inputs_are_unknown() -> None:
    assert eta_in_tidal_window(None, EXTREMES, 2) is None
    assert eta_in_tidal_window(BASE, [], 2) is None
    assert eta_in_tidal_window(BASE, [{"time": "bad", "type": "high"}], 2) is None
    assert eta_in_tidal_window(BASE, EXTREMES, -1) is None


def test_nearest_high_tide_picks_closest_high() -> None:
    extremes = [
        {"time": "2026-07-21T06:00:00Z", "height": 2.0, "type": "high"},
        {"time": "2026-07-21T09:00:00Z", "height": 0.4, "type": "low"},
        {"time": "2026-07-21T18:00:00Z", "height": 2.1, "type": "high"},
    ]
    result = nearest_high_tide(BASE + timedelta(hours=4), extremes)

    assert result == datetime(2026, 7, 21, 18, tzinfo=UTC)


def test_nearest_high_tide_without_usable_data_is_none() -> None:
    assert nearest_high_tide(BASE, []) is None
    assert nearest_high_tide(None, EXTREMES) is None
    assert nearest_high_tide(BASE, [{"time": "bad"}]) is None
