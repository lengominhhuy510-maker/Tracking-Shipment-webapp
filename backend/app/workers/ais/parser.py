"""Parse/validate a single raw aisstream.io message into an internal AisPosition.

Pure logic — no I/O, fully offline-testable (TDD). AIS wire semantics:
- SOG 102.3 (raw 1023) = speed unavailable → None.
- COG 360.0 (raw 3600) = course unavailable → None.
- Latitude 91 / Longitude 181 = position unavailable → whole message skipped.
Only ``PositionReport`` messages carry coordinates; anything else → None.
"""

import re
from datetime import datetime

from pydantic import BaseModel

_SOG_UNAVAILABLE = 102.3
_COG_UNAVAILABLE = 360.0
_FRACTION_RE = re.compile(r"\.(\d+)")


class AisPosition(BaseModel):
    """Normalized position extracted from one PositionReport."""

    mmsi: str
    lat: float
    lon: float
    sog: float | None
    cog: float | None
    timestamp: datetime


def _parse_time_utc(raw: str) -> datetime | None:
    """Parse aisstream ``time_utc`` (e.g. ``2026-07-21 02:10:04.000000000 +0000 UTC``).

    Nanosecond precision is truncated to microseconds (strptime %f caps at 6 digits).
    """
    cleaned = raw.replace(" UTC", "").strip()
    cleaned = _FRACTION_RE.sub(lambda m: "." + m.group(1)[:6], cleaned)
    for fmt in ("%Y-%m-%d %H:%M:%S.%f %z", "%Y-%m-%d %H:%M:%S %z"):
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    return None


def parse_ais_message(msg: dict) -> AisPosition | None:
    """Return an AisPosition, or None if the message is not a usable PositionReport."""
    report = msg.get("Message", {}).get("PositionReport")
    if not isinstance(report, dict):
        return None

    meta = msg.get("MetaData", {})
    mmsi_raw = meta.get("MMSI") or report.get("UserID")
    if mmsi_raw is None:
        return None

    lat = report.get("Latitude")
    lon = report.get("Longitude")
    if lat is None or lon is None:
        return None
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        return None

    sog = report.get("Sog")
    if sog is None or sog >= _SOG_UNAVAILABLE:
        sog = None
    cog = report.get("Cog")
    if cog is None or cog >= _COG_UNAVAILABLE:
        cog = None

    timestamp = _parse_time_utc(str(meta.get("time_utc", "")))
    if timestamp is None:
        return None

    return AisPosition(
        mmsi=str(mmsi_raw),
        lat=lat,
        lon=lon,
        sog=sog,
        cog=cog,
        timestamp=timestamp,
    )
