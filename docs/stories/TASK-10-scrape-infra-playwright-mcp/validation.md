# TASK-10 — Validation

## Status

planned

## Lane

high-risk

## Proof (theo Verify TASK-10 — smoke curl)

| # | Check | Cách chạy | Kết quả |
| --- | --- | --- | --- |
| 1 | Build sạch | `cd playwright-mcp && npm install && npm run build` | not run |
| 2 | Enqueue job | `docker compose up -d redis playwright-mcp` → `curl -XPOST localhost:3000/scrape-jobs -d '{"type":"imo_resolve","payload":{"vessel_name":"TEST"}}'` trả `{job_id}` | not run |
| 3 | Poll job | `curl localhost:3000/scrape-jobs/<id>` trả status + placeholder result | not run |
| 4 | MCP SSE | port 3001 phản hồi SSE | not run |
| 5 | Boundary IC§0.1 | grep compose/env container: KHÔNG có `DATABASE_URL`; code Node không import driver Postgres | not run |
| 6 | Contract shape | response GET khớp IC§3.3 (`status` ∈ queued/running/succeeded/failed, `error_code` đúng enum) | not run |
| 7 | Lock committed | `playwright-mcp/package-lock.json` nằm trong commit; `@playwright/mcp` = 0.0.78 exact | not run |
| 8 | Compose valid | `docker compose -f infra/docker-compose.yml config` không lỗi | not run |

## Ghi chú

- Không có nhánh thiếu-key: smoke này offline hoàn toàn (Redis + container local) — **không ghi smoke-key checklist**.
- Check 7 là gate cứng: lock không commit → không đánh [x] (xem execplan stop conditions).
- Ma trận test: xem row **TASK-10** trong `docs/TEST_MATRIX.md` (expected observation + risk flags đồng bộ với file này).
