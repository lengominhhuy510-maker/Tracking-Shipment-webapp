"""QA-01 — Ma trận Incoterm × direction → monitoring_mode (REPORT-ONLY, evidence-based).

Nguồn chân lý:
- Spec §5 (Spec_Demo_GiamSatLoHang-v0_9_19.md, bảng ma trận + hệ quả thiết kế).
- IC§1.1 (Interface-Contract_v0.9.9.md): hàm duy nhất
  `derive_monitoring_mode(direction, incoterm) -> Literal["auto_email","manual"] | raises UnsupportedCombination`.
  Nhóm E/F = EXW,FCA,FAS,FOB ; nhóm C/D = CFR,CIF,CPT,CIP,DAP,DPU,DDP ; enum KHÔNG dấu.

Vét cạn 22 ô (11 incoterm × 2 direction), KHÔNG sampling:
  import × E/F (4)  -> auto_email
  import × C/D (7)  -> manual
  export × C/D (7)  -> auto_email
  export × E/F (4)  -> raise UnsupportedCombination (API 400 UNSUPPORTED_INCOTERM_COMBINATION)
Edge: chữ thường / khoảng trắng thừa / không tồn tại -> hành vi xác định (raise rõ).
DRIFT: chỉ 1 module cài bảng §5 (IC§1.1 "mọi module dùng hàm này, không tự cài bảng riêng").
"""

import pathlib

import pytest

from app.core.monitoring_mode import (
    GROUP_CD,
    GROUP_EF,
    UnsupportedCombination,
    derive_monitoring_mode,
)

# Nhóm Incoterm theo IC§1.1 / Spec §5 (nguồn chân lý — viết cứng ở test, KHÔNG import từ code
# để phát hiện nếu code định nghĩa sai nhóm).
EF = ("EXW", "FCA", "FAS", "FOB")            # 4 incoterm nhóm E/F
CD = ("CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP")  # 7 incoterm nhóm C/D
ALL_11 = EF + CD


# --------------------------------------------------------------------------- #
# Vét cạn 22 ô = 11 incoterm × 2 direction                                     #
# --------------------------------------------------------------------------- #

# import × E/F (4 ô) -> auto_email
@pytest.mark.parametrize("incoterm", EF)
def test_cell_import_ef_auto_email(incoterm):
    assert derive_monitoring_mode("import", incoterm) == "auto_email"


# import × C/D (7 ô) -> manual
@pytest.mark.parametrize("incoterm", CD)
def test_cell_import_cd_manual(incoterm):
    assert derive_monitoring_mode("import", incoterm) == "manual"


# export × C/D (7 ô) -> auto_email
@pytest.mark.parametrize("incoterm", CD)
def test_cell_export_cd_auto_email(incoterm):
    assert derive_monitoring_mode("export", incoterm) == "auto_email"


# export × E/F (4 ô) -> raise UnsupportedCombination
@pytest.mark.parametrize("incoterm", EF)
def test_cell_export_ef_raises_unsupported(incoterm):
    with pytest.raises(UnsupportedCombination):
        derive_monitoring_mode("export", incoterm)


def test_matrix_is_exhaustive_22_cells():
    """Bằng chứng phủ đúng 22 ô: 11 incoterm × 2 direction, không trùng/thiếu."""
    assert len(ALL_11) == 11
    assert len(EF) == 4 and len(CD) == 7
    assert set(EF).isdisjoint(CD)
    cells = [(d, i) for d in ("import", "export") for i in ALL_11]
    assert len(cells) == 22
    assert len(set(cells)) == 22


# --------------------------------------------------------------------------- #
# Enum trả về hợp lệ (IC§1.1: Literal["auto_email","manual"])                   #
# --------------------------------------------------------------------------- #
def test_return_values_only_valid_enum():
    seen = set()
    for incoterm in ALL_11:
        seen.add(derive_monitoring_mode("import", incoterm))
    for incoterm in CD:
        seen.add(derive_monitoring_mode("export", incoterm))
    assert seen <= {"auto_email", "manual"}


# --------------------------------------------------------------------------- #
# API mapping: UnsupportedCombination -> 400 UNSUPPORTED_INCOTERM_COMBINATION   #
# (IC§1.1 dòng POST /api/v1/shipments). Xác nhận API dùng ĐÚNG hàm + đúng mã.   #
# --------------------------------------------------------------------------- #
def test_api_layer_maps_unsupported_to_400_code():
    src = (
        pathlib.Path(__file__).resolve().parents[2] / "app" / "api" / "shipments.py"
    ).read_text(encoding="utf-8")
    # API phải gọi hàm duy nhất, bắt UnsupportedCombination, và trả đúng mã contract.
    assert "derive_monitoring_mode(" in src
    assert "UnsupportedCombination" in src
    assert "UNSUPPORTED_INCOTERM_COMBINATION" in src
    assert "400" in src


# --------------------------------------------------------------------------- #
# Edge: chữ thường / khoảng trắng thừa / không tồn tại -> hành vi xác định      #
# IC§1.1 enum KHÔNG dấu, uppercase; hàm KHÔNG normalize -> phải raise rõ ràng,  #
# KHÔNG trả bừa một mode.                                                       #
# --------------------------------------------------------------------------- #
LOWER_OR_SPACED = [
    "fob",      # chữ thường (E/F)
    "cif",      # chữ thường (C/D)
    " FOB",     # khoảng trắng đầu
    "FOB ",     # khoảng trắng cuối
    " CIF ",    # khoảng trắng 2 đầu
    "Fo B",     # khoảng trắng giữa
]


@pytest.mark.parametrize("incoterm", LOWER_OR_SPACED)
def test_edge_lowercase_or_whitespace_import_raises(incoterm):
    """import: incoterm không chuẩn hoá -> raise xác định, KHÔNG trả bừa mode."""
    with pytest.raises((ValueError, UnsupportedCombination)):
        derive_monitoring_mode("import", incoterm)


@pytest.mark.parametrize("incoterm", LOWER_OR_SPACED)
def test_edge_lowercase_or_whitespace_export_raises(incoterm):
    """export: incoterm không chuẩn hoá -> raise xác định, KHÔNG trả bừa mode."""
    with pytest.raises((ValueError, UnsupportedCombination)):
        derive_monitoring_mode("export", incoterm)


@pytest.mark.parametrize("incoterm", ["", "XXX", "FOBB", "C/D", "123", "auto_email"])
def test_edge_nonexistent_incoterm_raises_valueerror(incoterm):
    """Incoterm không tồn tại -> ValueError rõ ràng (không trả auto_email/manual)."""
    with pytest.raises(ValueError):
        derive_monitoring_mode("import", incoterm)
    with pytest.raises(ValueError):
        derive_monitoring_mode("export", incoterm)


def test_edge_raise_not_silent_return():
    """Khẳng định: incoterm rác KHÔNG bao giờ trả về một mode hợp lệ (fail-loud)."""
    for junk in ["fob", " FOB ", "XXX", ""]:
        for direction in ("import", "export"):
            with pytest.raises((ValueError, UnsupportedCombination)):
                _ = derive_monitoring_mode(direction, junk)


# --------------------------------------------------------------------------- #
# Nhóm Incoterm trong code khớp IC§1.1 (nếu lệch -> BUG-APP, không phải test).  #
# --------------------------------------------------------------------------- #
def test_code_groups_match_contract():
    assert set(GROUP_EF) == set(EF)
    assert set(GROUP_CD) == set(CD)
    assert set(GROUP_EF).isdisjoint(GROUP_CD)
    assert set(GROUP_EF) | set(GROUP_CD) == set(ALL_11)


# --------------------------------------------------------------------------- #
# DRIFT: CHỈ 1 module cài bảng §5 (IC§1.1 "mọi module dùng hàm này, không tự    #
# cài bảng riêng"). Quét app/ tìm module định nghĩa nhóm E/F hoặc C/D riêng.    #
# Phân biệt "enum 11 giá trị đầy đủ" (hợp lệ) vs "subgroup E/F hay C/D" (drift). #
# --------------------------------------------------------------------------- #
def _iter_app_py_files():
    app_dir = pathlib.Path(__file__).resolve().parents[2] / "app"
    return [p for p in app_dir.rglob("*.py")]


def test_no_second_incoterm_table_drift():
    canonical = (
        pathlib.Path(__file__).resolve().parents[2]
        / "app" / "core" / "monitoring_mode.py"
    ).resolve()
    offenders = []
    for path in _iter_app_py_files():
        if path.resolve() == canonical:
            continue
        text = path.read_text(encoding="utf-8")
        has_ef_group = all(code in text for code in EF)
        has_cd_group = all(code in text for code in CD)
        # Enum đầy đủ 11 giá trị (có cả EF lẫn CD) = định nghĩa enum/CHECK hợp lệ, KHÔNG phải bảng mode.
        # Subgroup riêng lẻ (chỉ E/F hoặc chỉ C/D) = dấu hiệu module tự cài bảng nhóm.
        standalone_subgroup = (has_ef_group != has_cd_group)
        if standalone_subgroup:
            offenders.append(str(path))
    assert offenders == [], (
        "DRIFT: module khác cài nhóm Incoterm riêng (IC§1.1 cấm): " + ", ".join(offenders)
    )
