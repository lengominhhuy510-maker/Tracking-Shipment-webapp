# TASK-10 — Scrape infra: container playwright-mcp (Node) + BullMQ + Redis + REST /scrape-jobs

## Status

planned

## Lane

high-risk

## Current behavior

- `playwright-mcp/` mới chỉ có skeleton (`package.json`, `tsconfig.json`) từ TASK-00; chưa có server, chưa có queue.
- `infra/docker-compose.yml` mới có khung service `playwright-mcp` + `redis` (TASK-00), chưa hoàn chỉnh env/build.
- Backend Python chưa có hạ tầng scrape nào để gọi.

## Target behavior

Node container **2 cửa vào** (Spec §3.7):

1. **REST `/scrape-jobs`** — Express port **3000**: `POST /scrape-jobs {type:"imo_resolve",payload}` → `{job_id}` 202; `GET /scrape-jobs/:id` → `{job_id,status,result|null,error_code|null}` (IC§3.3). Job enqueue vào **BullMQ + Redis**, worker concurrency = `SCRAPE_CONCURRENCY`, mỗi job 1 browser context riêng, timeout `SCRAPE_JOB_TIMEOUT_SECONDS`.
2. **MCP SSE** — `@playwright/mcp@0.0.78` (pin exact, đã gate TASK-01, **KHÔNG bump**) chạy SSE port **3001**, song song Express — dành cho Carrier ETA Agent (TASK-12).

Job handler `imo_resolve` ở task này là **placeholder** (trả kết quả giả) — script Playwright thật thuộc TASK-11.

## Rào cứng (IC§0.1 — BLOCKING)

Container **KHÔNG có `DATABASE_URL`**, KHÔNG chạm Postgres. Job chỉ trả JSON qua `GET /scrape-jobs/:id`; Python poll + tự ghi DB. Env container chỉ gồm `REDIS_URL` + `SCRAPE_*`.

## Affected docs

- PROGRESS.md TASK-10; Spec §3.7, §6.7d; IC§0.1, IC§3.3, IC§7 (`SCRAPE_*`, `REDIS_URL`), IC§12 (hostname/port).

## Non-goals

- KHÔNG dùng `asyncio.Semaphore` thay BullMQ — MVP bắt buộc Redis + BullMQ (Semaphore chỉ là phương án ngoài MVP/scale-ahead).
- KHÔNG viết script Playwright VesselFinder thật (TASK-11).
- KHÔNG đụng `backend/requirements.txt` / `requirements.lock.txt` — task này chỉ MODIFY Node package/lock.
- KHÔNG bump version `@playwright/mcp` hay thêm dependency ngoài danh sách đã gate.
