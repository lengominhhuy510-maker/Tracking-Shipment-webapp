"""Enum value tuples — single source of truth per Interface-Contract v0.9.9 §1.1.

DB stores TEXT + CHECK constraint (no Postgres ENUM type). Values are ASCII,
snake_case, no diacritics (`trung_binh`, `thap`).
"""

INCOTERMS = ("EXW", "FCA", "FAS", "FOB", "CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP")

SHIPMENT_DIRECTION = ("import", "export")

MONITORING_MODE = ("auto_email", "manual")

SHIPMENT_TYPE = ("direct", "transit")  # default "direct"

SHIPMENT_STATUS = ("new", "on_sea", "arrived", "delivered")  # default "new"

ONBOARDING_STATUS = ("pending", "resolved", "manual_required")  # default "pending"

ONBOARDING_ERROR = ("captcha", "not_found", "ambiguous_name", "timeout", "login_required")

IMO_RESOLVED_VIA = ("cache_hit", "deterministic_scrape", "manual")

ETA_ORIGINAL_SOURCE = ("carrier_scrape", "manual")

ETA_HISTORY_SOURCE = ("original", "ais_recompute", "weather_adjusted", "email_agent", "manual")

PROPOSAL_STATUS = ("pending", "approved", "rejected")  # default "pending"

RESEARCH_LEVEL = ("cao", "trung_binh", "thap")  # relevance + confidence

REGISTRY_RESOLVED_VIA = ("manual", "ais_static", "vesselfinder")

USER_PROVIDER = ("google", "microsoft")

USER_ROLE = ("user", "admin")  # default "user"

EMAIL_OUTCOME = ("proposals_created", "no_match", "rejected_allowlist", "parse_failed")


def check_in(column: str, values: tuple[str, ...]) -> str:
    """SQL text for a CHECK constraint. NULL passes automatically (SQL 3VL)."""
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({quoted})"
