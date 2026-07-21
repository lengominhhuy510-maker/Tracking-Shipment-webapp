"""Great-circle geometry helpers (Spec §6.3 step 2 — haversine approximation).

Distances are great-circle, NOT real maritime route distances (v0.9.12 label).
"""

from math import asin, cos, radians, sin, sqrt

EARTH_RADIUS_NM = 3440.065


def haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in nautical miles."""
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_NM * asin(sqrt(a))
