# TASK-10 — Execution Plan

## Status

planned

## Lane

high-risk

## Goal

Dựng hạ tầng scrape Node 2 cửa (REST /scrape-jobs + MCP SSE) với BullMQ + Redis, đúng ranh giới IC§0.1 (không DB), sẵn sàng cho TASK-11 (job thật) và TASK-12 (cửa MCP).

## Scope — Output paths (đúng PROGRESS.md, CHỈ động vào đây)

- `playwright-mcp/package.json` (MODIFY: deps), `playwright-mcp/package-lock.json` (PHẢI commit), `playwright-mcp/tsconfig.json`
- `playwright-mcp/src/server.ts`, `src/queue.ts`, `src/jobs/imo_resolve.ts` (placeholder), `src/mcp.ts`
- `playwright-mcp/Dockerfile`
- `infra/docker-compose.yml` (MODIFY)
- `playwright-mcp/README.md`

## Risk classification

- **Lane:** high-risk. **Risk flags:** external systems (Chromium/Playwright/Redis), public contract (REST /scrape-jobs là contract Python↔Node — IC§3.3 normative), audit/security (security boundary không-DB).
- **Hard gate:** external provider infra + security boundary — vi phạm IC§0.1 (thêm DATABASE_URL / Node ghi DB) là fail cứng, không thương lượng.

## Work phases (theo Worker Instruction TASK-10)

1. Đọc Spec §3.7, §6.7d, IC§3.3, IC§12, IC§7. Đọc README `@playwright/mcp@0.0.78` bản pin.
2. `package.json`: deps `express`, `bullmq`, `playwright`, `@playwright/mcp@0.0.78` (exact), `zod`; script `build`/`start`. Regenerate lock.
3. `queue.ts`: Queue + Worker (concurrency `SCRAPE_CONCURRENCY`), job timeout `SCRAPE_JOB_TIMEOUT_SECONDS`, mỗi job 1 context riêng.
4. `server.ts`: Express 3000, POST validate zod (chỉ `type==="imo_resolve"`) → 202 `{job_id}`; GET /:id → `{job_id,status,result,error_code}`.
5. `jobs/imo_resolve.ts`: placeholder trả kết quả giả + comment rõ "script thật TASK-11".
6. `mcp.ts`: khởi động MCP SSE port 3001 song song Express.
7. `Dockerfile` (base mcr.microsoft.com/playwright, build TS) + docker-compose MODIFY (env chỉ `REDIS_URL`+`SCRAPE_*`, KHÔNG `DATABASE_URL`) + README.
8. Verify (xem validation.md) → 1 commit Conventional Commits.

## Stop conditions

- `package-lock.json` không regenerate/commit được → **KHÔNG đánh [x]** (vi phạm Lock reproducibility — lock không được miễn trừ scope).
- Phát hiện cần `DATABASE_URL` hoặc Node ghi DB để "cho tiện" → DỪNG, in FAILED (vi phạm IC§0.1 BLOCKING).
- API `@playwright/mcp@0.0.78` khác giả định SSE (transport/handshake đổi) → DỪNG, đối chiếu kết quả spike_mcp TASK-01, không bịa API, không tự bump version.
- Cần đụng file tracked ngoài Output paths → in FAILED + lý do.
- Task vượt sức 1 context (sắp auto-compaction) → in `FAILED: TASK-10 — quá lớn, đề nghị chẻ: [...]`.
