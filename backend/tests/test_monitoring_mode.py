"""TDD — derive_monitoring_mode (IC§1.1): all 4 branches of Incoterm×direction."""

import pytest

from app.core.monitoring_mode import UnsupportedCombination, derive_monitoring_mode


def test_import_ef_auto_email():
    assert derive_monitoring_mode("import", "FOB") == "auto_email"


def test_import_cd_manual():
    assert derive_monitoring_mode("import", "CIF") == "manual"


def test_export_cd_auto_email():
    assert derive_monitoring_mode("export", "CIF") == "auto_email"


def test_export_ef_raises():
    with pytest.raises(UnsupportedCombination):
        derive_monitoring_mode("export", "FOB")


@pytest.mark.parametrize("incoterm", ["EXW", "FCA", "FAS", "FOB"])
def test_all_ef_import_auto_email(incoterm):
    assert derive_monitoring_mode("import", incoterm) == "auto_email"


@pytest.mark.parametrize("incoterm", ["CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP"])
def test_all_cd_export_auto_email(incoterm):
    assert derive_monitoring_mode("export", incoterm) == "auto_email"


@pytest.mark.parametrize("incoterm", ["EXW", "FCA", "FAS", "FOB"])
def test_all_ef_export_raise(incoterm):
    with pytest.raises(UnsupportedCombination):
        derive_monitoring_mode("export", incoterm)
