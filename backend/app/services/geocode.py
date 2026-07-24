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


def _candidate_keys(name: str) -> tuple[set[str], str | None]:
    """Build the set of normalized keys to match a POD string against.

    Stored PODs use the ``"LOCODE Name"`` shape (e.g. ``"VNCLI Cat Lai"``), so
    besides the whole normalized string we also try the LOCODE prefix and the
    remainder as a port name. Returns ``(keys, prefix_locode)`` where
    ``prefix_locode`` is the upper-cased 5-char LOCODE prefix if present.
    """
    query = _normalize(name)
    keys = {query}

    prefix_locode: str | None = None
    tokens = name.split()
    if tokens:
        head = tokens[0].strip().upper()
        if len(head) == 5 and head.isalnum():
            prefix_locode = head
            keys.add(_normalize(head))
            remainder = " ".join(tokens[1:])
            if remainder:
                keys.add(_normalize(remainder))
    return keys, prefix_locode


def geocode_port(name: str) -> tuple[float, float, str] | None:
    path = Path(settings.WPI_DATA_PATH)
    try:
        with path.open(encoding="utf-8", newline="") as source:
            rows = list(csv.DictReader(source))
    except OSError:
        return None

    keys, prefix_locode = _candidate_keys(name)
    alias_locode = next((self for key in keys if (self := _ALIASES.get(key))), None)
    for row in rows:
        locode = row["un_locode"].strip().upper()
        if (
            alias_locode == locode
            or prefix_locode == locode
            or _normalize(locode) in keys
            or _normalize(row["name"]) in keys
        ):
            return float(row["latitude"]), float(row["longitude"]), locode
    return None
