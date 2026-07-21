# Decision Record

## Decision ID

0002-language-boundary-python-node

## Date

2026-07-21

## Status

accepted

## Context

Hệ có 2 runtime: Python (FastAPI backend) và Node (container `playwright-mcp`
chạy scrape + MCP server). Cả hai đều có thể chạm Postgres và Redis về mặt kỹ
thuật — nếu không vẽ ranh giới cứng, sẽ có 2 writer vào DB, mất single source
of truth cho định danh tàu (imo/mmsi/onboarding_status) và mirror leg→shipment
sẽ lệch âm thầm.

## Options Considered

1. **Ranh giới cứng theo ngôn ngữ** — Python không chạm Redis; Node không chạm
   Postgres. Pros: 1 writer duy nhất cho DB, dễ reason, container Node không
   cần credential DB. Cons: Python phải poll kết quả job qua HTTP.
2. **Node ghi thẳng DB** sau khi scrape xong — Pros: ít round-trip. Cons: 2
   writer, mirror logic (`resolve_leg`) phải duplicate sang TypeScript, mất
   single source of truth. **Bị loại.**

## Decision

Chọn Option 1:

- **Python KHÔNG chạm Redis** — BullMQ/Redis là chi tiết nội bộ của Node.
- **Node KHÔNG chạm Postgres** — container `playwright-mcp` không có
  `DATABASE_URL` trong env (IC§0.1, enforce ở docker-compose).
- Giao tiếp Python↔Node đúng 2 cửa: **HTTP REST `/scrape-jobs`** (IMO Resolver
  deterministic — POST enqueue, GET poll kết quả JSON) và **MCP SSE** port 3001
  (Carrier ETA agentic).
- Mọi ghi định danh tàu (imo/mmsi/onboarding_status + mirror lên `shipments`)
  đi qua `resolve_leg()` phía Python (`leg_service.py`) — Node chỉ trả kết quả
  JSON qua job result.

## Consequences

**Positive:**

- Postgres có đúng 1 writer (Python); mirror leg→shipment nằm trong 1
  transaction, 1 chỗ code.
- Container Node không giữ credential DB — bề mặt tấn công/blast radius nhỏ hơn.
- Contract `/scrape-jobs` (IC§3.3) test được độc lập bằng curl.

**Tradeoffs:**

- Python phải poll job status qua HTTP (3s interval, timeout 120s) thay vì
  nhận callback trực tiếp.
- Kết quả scrape đi qua serialize/validate Pydantic 2 lần (Node trả JSON,
  Python validate `IMOResolverResult`).

## Related Stories

- `docs/stories/TASK-10-scrape-infra-playwright-mcp/`
- `docs/stories/TASK-11-imo-resolver-resolve-leg/`
- `docs/stories/TASK-12-carrier-eta-agent/`
