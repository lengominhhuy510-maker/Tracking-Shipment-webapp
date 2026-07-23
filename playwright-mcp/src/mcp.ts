// Cửa 2 (Spec §3.7): MCP SSE port 3001 cho Carrier ETA Agent (TASK-12).
// Chạy CLI của @playwright/mcp@0.0.78 (pin exact, gate TASK-01 — spike_mcp.py
// đã verify handshake SSE qua đúng lệnh này) như child process song song Express.
// Không dùng API programmatic vì package experimental — CLI là bề mặt đã gate.
import { spawn, type ChildProcess } from "node:child_process";
import { createRequire } from "node:module";
import path from "node:path";

const MCP_SSE_PORT = process.env.MCP_SSE_PORT ?? "3001";

export function startMcpServer(): ChildProcess {
  const require = createRequire(import.meta.url);
  const pkgJson = require.resolve("@playwright/mcp/package.json");
  const pkg = require("@playwright/mcp/package.json") as {
    bin: Record<string, string>;
  };
  const binRel = Object.values(pkg.bin)[0];
  const binPath = path.join(path.dirname(pkgJson), binRel);

  const child = spawn(
    process.execPath,
    [binPath, "--port", MCP_SSE_PORT, "--host", "0.0.0.0", "--headless", "--isolated"],
    { stdio: "inherit" },
  );
  child.on("exit", (code, signal) => {
    console.error(`[mcp] server exited (code=${code} signal=${signal}) — container sẽ restart`);
    process.exit(code ?? 1);
  });
  console.log(`[mcp] SSE server starting on :${MCP_SSE_PORT}`);
  return child;
}
