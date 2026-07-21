"""Replay AIS source (AIS_MODE=replay): feed fixture PositionReports offline.

Yields the raw messages from ``tests/fixtures/ais_positions.json`` (or an
injected path) through the SAME upsert/broadcast path as the live source, so
CI can exercise the worker without a key or a real vessel. resubscribe is a
no-op — the fixture set is fixed.
"""

import json
from collections.abc import AsyncIterator
from pathlib import Path

_DEFAULT_FIXTURE = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "ais_positions.json"


class ReplaySource:
    """AisSource implementation reading a fixture JSON array of raw messages."""

    def __init__(self, fixture_path: str | Path | None = None) -> None:
        self._path = Path(fixture_path) if fixture_path else _DEFAULT_FIXTURE

    async def resubscribe(self, mmsi_set: set[str]) -> None:
        """No-op: the replay fixture set is fixed."""

    async def aclose(self) -> None:
        """No-op: nothing to close."""

    async def messages(self) -> AsyncIterator[dict]:
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        for msg in raw:
            yield msg
