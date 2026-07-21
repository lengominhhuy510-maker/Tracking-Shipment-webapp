# Demo Giám Sát Lô Hàng

Shipment monitoring demo — theo dõi lô hàng container theo thời gian thực (AIS, thời tiết, thủy triều, ETA engine, AI agents).

## Monorepo layout

| Thư mục | Nội dung |
|---|---|
| `backend/` | Python FastAPI + AIS worker + AG2 agents + email agent |
| `frontend/` | React + Vite + Leaflet |
| `playwright-mcp/` | Node scrape service (Playwright MCP) |
| `infra/` | `docker-compose.yml`, `Caddyfile` |

## Env setup

```bash
cp .env.devtest2 .env
# rồi tự điền các secret/credential còn trống trong .env
```

- `.env.example` — template canonical production/runtime (IC§7, `AIS_MODE=live`).
- `.env.devtest2` — template dev/test sạch (`AIS_MODE=replay`, deterministic).
- **Không đụng `.env.devtest`** — file key thật user-owned, đã gitignore.

## Dev commands

```bash
# Backend (port 1476)
cd backend && uvicorn app.main:app --reload --port 1476

# Frontend (Vite trên 5173, proxy /api và /ws → localhost:1476)
cd frontend && npm run dev
```

## Docker

```bash
docker compose -f infra/docker-compose.yml up --build
```

## Tests

```bash
cd backend && pytest
cd frontend && npx vitest run
```

## Tài liệu

- [Spec_Demo_GiamSatLoHang-v0_9_19.md](Spec_Demo_GiamSatLoHang-v0_9_19.md) — spec chính
- [Interface-Contract_v0.9.9.md](Interface-Contract_v0.9.9.md) — interface contract (env, API, DB)
- [PROGRESS.md](PROGRESS.md) — task tracker
- [ORCHESTRATOR_PROMPT.md](ORCHESTRATOR_PROMPT.md) — orchestrator prompt
