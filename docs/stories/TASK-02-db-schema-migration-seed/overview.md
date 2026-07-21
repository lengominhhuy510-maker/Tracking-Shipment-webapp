# TASK-02 — DB models + Alembic migration + seed — Overview

## Status

planned

## Lane

high-risk

## Current behavior

Chưa build. Repo mới có scaffold TASK-00 (config, FastAPI health, docker-compose khung). Chưa có model, migration, seed nào — DB Postgres rỗng.

## Target behavior

- 10 bảng DB: 8 bảng spec §4 (`shipments`, `eta_history`, `vessel_trail`, `agent_proposals`, `research_findings`, `vessel_registry`, `users`, `shipment_legs`) + 2 bảng IC§0.2 (`env_conditions`, `processed_emails`).
- SQLAlchemy 2.x async (`Mapped[]` + `mapped_column`), enum = text + CHECK (IC§1.1), relationship `lazy="raise"`.
- Alembic migration forward-only (`downgrade()` raise `NotImplementedError` — IC§2.1), đủ index IC§2.3 — đặc biệt partial unique index `uq_legs_one_active`.
- Seed idempotent: 4 lô + 2 user theo IC§13, bắt buộc lô 3 = export C/D VNCLI→SGSIN.

## Affected users / docs

- Mọi task sau (TASK-03..17) import model từ đây — đây là task quan trọng nhất về đồng bộ: task sau thiếu cột → quay lại sửa task này, không bỏ qua leg/mirror.
- Docs quy chiếu (nguồn chân lý): PROGRESS.md TASK-02; Spec §4, IC§0.2, IC§1.1, IC§2, IC§9, IC§13.

## Non-goals

- KHÔNG build cleanup job §4.9 (STRETCH — bước 18).
- KHÔNG build logic transit/rollover (`switch_active_leg`) — chỉ schema-ahead `shipment_legs`.
- KHÔNG viết CRUD API (TASK-03), không AIS worker (TASK-04).
- KHÔNG hỗ trợ downgrade migration (forward-only policy).
