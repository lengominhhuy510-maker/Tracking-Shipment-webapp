# TASK-02 — Design

## Status

planned

## Lane

high-risk

## Data model

10 bảng — cột 8 bảng gốc lấy đúng Spec §4.1–4.8; 2 bảng mới theo IC§2.2:

- `env_conditions` (bảng 9): 1 dòng/lô, PK = `shipment_id` FK CASCADE; wind/wave/current + `weather_fetched_at`, `tide_extremes` jsonb + station metadata + `tide_fetched_at`.
- `processed_emails` (bảng 10): PK `message_id`, `outcome` CHECK 4 giá trị, `unmatched_containers` jsonb + 3 cột trace [v0.9.10-p2]: `imap_uid bigint NULL`, `imap_folder text NULL`, `seen_set_at timestamptz NULL`.

## Quyết định chốt (từ Spec + IC)

- **Stack:** SQLAlchemy 2.x async (`asyncpg`) + Alembic; query 2.0-style tường minh (IC§2.1).
- **Enum = text + CHECK** (IC§1.1), KHÔNG Postgres ENUM type. Giá trị ASCII không dấu (`trung_binh`, `thap`). Enum constants gom vào `enums.py` (mỗi enum 1 tuple).
- **`lazy="raise"`** cho mọi relationship — cấm lazy-load ngầm.
- **FK ON DELETE** (IC§2.4): con của `shipments` = CASCADE; FK tới `users` (`decided_by`, `verified_by`) = RESTRICT.
- **Migration forward-only** (IC§2.1): `downgrade()` raise `NotImplementedError`; mỗi schema change = revision mới.
- **Index bắt buộc** (IC§2.3), trọng yếu nhất: `CREATE UNIQUE INDEX uq_legs_one_active ON shipment_legs(shipment_id) WHERE is_active_leg` — DB ép "chỉ 1 leg active/lô". Autogenerate thường KHÔNG sinh partial unique index → phải review/bổ tay trong `0001_init.py`. Kèm `uq_users_provider_sub`, `ix_shipments_mmsi ... WHERE mmsi IS NOT NULL`, `uq_proposals_email_shipment ... WHERE shipment_id IS NOT NULL`.

## Seed (IC§13)

- 4 lô + 2 user, upsert/idempotent. Ba mục tiêu cùng 1 script, khác `.env`: (a) offline-deterministic (`AIS_MODE=replay` + fixture, mặc định test/CI); (b) live-integration (`DEV_SEED_VESSEL_*` + key thật); (c) demo (điền tàu thật trước ngày demo).
- BẮT BUỘC lô 3 = **export C/D VNCLI→SGSIN** (export×CIF → auto_email). Lô 1+4 cùng vessel_name khác voyage.
- Nhánh lô #1: thiếu NAME → placeholder resolved; NAME+VOYAGE+IMO+MMSI → resolved shortcut; chỉ NAME+VOYAGE → pending chờ resolver.
- User seed: `admin@demo` (admin/google) + `user@demo` (user), upsert theo `(provider, provider_sub)`.

## Chi tiết đầy đủ

Trỏ về Spec §4, IC§0.2, IC§1.1, IC§2.2–2.4, IC§13 — không copy lại DDL ở đây.
