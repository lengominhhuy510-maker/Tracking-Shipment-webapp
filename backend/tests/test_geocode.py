from pathlib import Path

import pytest

from app.config import settings


@pytest.fixture(autouse=True)
def use_demo_wpi(monkeypatch: pytest.MonkeyPatch) -> None:
    path = Path(__file__).parents[1] / "data" / "wpi_ports.csv"
    monkeypatch.setattr(settings, "WPI_DATA_PATH", str(path))


def test_geocode_alias_cat_lai() -> None:
    from app.services.geocode import geocode_port

    lat, lng, un_locode = geocode_port("Cat Lai")

    assert un_locode == "VNCLI"
    assert lat == pytest.approx(10.756)
    assert lng == pytest.approx(106.75)


def test_geocode_alias_is_accent_and_case_insensitive() -> None:
    from app.services.geocode import geocode_port

    assert geocode_port("  cÁT lÁi ") == geocode_port("Cat Lai")


def test_geocode_by_un_locode() -> None:
    from app.services.geocode import geocode_port

    assert geocode_port("SGSIN")[2] == "SGSIN"


def test_geocode_unknown_port_returns_none() -> None:
    from app.services.geocode import geocode_port

    assert geocode_port("Definitely Not A Port") is None


def test_geocode_missing_csv_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.geocode import geocode_port

    monkeypatch.setattr(settings, "WPI_DATA_PATH", "missing-wpi.csv")

    assert geocode_port("Cat Lai") is None
