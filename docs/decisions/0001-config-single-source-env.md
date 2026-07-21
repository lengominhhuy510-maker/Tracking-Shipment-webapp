# Decision Record

## Decision ID

0001-config-single-source-env

## Date

2026-07-21

## Status

accepted

## Context

App có nhiều môi trường chạy (local dev, pytest từ `backend/`, docker compose)
và nhiều loại config (port, hệ số ETA, API key). Nếu cho phép nhiều file env
với fallback chain, sẽ không biết giá trị đang chạy đến từ nguồn nào — debug
config sai rất tốn thời gian, và dễ leak secret khi agent đọc/ghi nhầm file
chứa key thật.

## Options Considered

1. **Single source `.env`** — app CHỈ load `.env` ở gốc repo qua
   pydantic-settings, không fallback chain. Pros: 1 nguồn duy nhất, dễ debug,
   biến môi trường thật (docker `env_file`) vẫn override được. Cons: user phải
   tự copy template thành `.env`.
2. **Fallback chain nhiều file** (`.env.local` → `.env.devtest` → `.env`...) —
   Pros: tiện "cứ chạy là được". Cons: khó debug nguồn giá trị, thứ tự
   precedence ngầm, dễ đọc nhầm file secret. **Bị loại.**

## Decision

Chọn Option 1 — single source:

- App CHỈ load `.env` (1 nguồn, KHÔNG fallback chain). Tên biến + default
  chuẩn lấy duy nhất từ **IC§7**, khai báo qua `pydantic-settings`
  (`backend/app/config.py`, export singleton `settings`).
- **`.env.example`** = template production/runtime canonical, tracked.
- **`.env.devtest2`** = template dev/test sạch, tracked, cùng key set nhưng
  override có chủ đích `AIS_MODE=replay` (deterministic).
- **`.env.devtest`** = file key thật legacy, user-owned, gitignored — agent
  **KHÔNG đọc, KHÔNG ghi, KHÔNG echo nội dung**. Luồng chuẩn: user copy
  `.env.devtest2` → `.env` rồi tự điền secret.
- CẤM hardcode key/URL trong code — mọi thứ đi qua `settings`.

## Consequences

**Positive:**

- Luôn biết chính xác giá trị config đến từ đâu (`.env` hoặc env var thật).
- Secret thật nằm ngoài git và ngoài tầm đọc/ghi của agent.
- Template tracked đảm bảo key set đồng bộ với IC§7, test được bằng pytest.

**Tradeoffs:**

- User phải chủ động copy template + điền secret trước khi chạy live.
- Mọi biến mới đều phải khai ở IC§7 + cả 2 template — thêm 1 bước kỷ luật.

## Related Stories

- `docs/stories/TASK-14-auth-oauth-jwt/` (OAuth client secret, JWT secret qua settings)
- `docs/stories/TASK-13-email-agent/` (IMAP credential qua settings)
- `docs/stories/TASK-16-auto-forward/` (whitelist/interval qua settings, không hardcode)
