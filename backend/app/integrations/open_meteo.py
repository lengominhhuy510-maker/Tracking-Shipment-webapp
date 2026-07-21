"""Open-Meteo client — Marine (wave/current) + Forecast (wind), no API key.

One logical ``fetch_conditions`` = two HTTP requests (Marine grid lacks wind).
Units requested in knots/metres/degrees so values persist directly (IC§7).
"""

import logging
from datetime import UTC, datetime

import httpx
from pydantic import BaseModel

from app.integrations.errors import ExternalIntegrationError

logger = logging.getLogger(__name__)

MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_TIMEOUT_S = 15


class WeatherConditions(BaseModel):
    wind_speed_kn: float
    wave_height_m: float
    current_speed_kn: float
    current_direction_deg: float
    fetched_at: datetime


def _current_hour_value(payload: dict, key: str) -> object:
    hourly = payload["hourly"]
    now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:00")
    times = hourly["time"]
    idx = times.index(now_iso) if now_iso in times else 0
    return hourly[key][idx]


async def fetch_conditions(lat: float, lon: float) -> WeatherConditions:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            marine = await client.get(
                MARINE_URL,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "hourly": "wave_height,ocean_current_velocity,ocean_current_direction",
                    "timezone": "UTC",
                },
            )
            marine.raise_for_status()
            forecast = await client.get(
                FORECAST_URL,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "hourly": "wind_speed_10m,wind_direction_10m",
                    "wind_speed_unit": "kn",
                    "timezone": "UTC",
                },
            )
            forecast.raise_for_status()
    except httpx.HTTPError as exc:
        raise ExternalIntegrationError(f"open-meteo request failed: {exc!r}", retryable=True) from exc

    try:
        marine_json = marine.json()
        forecast_json = forecast.json()
        values = {
            "wave_height_m": _current_hour_value(marine_json, "wave_height"),
            "current_speed_kn": _current_hour_value(marine_json, "ocean_current_velocity"),
            "current_direction_deg": _current_hour_value(marine_json, "ocean_current_direction"),
            "wind_speed_kn": _current_hour_value(forecast_json, "wind_speed_10m"),
        }
    except (KeyError, IndexError, ValueError, TypeError) as exc:
        raise ExternalIntegrationError(
            f"open-meteo payload unusable: {exc!r}", retryable=True
        ) from exc

    # Marine grid returns null over land/river cells (e.g. Cát Lái) — treat as
    # a failed fetch so cached values survive, never persist nulls.
    if any(value is None for value in values.values()):
        raise ExternalIntegrationError(
            f"open-meteo returned null marine data at ({lat}, {lon})", retryable=True
        )

    # Marine current velocity has no unit param — provider returns km/h.
    return WeatherConditions(
        wind_speed_kn=float(values["wind_speed_kn"]),
        wave_height_m=float(values["wave_height_m"]),
        current_speed_kn=float(values["current_speed_kn"]) / 1.852,
        current_direction_deg=float(values["current_direction_deg"]),
        fetched_at=datetime.now(UTC),
    )
