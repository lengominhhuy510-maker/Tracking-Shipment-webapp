"""QA-07 — WS broadcast contract (server side, REPORT-ONLY).

Truth: IC§6 — the 8 broadcast_* function names, their 1-1 mapping to WS `type`,
the envelope shape {type, shipment_id, ts, data}, and the exact signature
`async def <name>(shipment_id: int, data: dict) -> None`.

"Lệch 1 chữ = gãy import" — so this suite imports each of the 8 names by exact
string and asserts name, coroutine-ness, signature, and emitted envelope. No app
code is modified; the ConnectionManager is exercised through a fake WebSocket so
no real network is used.
"""

import asyncio
import inspect

import pytest

from app.services import broadcast

# IC§6 mapping table (function name -> WS type), verbatim.
MAPPING = {
    "broadcast_position": "position_update",
    "broadcast_eta_update": "eta_update",
    "broadcast_deviation_alert": "deviation_alert",
    "broadcast_tidal_alert": "tidal_alert",
    "broadcast_proposal_created": "proposal_created",
    "broadcast_onboarding_update": "onboarding_update",
    "broadcast_status_change": "status_change",
    "broadcast_status_change_suggested": "status_change_suggested",
}


def test_exactly_eight_broadcast_functions_exist():
    names = {n for n in dir(broadcast) if n.startswith("broadcast_")}
    assert names == set(MAPPING), f"broadcast_* set drifted from IC§6: {names ^ set(MAPPING)}"


@pytest.mark.parametrize("name", sorted(MAPPING))
def test_broadcast_name_importable_by_exact_string(name):
    """Each of the 8 names must resolve — a 1-char drift breaks import."""
    fn = getattr(broadcast, name)
    assert callable(fn)
    assert inspect.iscoroutinefunction(fn), f"{name} must be `async def`"


@pytest.mark.parametrize("name", sorted(MAPPING))
def test_broadcast_signature_matches_ic6(name):
    """Signature must be `(shipment_id: int, data: dict) -> None`."""
    fn = getattr(broadcast, name)
    sig = inspect.signature(fn)
    params = list(sig.parameters.values())
    assert [p.name for p in params] == ["shipment_id", "data"], f"{name} param names drifted"
    assert params[0].annotation is int, f"{name} shipment_id must be annotated int"
    assert params[1].annotation is dict, f"{name} data must be annotated dict"
    assert sig.return_annotation is None, f"{name} must be annotated -> None"


class _FakeWS:
    def __init__(self):
        self.sent: list[dict] = []

    async def send_json(self, message: dict) -> None:
        self.sent.append(message)


@pytest.mark.parametrize("name,ws_type", sorted(MAPPING.items()))
def test_broadcast_emits_correct_envelope_type(monkeypatch, name, ws_type):
    """Calling broadcast_<x> emits an envelope whose `type` is the IC§6 type,
    with the full envelope shape and the payload passed through verbatim."""
    fake = _FakeWS()
    monkeypatch.setattr(broadcast.manager, "active_connections", [fake])

    payload = {"probe": 123}
    fn = getattr(broadcast, name)
    asyncio.run(fn(42, payload))

    assert len(fake.sent) == 1
    msg = fake.sent[0]
    assert set(msg) == {"type", "shipment_id", "ts", "data"}, "envelope shape drifted from IC§6"
    assert msg["type"] == ws_type
    assert msg["shipment_id"] == 42
    assert msg["data"] == payload
    assert isinstance(msg["ts"], str) and msg["ts"].endswith("Z")
