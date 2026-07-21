"""derive_monitoring_mode — single source for Incoterm×direction table (IC§1.1, Spec §5)."""

from typing import Literal

GROUP_EF = frozenset({"EXW", "FCA", "FAS", "FOB"})
GROUP_CD = frozenset({"CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP"})


class UnsupportedCombination(Exception):
    """export × E/F group — not supported (API returns 400, UI hides the option)."""


def derive_monitoring_mode(direction: str, incoterm: str) -> Literal["auto_email", "manual"]:
    if incoterm in GROUP_EF:
        if direction == "export":
            raise UnsupportedCombination(f"export × {incoterm} (nhóm E/F) không được hỗ trợ")
        return "auto_email"
    if incoterm in GROUP_CD:
        return "auto_email" if direction == "export" else "manual"
    raise ValueError(f"incoterm không hợp lệ: {incoterm!r}")
