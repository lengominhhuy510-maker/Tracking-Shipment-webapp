# playwright-mcp

Node container hạ tầng scrape — **2 cửa vào** (Spec §3.7):

1. **REST `/scrape-jobs`** (Express, port **3000**) — cửa cho IMO Resolver deterministic (TASK-11). Enqueue job vào BullMQ + Redis, worker chạy concurrency `SCRAPE_CONCURRENCY`, mỗi job có browser context riêng, timeout `SCRAPE_JOB_TIMEOUT_SECONDS`.
2. **MCP SSE** (`@playwright/mcp@0.0.78`, port **3001**) — cửa cho Carrier ETA Agent (TASK-12). Chạy song song Express trong cùng container.

## Ranh giới cứng (IC§0.1 — BLOCKING)

Container này **KHÔNG có `DATABASE_URL`** và **KHÔNG bao giờ chạm Postgres**. Kết quả job chỉ nằm trong Redis job state; Python poll qua `GET /scrape-jobs/:id` rồi **tự ghi DB** (mọi ghi định danh tàu đi qua `resolve_leg()` phía Python — xem `docs/decisions/0002`). Env container chỉ gồm `REDIS_URL` + `SCRAPE_*` + `MCP_SSE_PORT`.

## Contract REST (IC§3.3)

```
POST /scrape-jobs   {"type":"imo_resolve","payload":{...}}  → 202 {"job_id":"..."}
GET  /scrape-jobs/:id                                        → 200 {"job_id","status","result"|null,"error_code"|null}
```

- `status` ∈ `queued` | `running` | `succeeded` | `failed`.
- `error_code` khớp enum `onboarding_error` (IC§1.1): `captcha` | `not_found` | `ambiguous_name` | `timeout` | `login_required`.
- `/scrape-jobs` **chỉ** nhận `type==="imo_resolve"` (Carrier ETA đi cửa MCP riêng, hai cửa không trộn).

Job handler `imo_resolve` hiện là **placeholder** trả kết quả giả đúng shape `IMOResolverResult` (IC§4.1) — script Playwright VesselFinder thật thuộc **TASK-11**.

## Env (IC§7)

| Biến | Default | Ý nghĩa |
|---|---|---|
| `REDIS_URL` | `redis://redis:6379/0` | BullMQ connection (chỉ Node dùng) |
| `SCRAPE_REST_PORT` | `3000` | Port Express REST |
| `MCP_SSE_PORT` | `3001` | Port MCP SSE |
| `SCRAPE_CONCURRENCY` | `2` | Số job (browser context) đồng thời |
| `SCRAPE_JOB_TIMEOUT_SECONDS` | `90` | Timeout mỗi job |

## Chạy

Trong compose (khuyến nghị — có sẵn Redis):

```bash
docker compose -f infra/docker-compose.yml up -d redis playwright-mcp
curl -XPOST localhost:3000/scrape-jobs -H 'content-type: application/json' \
  -d '{"type":"imo_resolve","payload":{"vessel_name":"TEST"}}'
# → {"job_id":"1"}
curl localhost:3000/scrape-jobs/1
# → {"job_id":"1","status":"succeeded","result":{...},"error_code":null}
```

Build local:

```bash
npm ci
npm run build   # tsc → dist/
npm start        # node dist/server.js (REST 3000 + MCP SSE 3001 + BullMQ worker)
```

## Build image

Base `mcr.microsoft.com/playwright` (đã có Chromium + OS libs). Build cho host amd64:

```bash
docker buildx build --platform linux/amd64 -t playwright-mcp ./playwright-mcp
```

## Version pin

`@playwright/mcp@0.0.78` (exact) đã gate ở TASK-01 — **KHÔNG bump**. Mọi thay đổi `package.json` phải regenerate + commit `package-lock.json` (`npm ci` chỉ chạy với lock đã commit).
