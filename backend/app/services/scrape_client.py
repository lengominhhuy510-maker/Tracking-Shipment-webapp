"""Python client for the Node playwright-mcp /scrape-jobs gate (IC§3.3).

Python owns the poll loop and writes the DB (IC§0.1); Node only runs the
deterministic Playwright job and returns JSON via Redis-backed job state.
``resolve_imo`` POSTs a job, polls every 3s up to 120s, and validates the
result against ``IMOResolverResult`` (IC§4.1). Any failure maps to a
``ScrapeError`` carrying an ``onboarding_error`` code the caller feeds to
``mark_leg_manual``.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

import httpx
from pydantic import BaseModel, Field, HttpUrl, ValidationError, field_validator

from app.core.normalize import normalize_vessel_name

logger = logging.getLogger(__name__)

SCRAPE_BASE_URL = "http://playwright-mcp:3000"
POLL_INTERVAL_SECONDS = 3.0
POLL_TIMEOUT_SECONDS = 120.0
HTTP_REQUEST_TIMEOUT_SECONDS = 15.0

# Matches enums.ONBOARDING_ERROR 1-1 (IC§3.3 error_code ↔ onboarding_error).
ErrorCode = Literal["captcha", "not_found", "ambiguous_name", "timeout", "login_required"]
_VALID_ERROR_CODES = {"captcha", "not_found", "ambiguous_name", "timeout", "login_required"}


class IMOResolverResult(BaseModel):
    """Node scrape output, re-validated in Python before any DB write (IC§4.1)."""

    vessel_name: str
    imo: str = Field(pattern=r"^\d{7}$")
    mmsi: str | None = Field(default=None, pattern=r"^\d{9}$")
    matched_voyage: str | None = None
    confidence: Literal["cao", "trung_binh", "thap"]
    source_url: HttpUrl

    @field_validator("vessel_name")
    @classmethod
    def _normalize_name(cls, raw: str) -> str:
        return normalize_vessel_name(raw)


@dataclass(frozen=True)
class ScrapeError:
    """Terminal failure — caller maps error_code onto the leg via mark_leg_manual."""

    error_code: ErrorCode


def _coerce_error_code(raw: str | None) -> ErrorCode:
    if raw in _VALID_ERROR_CODES:
        return raw  # type: ignore[return-value]
    return "timeout"


async def enqueue_imo(
    vessel_name: str,
    voyage_no: str | None = None,
    pol: str | None = None,
    pod: str | None = None,
    *,
    client: httpx.AsyncClient | None = None,
) -> str | ScrapeError:
    payload = {
        "vessel_name": normalize_vessel_name(vessel_name),
        "voyage_no": voyage_no,
        "pol": pol,
        "pod": pod,
    }
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(
            base_url=SCRAPE_BASE_URL, timeout=HTTP_REQUEST_TIMEOUT_SECONDS
        )
    try:
        return await _enqueue(client, payload)
    finally:
        if owns_client:
            await client.aclose()


async def poll_imo_job(
    job_id: str,
    *,
    client: httpx.AsyncClient | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    poll_interval_s: float = POLL_INTERVAL_SECONDS,
    timeout_s: float = POLL_TIMEOUT_SECONDS,
) -> IMOResolverResult | ScrapeError:
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(
            base_url=SCRAPE_BASE_URL, timeout=HTTP_REQUEST_TIMEOUT_SECONDS
        )
    try:
        return await _poll(client, job_id, sleep, poll_interval_s, timeout_s)
    finally:
        if owns_client:
            await client.aclose()


async def resolve_imo(
    vessel_name: str,
    voyage_no: str | None = None,
    pol: str | None = None,
    pod: str | None = None,
    *,
    client: httpx.AsyncClient | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    poll_interval_s: float = POLL_INTERVAL_SECONDS,
    timeout_s: float = POLL_TIMEOUT_SECONDS,
) -> IMOResolverResult | ScrapeError:
    payload = {
        "vessel_name": normalize_vessel_name(vessel_name),
        "voyage_no": voyage_no,
        "pol": pol,
        "pod": pod,
    }

    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(
            base_url=SCRAPE_BASE_URL, timeout=HTTP_REQUEST_TIMEOUT_SECONDS
        )
    try:
        job_id = await _enqueue(client, payload)
        if isinstance(job_id, ScrapeError):
            return job_id
        return await _poll(client, job_id, sleep, poll_interval_s, timeout_s)
    finally:
        if owns_client:
            await client.aclose()


async def _enqueue(client: httpx.AsyncClient, payload: dict) -> str | ScrapeError:
    try:
        create = await client.post(
            "/scrape-jobs", json={"type": "imo_resolve", "payload": payload}
        )
        create.raise_for_status()
        return str(create.json()["job_id"])
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        logger.warning("scrape enqueue failed for %r: %r", payload.get("vessel_name"), exc)
        return ScrapeError("timeout")


async def _poll(
    client: httpx.AsyncClient,
    job_id: str,
    sleep: Callable[[float], Awaitable[None]],
    poll_interval_s: float,
    timeout_s: float,
) -> IMOResolverResult | ScrapeError:
    elapsed = 0.0
    while elapsed < timeout_s:
        try:
            poll = await client.get(f"/scrape-jobs/{job_id}")
            poll.raise_for_status()
            body = poll.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("scrape poll failed for job %s: %r", job_id, exc)
            return ScrapeError("timeout")

        status = body.get("status")
        if status == "succeeded":
            try:
                return IMOResolverResult.model_validate(body.get("result"))
            except ValidationError as exc:
                logger.warning("scrape result for job %s failed validation: %r", job_id, exc)
                return ScrapeError("not_found")
        if status == "failed":
            return ScrapeError(_coerce_error_code(body.get("error_code")))

        await sleep(poll_interval_s)
        elapsed += poll_interval_s

    logger.warning("scrape job %s timed out after %.0fs", job_id, timeout_s)
    return ScrapeError("timeout")
