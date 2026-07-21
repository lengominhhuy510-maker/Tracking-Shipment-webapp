"""MCP browser gateway (IC§3.3 cửa MCP, Ràng buộc toàn cục v0.9.12 Option 1.5).

``BrowserAgentClient`` is the ONLY module in the codebase allowed to import the
``mcp`` package (``mcp==1.12.4``, verified by the TASK-01 ``spike_mcp.py`` gate:
``sse_client(url)`` -> ``ClientSession`` -> ``initialize`` -> ``call_tool``).
It owns transport/handshake/timeout and maps every failure to
``ExternalIntegrationError`` — no MCP types leak out of this file. Carrier ETA
agent/service call this gateway; they never see the SSE endpoint or raw dicts.

This is the MCP SSE door (port 3001) — distinct from the deterministic
``/scrape-jobs`` REST door (port 3000) reserved for the IMO Resolver.
"""

import logging
from contextlib import AsyncExitStack
from datetime import timedelta

from mcp import ClientSession
from mcp.client.sse import sse_client

from app.config import settings
from app.integrations.errors import ExternalIntegrationError

logger = logging.getLogger(__name__)

MCP_SSE_HOST = "playwright-mcp"  # IC§12 — same docker network host as scrape_client
CONNECT_TIMEOUT_SECONDS = 10.0
TOOL_CALL_TIMEOUT_SECONDS = 60.0


def _default_url() -> str:
    return f"http://{MCP_SSE_HOST}:{settings.MCP_SSE_PORT}/sse"


class BrowserAgentClient:
    """One SSE connection + MCP session for the lifetime of one agent run.

    Usage::

        async with BrowserAgentClient() as client:
            text = await client.call_tool("browser_navigate", {"url": ...})
    """

    def __init__(self, url: str | None = None) -> None:
        self._url = url or _default_url()
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None

    async def __aenter__(self) -> "BrowserAgentClient":
        stack = AsyncExitStack()
        try:
            read_stream, write_stream = await stack.enter_async_context(
                sse_client(self._url, timeout=CONNECT_TIMEOUT_SECONDS)
            )
            session = await stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )
            await session.initialize()
        except BaseException as exc:
            await stack.aclose()
            raise ExternalIntegrationError(
                f"MCP SSE connect/handshake failed ({self._url}): {exc!r}",
                retryable=True,
            ) from exc
        self._stack = stack
        self._session = session
        return self

    async def __aexit__(self, *exc_info) -> None:
        stack, self._stack, self._session = self._stack, None, None
        if stack is not None:
            try:
                await stack.aclose()
            except BaseException:  # noqa: BLE001 — teardown must not mask the run outcome
                logger.warning("MCP SSE close failed", exc_info=True)

    async def call_tool(self, name: str, arguments: dict | None = None) -> str:
        """Call one browser tool; return its text content joined into one string."""
        if self._session is None:
            raise ExternalIntegrationError(
                "BrowserAgentClient dùng ngoài context manager", retryable=False
            )
        try:
            result = await self._session.call_tool(
                name,
                arguments or {},
                read_timeout_seconds=timedelta(seconds=TOOL_CALL_TIMEOUT_SECONDS),
            )
        except Exception as exc:
            raise ExternalIntegrationError(
                f"MCP tool {name} call failed: {exc!r}", retryable=True
            ) from exc

        text = "\n".join(
            c.text for c in result.content if getattr(c, "text", None)
        )
        if result.isError:
            raise ExternalIntegrationError(
                f"MCP tool {name} returned error: {text[:500]}", retryable=True
            )
        return text
