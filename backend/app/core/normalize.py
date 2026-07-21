"""Shared normalization utils (IC§9). Every module MUST import from here."""

import re

_CONTAINER_RE = re.compile(r"^[A-Z]{4}\d{7}$")

# ISO 6346 letter values: A=10, then +1 per letter but skipping multiples of 11
# (11, 22, 33 are never assigned) → B=12 ... Z=38.
_LETTER_VALUES = {}
_v = 10
for _ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
    if _v % 11 == 0:
        _v += 1
    _LETTER_VALUES[_ch] = _v
    _v += 1


def normalize_vessel_name(raw: str) -> str:
    """Trim, collapse internal whitespace to one space, uppercase."""
    return " ".join(raw.split()).upper()


def normalize_container_no(raw: str) -> str:
    """Strip spaces/hyphens, uppercase, validate ISO 6346 format + check digit.

    Raises ValueError on bad format or wrong check digit (API maps to
    400 INVALID_CONTAINER_NO, IC§3.1).
    """
    cleaned = re.sub(r"[\s-]", "", raw).upper()
    if not _CONTAINER_RE.match(cleaned):
        raise ValueError(f"container number {raw!r} không đúng format ISO 6346")

    total = 0
    for i, ch in enumerate(cleaned[:10]):
        value = _LETTER_VALUES[ch] if ch.isalpha() else int(ch)
        total += value * (2**i)
    check_digit = (total % 11) % 10

    if check_digit != int(cleaned[10]):
        raise ValueError(f"container number {raw!r} sai check-digit ISO 6346")
    return cleaned
