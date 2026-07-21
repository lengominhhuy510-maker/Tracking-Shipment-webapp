# TASK-10 — Design

## Status

planned

## Lane

high-risk

## Contract (trỏ nguồn, không copy dài)

- **REST /scrape-jobs:** shape request/response, enum status (`queued/running/succeeded/failed`), `error_code` khớp enum onboarding_error — **IC§3.3** là normative.
- **Port/hostname:** REST 3000, MCP SSE 3001, hostname `playwright-mcp` — **IC§12**.
- **Env:** `SCRAPE_CONCURRENCY`, `SCRAPE_JOB_TIMEOUT_SECONDS`, `REDIS_URL` — **IC§7**.
- **2 cửa vào:** REST cho IMO Resolver deterministic (TASK-11), MCP SSE cho Carrier ETA agentic (TASK-12) — **Spec §3.7**. Hai cửa KHÔNG trộn: /scrape-jobs chỉ nhận `type==="imo_resolve"`.

## Flow

```
Python (TASK-11 scrape_client)
  → POST http://playwright-mcp:3000/scrape-jobs {type,payload}   [zod validate]
  → BullMQ Queue (Redis) → Worker (concurrency SCRAPE_CONCURRENCY)
  → jobs/imo_resolve.ts (placeholder ở task này) → result JSON
  ← GET /scrape-jobs/:id  {status, result|null, error_code|null}
Python poll → Python TỰ ghi DB (Node không bao giờ ghi)
```

MCP SSE (port 3001) chạy song song trong cùng process/container — `@playwright/mcp@0.0.78`, đọc README bản pin trước khi cấu hình (package experimental, KHÔNG bịa API).

## Quyết định trích từ PROGRESS.md

- **BullMQ bắt buộc** (§6.7d: concurrency 2-3, Python↔Node = HTTP) — cap số browser context đồng thời; Chromium do container quản lý.
- **Security boundary IC§0.1:** Node là sandbox scrape thuần — không credential DB, blast radius khi bị compromise chỉ là Redis queue.
- **Dockerfile** base `mcr.microsoft.com/playwright` (có sẵn Chromium+libs); comment `docker buildx --platform linux/amd64`.
- **Lock reproducibility:** MODIFY `playwright-mcp/package.json` ⇒ PHẢI regenerate + commit `playwright-mcp/package-lock.json`; `npm ci` chỉ chạy với lock đã commit.

## Files

`playwright-mcp/src/server.ts` (Express), `src/queue.ts` (BullMQ), `src/jobs/imo_resolve.ts` (placeholder), `src/mcp.ts` (SSE 3001), `Dockerfile`, `README.md`; MODIFY `package.json` + `package-lock.json`, `infra/docker-compose.yml` (hoàn chỉnh playwright-mcp + redis, env KHÔNG có `DATABASE_URL`).
