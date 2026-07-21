# Decision Record

## Decision ID

0004-db-conventions-enum-text-check-utc

## Date

2026-07-21

## Status

accepted

## Context

TASK-02 dựng 10 bảng là nền cho mọi task sau import. Cần chốt trước các
convention: cách lưu enum, cách load relationship, style query, timezone, và
chính sách migration — nếu không chốt, mỗi task sẽ tự chọn một kiểu và schema
sẽ trôi (đặc biệt là ràng buộc "chỉ 1 leg active/lô" nếu chỉ enforce ở tầng
application sẽ hỏng âm thầm).

## Options Considered

1. **Enum = text + CHECK constraint** — Pros: thêm giá trị enum chỉ cần drop/
   re-add CHECK trong 1 migration thường. Cons: không có type-level enforcement
   ngoài CHECK.
2. **Native Postgres enum** — Pros: type thật. Cons: `ALTER TYPE ... ADD VALUE`
   đau đớn (không chạy trong transaction cũ, không xóa value được). **Bị loại.**
3. **Downgrade đầy đủ cho mỗi migration** — Pros: rollback được. Cons: chi phí
   viết + test downgrade không đáng cho MVP forward-only. **Bị loại.**

## Decision

- **Enum = `text` + `CheckConstraint`** (không native Postgres enum — IC§1.1);
  giá trị chuẩn khai trong `backend/app/db/enums.py`.
- **Relationship `lazy="raise"`** — cấm lazy-load ngầm trong async context;
  query 2.0-style tường minh (`select()`/`update()`).
- **Mọi `datetime` tz-aware UTC** (IC§15) — cấm naive datetime, Pydantic/DB
  validator từ chối.
- **Alembic FORWARD-ONLY** (IC§2.1) — mỗi schema change là revision mới;
  `downgrade()` để `raise NotImplementedError` hoặc `pass` kèm comment.
- **Partial unique index `uq_legs_one_active`**
  (`ON shipment_legs(shipment_id) WHERE is_active_leg`) — DB ép "chỉ 1 leg
  active/lô"; autogenerate thường KHÔNG sinh index này nên phải review/bổ tay
  file migration trước khi đánh done.

## Consequences

**Positive:**

- Thêm giá trị enum về sau là migration rẻ, không đụng `ALTER TYPE`.
- `lazy="raise"` + query tường minh: không có N+1/lazy-load surprise trong
  async session.
- Ràng buộc 1-leg-active được DB đảm bảo — insert leg active thứ 2 fail ngay
  bằng unique violation, không thành bug dữ liệu khó debug.
- UTC nhất quán: so sánh ETA/deviation dùng epoch an toàn.

**Tradeoffs:**

- Không rollback schema được — môi trường hỏng thì migrate tiến hoặc dựng lại
  DB (chấp nhận cho MVP).
- CHECK constraint phải đồng bộ tay với tuple trong `enums.py`.

## Related Stories

- `docs/stories/TASK-02-db-schema-migration-seed/`
- `docs/stories/TASK-11-imo-resolver-resolve-leg/` (mirror dựa trên leg active duy nhất)
