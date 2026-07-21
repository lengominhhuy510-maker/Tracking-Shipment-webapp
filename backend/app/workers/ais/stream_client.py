"""Live AIS source (AIS_MODE=live): aisstream.io WebSocket.

Manages connect/subscribe/reconnect. The subscribe message is swap-and-replace
with the FULL MMSI list (Spec §3.1) — never a merge. ``resubscribe`` updates
the desired set and, if connected, re-sends the full subscribe payload.

External I/O with graceful fallback: connection/recv failures are logged and
retried with backoff rather than crashing the embedded worker.
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator

import websockets

from app.config import settings

logger = logging.getLogger(__name__)

_AIS_WS_URL = "wss://stream.aisstream.io/v0/stream"
_RECONNECT_BACKOFF_S = 5.0


class StreamClient:
    """AisSource implementation over the aisstream.io WebSocket."""

    def __init__(self, mmsi_set: set[str] | None = None) -> None:
        self._mmsi_set = set(mmsi_set or set())
        self._ws: websockets.ClientConnection | None = None

    def _subscribe_payload(self) -> dict:
        return {
            "APIKey": settings.AISSTREAM_API_KEY,
            "BoundingBoxes": [[[-90.0, -180.0], [90.0, 180.0]]],
            "FiltersShipMMSI": sorted(self._mmsi_set),
            "FilterMessageTypes": ["PositionReport"],
        }

    async def resubscribe(self, mmsi_set: set[str]) -> None:
        """Swap-and-replace the full MMSI list; re-send if currently connected."""
        self._mmsi_set = set(mmsi_set)
        if self._ws is not None:
            try:
                await self._ws.send(json.dumps(self._subscribe_payload()))
            except (OSError, websockets.WebSocketException) as exc:
                logger.warning("AIS resubscribe send failed: %r", exc)

    async def aclose(self) -> None:
        if self._ws is not None:
            await self._ws.close()
            self._ws = None

    async def messages(self) -> AsyncIterator[dict]:
        """Yield parsed JSON messages, reconnecting with backoff on failure."""
        while True:
            try:
                async with websockets.connect(_AIS_WS_URL) as ws:
                    self._ws = ws
                    await ws.send(json.dumps(self._subscribe_payload()))
                    async for raw in ws:
                        msg = json.loads(raw)
                        if "error" in msg:
                            logger.warning("aisstream error: %s", msg["error"])
                            continue
                        yield msg
            except (OSError, websockets.WebSocketException) as exc:
                logger.warning("AIS stream disconnected: %r — reconnecting", exc)
            finally:
                self._ws = None
            await asyncio.sleep(_RECONNECT_BACKOFF_S)
