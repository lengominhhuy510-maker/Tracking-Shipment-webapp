"""StormGlass tide-extremes client (free tier ~10 req/day; quota lives in tide_poll).

GET /v2/tide/extremes/point?lat=&lng= with the API key in the Authorization
header. Normalizes extremes + station metadata; MSL-relative heights kept as-is.
"""

import logging
from datetime import UTC, datetime, timedelta

import httpx
from pydantic import BaseModel

from app.integrations.errors import ExternalIntegrationError

logger = logging.getLogger(__name__)

EXTREMES_URL = "https://api.stormglass.io/v2/tide/extremes/point"
_TIMEOUT_S = 15


class TideConditions(BaseModel):
    extremes: list[dict[str, object]]
    station_name: str | None
    station_distance_km: float | None
    fetched_at: datetime


async def fetch_tide(lat: float, lon: float, api_key: str) -> TideConditions:
    now = datetime.now(UTC)
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            resp = await client.get(
                EXTREMES_URL,
                params={
                    "lat": lat,
                    "lng": lon,
                    "start": now.isoformat(),
                    "end": (now + timedelta(hours=48)).isoformat(),
                },
                headers={"Authorization": api_key},
            )
            resp.raise_for_status()
            payload = resp.json()
    except httpx.HTTPStatusError as exc:
        retryable = exc.response.status_code not in (401, 403, 422)
        raise ExternalIntegrationError(
            f"stormglass HTTP {exc.response.status_code}", retryable=retryable
        ) from exc
    except httpx.HTTPError as exc:
        raise ExternalIntegrationError(f"stormglass request failed: {exc!r}", retryable=True) from exc

    try:
        extremes = [
            {
                "time": item["time"],
                "height": float(item["height"]),
                "type": str(item.get("type", "")),
            }
            for item in payload["data"]
        ]
        station = payload.get("meta", {}).get("station", {})
    except (KeyError, TypeError, ValueError) as exc:
        raise ExternalIntegrationError(f"stormglass payload unusable: {exc!r}", retryable=True) from exc

    if not extremes:
        raise ExternalIntegrationError("stormglass returned no tide extremes", retryable=True)

    distance = station.get("distance")
    return TideConditions(
        extremes=extremes,
        station_name=station.get("name"),
        station_distance_km=float(distance) if distance is not None else None,
        fetched_at=now,
    )
