"""TDD tests for app.core.geo (haversine great-circle distance, nautical miles)."""

import pytest

from app.core.geo import haversine_nm

# Singapore anchorage vs Cát Lái (VNCLI) — known great-circle distance ~596 nm.
SGSIN = (1.2644, 103.8400)
VNCLI = (10.7560, 106.7500)


def test_haversine_sg_to_cat_lai_within_5pct():
    dist = haversine_nm(*SGSIN, *VNCLI)
    assert dist == pytest.approx(596, rel=0.05)


def test_haversine_zero_distance():
    assert haversine_nm(10.5, 107.0, 10.5, 107.0) == 0.0


def test_haversine_one_degree_longitude_at_equator():
    # 1 degree of longitude at the equator = 60 nm by definition (±0.5%).
    assert haversine_nm(0.0, 0.0, 0.0, 1.0) == pytest.approx(60.0, rel=0.005)


def test_haversine_symmetric():
    assert haversine_nm(*SGSIN, *VNCLI) == pytest.approx(haversine_nm(*VNCLI, *SGSIN))
