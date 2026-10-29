# TASK-02 — Validation

## Status

planned

## Lane

high-risk

## Proof strategy

Theo mục Verify Spec §02: TDD cho phần model/metadata chạy được offline; schema inspection + psql check cần Postgres thật (`docker compose -f infra/docker-compose.yml up -d db`). **Tất cả check dưới đây: not run — chưa claim pass.**

## Checks

| # | Check | Lệnh / cách kiểm | Trạng thái |
| --- | --- | --- | --- |
| 1 | Migration lên head tạo 10 bảng | `cd backend && alembic upgrade head` | not run |
| 2 | Seed 4 lô + 2 user không lỗi | `python -m app.db.seed` | not run |
| 3 | Seed idempotent | chạy seed lần 2 → vẫn 4 lô + 2 user, không lỗi | not run |
| 4 | Unit/model tests | `pytest tests/test_models.py tests/test_schema_inspection.py -v` | not run |
| 5 | 10 bảng tồn tại | `psql ... -c "\dt"` thấy đủ 10 bảng | not run |
| 6 | Số lô seed | `SELECT count(*) FROM shipments` = 4 | not run |
| 7 | **Partial index có thật** | `psql ... -c "\di uq_legs_one_active"` phải ra 1 dòng — 0 dòng = migration thiếu, KHÔNG đánh [x] | not run |
| 8 | DB ép 1 leg active/lô | INSERT 2 dòng `shipment_legs` cùng `shipment_id`, cùng `is_active_leg=true` → unique violation | not run |
| 9 | CHECK enum reject | insert giá trị enum sai → lỗi constraint (trong test_schema_inspection) | not run |
| 10 | FK ON DELETE đúng | inspect: con shipments = CASCADE, tới users = RESTRICT | not run |

## Ghi chú

- `test_schema_inspection.py` dùng marker/skip khi không có Postgres — KHÔNG chạy trên SQLite.
- Downgrade: forward-only, không có check downgrade (chủ đích, IC§2.1).
- Không cần key ngoài — task này offline-deterministic hoàn toàn, không có mục smoke-key checklist.
- Ma trận test: xem row **TASK-02** trong `docs/TEST_MATRIX.md` (expected observation + risk flags đồng bộ với file này).
