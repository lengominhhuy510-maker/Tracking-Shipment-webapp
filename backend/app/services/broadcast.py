"""Central broadcast hook module (TASK-04 step 0 — noop bodies).

TASK-06 replaces each body with ConnectionManager.broadcast using the IC§6
envelope ``{type, shipment_id, ts, data}``. Names + signatures are FROZEN
(IC§6 mapping table) — TASK-05/07/11/13 import these exact names.
"""


async def broadcast_position(shipment_id: int, data: dict) -> None:
    """type="position_update" — TASK-06 thay body bằng ConnectionManager.broadcast."""


async def broadcast_eta_update(shipment_id: int, data: dict) -> None:
    """type="eta_update" — TASK-06 thay body bằng ConnectionManager.broadcast."""


async def broadcast_deviation_alert(shipment_id: int, data: dict) -> None:
    """type="deviation_alert" — TASK-06 thay body bằng ConnectionManager.broadcast."""


async def broadcast_tidal_alert(shipment_id: int, data: dict) -> None:
    """type="tidal_alert" — TASK-06 thay body bằng ConnectionManager.broadcast."""


async def broadcast_proposal_created(shipment_id: int, data: dict) -> None:
    """type="proposal_created" — TASK-06 thay body bằng ConnectionManager.broadcast."""


async def broadcast_onboarding_update(shipment_id: int, data: dict) -> None:
    """type="onboarding_update" — TASK-06 thay body bằng ConnectionManager.broadcast."""


async def broadcast_status_change(shipment_id: int, data: dict) -> None:
    """type="status_change" — TASK-06 thay body bằng ConnectionManager.broadcast."""


async def broadcast_status_change_suggested(shipment_id: int, data: dict) -> None:
    """type="status_change_suggested" — TASK-06 thay body bằng ConnectionManager.broadcast."""
