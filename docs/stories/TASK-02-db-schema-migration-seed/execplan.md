# TASK-02 — Execution Plan

## Status

planned

## Lane

high-risk

## Goal

10 bảng DB + Alembic migration forward-only + seed 4 lô/2 user idempotent — nền cho mọi task sau import.

## Scope (Output paths — CHỈ động vào đây)

- `backend/app/db/base.py` (engine async, session factory, `Base`)
- `backend/app/db/models.py` (10 model)
- `backend/app/db/enums.py` (constant tuple + CHECK — IC§1.1)
- `backend/alembic.ini`, `backend/migrations/` (toàn bộ scaffold `alembic init`: `env.py`, `script.py.mako`, `README`, `versions/0001_init.py`)
- `backend/app/db/seed.py`
- `backend/tests/test_models.py`, `backend/tests/test_schema_inspection.py`
- `requirements.lock.txt` (sinh sau khi verify pass TASK-00)

## Risk classification

- **Flags:** data model, migration, multi-domain (mọi task sau phụ thuộc schema này).
- **Hard gates:** data model + migration — thay đổi schema phải qua review; partial unique index thiếu = fail gate.

## Work phases (theo Worker Instruction Spec §02)

1. **`enums.py`** — mỗi enum 1 tuple đúng IC§1.1 (giá trị không dấu).
2. **`base.py`** — `create_async_engine(settings.DATABASE_URL)`, `async_sessionmaker(expire_on_commit=False)`, `Base(DeclarativeBase)`.
3. **`models.py`** — 10 model SQLAlchemy 2.x; CHECK cho từng enum cột; `lazy="raise"`; FK CASCADE/RESTRICT đúng IC§2.4; `processed_emails` gồm 3 cột trace imap.
4. **Alembic** — init + sửa `env.py` async engine + `target_metadata`; tạo `0001_init.py` bằng autogenerate NHƯNG review/bổ tay từng index IC§2.3. `downgrade()` raise `NotImplementedError` (forward-only).
5. **`seed.py`** — 4 lô + 2 user theo IC§13, upsert idempotent, lô 3 export C/D VNCLI→SGSIN, các nhánh DEV_SEED_VESSEL_*.
6. **Tests** — `test_models.py` (metadata 10 bảng, insert/query SQLite async, CHECK reject); `test_schema_inspection.py` (Postgres thật, marker/skip nếu không có).

## Stop conditions

- **Partial unique index `uq_legs_one_active` KHÔNG có dòng `WHERE is_active_leg` trong `0001_init.py` → KHÔNG đánh [x]**, sửa migration trước.
- Cần đụng file tracked ngoài Output paths → in `FAILED` + lý do, không tự sửa.
- Task vượt sức 1 context (sắp auto-compaction) → `FAILED: TASK-02 — quá lớn, đề nghị chẻ: [...]`.
- Task sau phát hiện thiếu cột → quay lại sửa TASK-02, KHÔNG ghi tắt bỏ qua leg/mirror.
- Kết thúc = 1 commit Conventional Commits, không push.
