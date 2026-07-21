"""Spike: lấy wave/current thật từ Open-Meteo Marine API + wind từ Forecast API.

Chạy từ ``backend/``:  python scripts/spike_openmeteo.py

KHÔNG cần API key. In giá trị giờ hiện tại (UTC) tại toạ độ gần Cát Lái.
"""

import sys
from datetime import datetime, timezone

import httpx

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")  # console Windows mặc định cp1252

MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
LAT, LON = 10.75, 106.8  # ~Cát Lái (river port — marine grid cell có thể null)
SEA_LAT, SEA_LON = 10.2, 107.3  # ngoài khơi Vũng Tàu — luôn có dữ liệu marine


def current_hour_value(payload: dict, key: str) -> tuple[str, object]:
    hourly = payload["hourly"]
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:00")
    times = hourly["time"]
    idx = times.index(now_iso) if now_iso in times else 0
    return times[idx], hourly[key][idx]


def fetch_marine(lat: float, lon: float) -> dict:
    resp = httpx.get(
        MARINE_URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "hourly": "wave_height,ocean_current_velocity,ocean_current_direction",
            "timezone": "UTC",
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def main() -> int:
    try:
        marine = fetch_marine(LAT, LON)
        wave_now = current_hour_value(marine, "wave_height")[1]
        used = (LAT, LON)
        if wave_now is None:
            print(f"marine null tại Cát Lái ({LAT},{LON}) — thử điểm ngoài khơi ({SEA_LAT},{SEA_LON})")
            marine = fetch_marine(SEA_LAT, SEA_LON)
            used = (SEA_LAT, SEA_LON)
        forecast = httpx.get(
            FORECAST_URL,
            params={
                "latitude": LAT,
                "longitude": LON,
                "hourly": "wind_speed_10m,wind_direction_10m",
                "timezone": "UTC",
            },
            timeout=15,
        )
        forecast.raise_for_status()
    except httpx.HTTPError as exc:
        print(f"Open-Meteo request failed: {exc!r}")
        return 0

    m, f = marine, forecast.json()
    print(f"marine point used: {used}")
    for key in ("wave_height", "ocean_current_velocity", "ocean_current_direction"):
        t, v = current_hour_value(m, key)
        unit = m.get("hourly_units", {}).get(key, "")
        print(f"{key} @ {t}Z: {v} {unit}")
    for key in ("wind_speed_10m", "wind_direction_10m"):
        t, v = current_hour_value(f, key)
        unit = f.get("hourly_units", {}).get(key, "")
        print(f"{key} @ {t}Z: {v} {unit}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
