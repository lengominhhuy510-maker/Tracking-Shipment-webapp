# TASK-14 — Design

## Status

planned

## Lane

high-risk

## Flow (Spec §3.8 + IC§10)

1. `GET /auth/login/{provider}` → Authlib `authorize_redirect` (Authlib tự sinh state + PKCE — KHÔNG tự implement, KHÔNG bịa tham số; đọc docstring bản pin 1.7.2).
2. `GET /auth/callback/{provider}` → `authorize_access_token` verify state+code → id_token → email/name/provider_sub → upsert `users` theo UNIQUE `(provider, provider_sub)` (§4.7) → `issue_token` → set cookie → **302 về `/`** (SPA shell công khai).
3. `GET /auth/me` → đọc cookie → verify → `{id,email,name,role,provider}` hoặc 401. `GET /auth/logout` → xóa cookie.
4. `/auth/*` ở root (KHÔNG prefix `/api/v1`) — khớp redirect URI đã đăng ký (IC§3.1).

## Interface contract

- **JWT (IC§10):** claims `{sub: users.id, role, iat, exp}`; `exp = iat + SESSION_JWT_EXPIRE_HOURS` (72h); HS256, secret `SESSION_JWT_SECRET`. Không refresh token.
- **Cookie:** `session_token`, `Path=/`, `Max-Age=259200`, `HttpOnly; SameSite=Lax`, `Secure` theo `COOKIE_SECURE` env.
- **Middleware:** dependency `get_current_user` — đọc cookie → verify → load `users` → `request.state.user`. Thiếu/sai/hết hạn → **401 `UNAUTHENTICATED` JSON envelope IC§3.1, không server-redirect** (SPA tự điều hướng). 403 `FORBIDDEN` chừa sẵn cho admin.
- **WS (`/ws`):** handshake đọc cookie `session_token` → verify → không hợp lệ **close 4401** (thay comment TASK-06).
- **SessionMiddleware** thêm ở `main.py` — chỉ phục vụ cookie handshake của Authlib (tên mặc định).

## Quyết định chốt (từ PROGRESS.md)

- Version pin: `authlib==1.7.2`, `python-jose[cryptography]==3.5.0` — đã pin TASK-00, TASK-14 dùng lại, KHÔNG bump. Experimental → đọc docstring bản đã cài trước khi dùng.
- Stub `get_current_user` TASK-03 phải **biến mất hoàn toàn** — mọi route dùng cùng 1 dependency thật.
- Auth coverage regression [v0.9.12]: `test_auth_coverage.py` duyệt `app.routes` assert mọi route `/api/v1/*` có `get_current_user`; endpoint không cookie → 401; WS không cookie → 4401.
- Frontend: `Login.tsx` (2 nút → `/auth/login/google|microsoft`), `App.tsx` mount gọi `/auth/me` → chưa login render Login, có thì render app + tên/role.

## Chi tiết đầy đủ

Trỏ về Spec §3.8, §4.7, IC§10, IC§3.1/3.2 — không copy lại.
