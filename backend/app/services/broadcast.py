"""Broadcast shipment events to connected WebSocket clients (IC§6)."""

from datetime import UTC, datetime

from app.api.ws import manager


def _envelope(event_type: str, shipment_id: int, data: dict) -> dict:
    return {
        "type": event_type,
        "shipment_id": shipment_id,
        "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "data": data,
    }


async def broadcast_position(shipment_id: int, data: dict) -> None:
    await manager.broadcast(_envelope("position_update", shipment_id, data))


async def broadcast_eta_update(shipment_id: int, data: dict) -> None:
    await manager.broadcast(_envelope("eta_update", shipment_id, data))


async def broadcast_deviation_alert(shipment_id: int, data: dict) -> None:
    await manager.broadcast(_envelope("deviation_alert", shipment_id, data))


async def broadcast_tidal_alert(shipment_id: int, data: dict) -> None:
    await manager.broadcast(_envelope("tidal_alert", shipment_id, data))


async def broadcast_proposal_created(shipment_id: int, data: dict) -> None:
    await manager.broadcast(_envelope("proposal_created", shipment_id, data))


async def broadcast_onboarding_update(shipment_id: int, data: dict) -> None:
    await manager.broadcast(_envelope("onboarding_update", shipment_id, data))


async def broadcast_status_change(shipment_id: int, data: dict) -> None:
    await manager.broadcast(_envelope("status_change", shipment_id, data))


async def broadcast_status_change_suggested(shipment_id: int, data: dict) -> None:
    await manager.broadcast(_envelope("status_change_suggested", shipment_id, data))
