"""Spike/compatibility gate: MCP Python SDK ``mcp==1.12.4`` <-> ``@playwright/mcp@0.0.78`` qua SSE.

Chạy từ ``backend/``:  python scripts/spike_mcp.py

Yêu cầu server đang chạy (terminal khác, từ ``playwright-mcp/``):

    npx @playwright/mcp --port 3001 --headless

Client: ``from mcp.client.sse import sse_client`` -> ClientSession.initialize()
-> list_tools() -> gọi browser tool ``browser_navigate`` tới example.com, in
kết quả rồi thoát. Server không chạy -> in cảnh báo, exit 0 (không crash).

Port đọc từ env ``MCP_SSE_PORT`` (IC§7, default 3001).
"""

import asyncio
import os
import sys

import httpx

from mcp import ClientSession
from mcp.client.sse import sse_client

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")  # console Windows mặc định cp1252


async def run(url: str) -> None:
    async with sse_client(url) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            init = await session.initialize()
            print(f"initialized: server={init.serverInfo.name} v{init.serverInfo.version}")

            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            print(f"{len(names)} tools: {', '.join(sorted(names)[:10])} ...")

            assert "browser_navigate" in names, "browser_navigate tool missing"
            result = await session.call_tool(
                "browser_navigate", {"url": "https://example.com"}
            )
            text = " | ".join(
                c.text for c in result.content if getattr(c, "text", None)
            )
            print(f"browser_navigate result (trimmed): {text[:400]}")
            assert not result.isError, "browser_navigate returned isError"
            print("MCP SSE handshake + browser tool call OK")


async def main() -> int:
    port = os.environ.get("MCP_SSE_PORT", "3001").strip() or "3001"
    url = f"http://localhost:{port}/sse"
    print(f"Connecting SSE {url} ...")
    try:
        await run(url)
    except (httpx.HTTPError, OSError, ConnectionError) as exc:
        print(f"không kết nối được MCP server: {exc!r}")
        print("server chưa chạy? Từ playwright-mcp/: npx @playwright/mcp --port 3001 --headless")
        return 0
    except asyncio.TimeoutError:
        print("timeout chờ SSE — kiểm tra server/port")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
