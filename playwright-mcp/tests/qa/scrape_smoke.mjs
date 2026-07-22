// QA-12 smoke harness (REPORT-ONLY, OFFLINE — no real scraping).
// Boots the built REST app (dist/server.js `createApp`) WITHOUT the BullMQ
// worker, so enqueued jobs stay `queued` and the Playwright/VesselFinder script
// (runImoResolve) NEVER runs — zero network to real sites. Also boots the MCP
// SSE server (@playwright/mcp CLI, --headless --isolated) to verify the :3001
// handshake. Verifies IC§3.3 shapes + IC§12 ports.
//
// Run:  cd playwright-mcp && npm ci && npm run build
//       node tests/qa/scrape_smoke.mjs
// Requires a Redis reachable at REDIS_URL (BullMQ Queue construction only;
// no worker consumes jobs).
import { createApp } from "../../dist/server.js";
import { startMcpServer } from "../../dist/mcp.js";

const REST_PORT = Number(process.env.SCRAPE_REST_PORT ?? "3000");
const SSE_PORT = Number(process.env.MCP_SSE_PORT ?? "3001");
const BASE = `http://localhost:${REST_PORT}`;

let pass = 0;
let fail = 0;
function check(name, cond, detail) {
  const tag = cond ? "PASS" : "FAIL";
  if (cond) pass++; else fail++;
  console.log(`[${tag}] ${name}${detail ? " — " + detail : ""}`);
}

async function main() {
  // 1) Boot REST (no worker → jobs never execute → offline).
  const app = createApp();
  const server = await new Promise((resolve) => {
    const s = app.listen(REST_PORT, () => resolve(s));
  });
  console.log(`[boot] REST listening on :${REST_PORT} (worker intentionally NOT started)`);

  // 2) Boot MCP SSE child.
  const mcpChild = startMcpServer();
  await new Promise((r) => setTimeout(r, 3500)); // give CLI time to bind

  try {
    // --- POST valid payload (IC§3.3) → 202 {job_id} ---
    const postRes = await fetch(`${BASE}/scrape-jobs`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        type: "imo_resolve",
        payload: { vessel_name: "EVER GIVEN", voyage_no: "0FKW1E1MA", pol: "SGSIN", pod: "VNCLI" },
      }),
    });
    const postBody = await postRes.json();
    console.log("POST /scrape-jobs ->", postRes.status, JSON.stringify(postBody));
    check("POST valid returns 202", postRes.status === 202, `got ${postRes.status}`);
    check("POST 202 body has job_id:str", typeof postBody.job_id === "string", JSON.stringify(postBody));
    const jobId = postBody.job_id;

    // --- POST invalid type → 400 (validation) ---
    const badRes = await fetch(`${BASE}/scrape-jobs`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ type: "carrier_eta", payload: { vessel_name: "X" } }),
    });
    const badBody = await badRes.json();
    console.log("POST invalid type ->", badRes.status, JSON.stringify(badBody).slice(0, 160));
    check("POST wrong type rejected 400", badRes.status === 400, `got ${badRes.status}`);

    // --- POST missing vessel_name → 400 ---
    const badRes2 = await fetch(`${BASE}/scrape-jobs`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ type: "imo_resolve", payload: { voyage_no: "x" } }),
    });
    console.log("POST missing vessel_name ->", badRes2.status);
    check("POST missing vessel_name rejected 400", badRes2.status === 400, `got ${badRes2.status}`);

    // --- GET existing job → 200, correct shape, status queued (worker off) ---
    const getRes = await fetch(`${BASE}/scrape-jobs/${jobId}`);
    const getBody = await getRes.json();
    console.log("GET /scrape-jobs/:id ->", getRes.status, JSON.stringify(getBody));
    check("GET existing returns 200", getRes.status === 200, `got ${getRes.status}`);
    const validStatus = ["queued", "running", "succeeded", "failed"];
    check("GET status in 4-value enum", validStatus.includes(getBody.status), `status=${getBody.status}`);
    check("GET has job_id + result + error_code keys",
      "job_id" in getBody && "result" in getBody && "error_code" in getBody,
      Object.keys(getBody).join(","));
    check("GET queued job: result null + error_code null",
      getBody.result === null && getBody.error_code === null,
      `result=${JSON.stringify(getBody.result)} error_code=${JSON.stringify(getBody.error_code)}`);

    // --- GET nonexistent job → 404 ---
    const missRes = await fetch(`${BASE}/scrape-jobs/does-not-exist-999`);
    console.log("GET nonexistent ->", missRes.status);
    check("GET nonexistent returns 404", missRes.status === 404, `got ${missRes.status}`);

    // --- SSE :3001 handshake (IC§12 /sse) ---
    let sseStatus = 0, sseCT = "";
    try {
      const ac = new AbortController();
      const sseRes = await fetch(`http://localhost:${SSE_PORT}/sse`, {
        headers: { accept: "text/event-stream" },
        signal: ac.signal,
      });
      sseStatus = sseRes.status;
      sseCT = sseRes.headers.get("content-type") ?? "";
      console.log(`SSE GET :${SSE_PORT}/sse ->`, sseStatus, "content-type:", sseCT);
      // Read a small chunk then abort to simulate client disconnect.
      const reader = sseRes.body.getReader();
      const chunk = await Promise.race([
        reader.read(),
        new Promise((r) => setTimeout(() => r({ value: null }), 1500)),
      ]);
      if (chunk && chunk.value) {
        console.log("SSE first bytes:", Buffer.from(chunk.value).toString("utf8").slice(0, 120).replace(/\n/g, "\\n"));
      }
      ac.abort(); // client disconnect
      try { await reader.cancel(); } catch {}
    } catch (e) {
      console.log("SSE fetch error:", e.message);
    }
    check("SSE :3001 handshake 200", sseStatus === 200, `status=${sseStatus}`);
    check("SSE content-type text/event-stream", sseCT.includes("text/event-stream"), `ct=${sseCT}`);

    // --- verify MCP child still alive after client disconnect (no crash) ---
    await new Promise((r) => setTimeout(r, 800));
    check("MCP child alive after client disconnect", mcpChild.exitCode === null && !mcpChild.killed,
      `exitCode=${mcpChild.exitCode} killed=${mcpChild.killed}`);
    // --- verify REST still serving after SSE churn ---
    const post2 = await fetch(`${BASE}/scrape-jobs`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ type: "imo_resolve", payload: { vessel_name: "MSC TEST" } }),
    });
    check("REST still alive after SSE churn (202)", post2.status === 202, `got ${post2.status}`);
  } finally {
    // Detach exit handler so killing MCP child doesn't process.exit us.
    mcpChild.removeAllListeners("exit");
    try { mcpChild.kill("SIGKILL"); } catch {}
    server.close();
  }

  console.log(`\n=== RESULT: ${pass} pass / ${fail} fail ===`);
  process.exit(fail === 0 ? 0 : 1);
}

main().catch((e) => { console.error("HARNESS ERROR:", e); process.exit(2); });
