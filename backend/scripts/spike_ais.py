"""Spike: nhận PositionReport thật từ aisstream.io qua WebSocket.

Chạy từ ``backend/``:  python scripts/spike_ais.py

Cần env ``AISSTREAM_API_KEY`` (load từ ``.env`` gốc repo — xem scripts/README.md).
In 5-10 bản tin PositionReport (MMSI, lat, lon, SOG, COG) rồi thoát.
Khi nhận đủ, dump bản tin thô vào ``backend/tests/fixtures/ais_positions.json``
(fixture cho parser test / replay mode TASK-04 / E2E TASK-17).

Fallback: 30s không có message -> in cảnh báo, exit 0 (không crash).
"""

import asyncio
import json
import os
import sys
from pathlib import Path

import websockets

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")  # console Windows mặc định cp1252

AIS_WS_URL = "wss://stream.aisstream.io/v0/stream"
# Box quanh biển Đông / Singapore (lat, lon pairs per aisstream docs)
BOUNDING_BOXES = [[[1.0, 103.0], [11.0, 110.0]]]
TARGET_COUNT = 10
MIN_COUNT = 5
OVERALL_TIMEOUT_S = 30
FIXTURE_PATH = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "ais_positions.json"


async def collect_position_reports(api_key: str) -> list[dict]:
    reports: list[dict] = []
    subscribe = {
        "APIKey": api_key,
        "BoundingBoxes": BOUNDING_BOXES,
        "FilterMessageTypes": ["PositionReport"],
    }
    async with websockets.connect(AIS_WS_URL) as ws:
        await ws.send(json.dumps(subscribe))
        while len(reports) < TARGET_COUNT:
            raw = await ws.recv()
            msg = json.loads(raw)
            if msg.get("MessageType") != "PositionReport":
                # aisstream có thể trả error object {"error": "..."} khi key sai
                if "error" in msg:
                    print(f"aisstream error: {msg['error']}")
                    return reports
                continue
            reports.append(msg)
            pr = msg["Message"]["PositionReport"]
            meta = msg.get("MetaData", {})
            print(
                f"PositionReport #{len(reports)}: "
                f"MMSI={pr.get('UserID')} "
                f"lat={pr.get('Latitude'):.5f} lon={pr.get('Longitude'):.5f} "
                f"SOG={pr.get('Sog')} COG={pr.get('Cog')} "
                f"name={str(meta.get('ShipName', '')).strip()}"
            )
    return reports


async def main() -> int:
    api_key = os.environ.get("AISSTREAM_API_KEY", "").strip()
    if not api_key:
        print("thiếu key: AISSTREAM_API_KEY trống — load .env rồi chạy lại (xem scripts/README.md)")
        return 0

    print(f"Connecting {AIS_WS_URL} (timeout {OVERALL_TIMEOUT_S}s)...")
    try:
        reports = await asyncio.wait_for(
            collect_position_reports(api_key), timeout=OVERALL_TIMEOUT_S
        )
    except asyncio.TimeoutError:
        print("không nhận được message trong 30s — kiểm tra key/bounding box")
        return 0
    except (OSError, websockets.WebSocketException) as exc:
        print(f"kết nối thất bại: {exc!r} — kiểm tra mạng/key")
        return 0

    if not reports:
        print("không nhận được PositionReport — kiểm tra key/bounding box")
        return 0

    print(f"Nhận {len(reports)} PositionReport.")
    if len(reports) >= MIN_COUNT:
        FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE_PATH.write_text(
            json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"Fixture dumped: {FIXTURE_PATH}")
    else:
        print(f"<{MIN_COUNT} bản tin — không ghi đè fixture")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
