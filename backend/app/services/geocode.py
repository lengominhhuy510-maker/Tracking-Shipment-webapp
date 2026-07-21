import csv
import unicodedata
from pathlib import Path

from app.config import settings

_ALIASES = {
    "cat lai": "VNCLI",
    "cang cat lai": "VNCLI",
    "port of singapore": "SGSIN",
    "port of hong kong": "HKHKG",
    "port of kaohsiung": "TWKHH",
    "port of shanghai": "CNSHA",
}


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return " ".join(
        "".join(char for char in decomposed if not unicodedata.combining(char))
        .casefold()
        .split()
    )


def geocode_port(name: str) -> tuple[float, float, str] | None:
    path = Path(settings.WPI_DATA_PATH)
    try:
        with path.open(encoding="utf-8", newline="") as source:
            rows = list(csv.DictReader(source))
    except OSError:
        return None

    query = _normalize(name)
    alias_locode = _ALIASES.get(query)
    for row in rows:
        locode = row["un_locode"].strip().upper()
        if alias_locode == locode or query in {
            _normalize(locode),
            _normalize(row["name"]),
        }:
            return float(row["latitude"]), float(row["longitude"]), locode
    return None
