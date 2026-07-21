# TASK-14 — Auth OAuth Google/Microsoft + session JWT + middleware — Overview

## Status

planned

## Lane

high-risk

## Current behavior

Chưa build auth thật. TASK-03 để lại **stub development-only**: `deps.get_current_user` trả cứng user seed #1 (để `decided_by`/`verified_by` có giá trị test — chủ đích, không phải bug). WS endpoint (TASK-06) accept thẳng không kiểm cookie.

## Target behavior

- OAuth OIDC Google + Microsoft qua **Authlib 1.7.2** (`authorize_redirect`/`authorize_access_token` tự lo state + PKCE — §3.8).
- Session JWT tự phát hành (**python-jose 3.5.0**, HS256, claims `sub/role/iat/exp` — IC§10), cookie `session_token` HttpOnly + Secure(theo env) + SameSite=Lax.
- `get_current_user` thật thay stub TASK-03: thiếu/sai cookie → **401 JSON `UNAUTHENTICATED`, không redirect**.
- WS handshake verify cookie, không hợp lệ → **close 4401**.
- Frontend: `Login.tsx` 2 nút provider; `App.tsx` gọi `/auth/me` lúc mount.
- Regression: `test_auth_coverage.py` duyệt `app.routes`, assert MỌI route `/api/v1/*` có dependency `get_current_user`.

## Affected users / docs

- Mọi user demo (login bắt buộc trước khi vào app); mọi route `/api/v1/*` + `/ws`.
- `decided_by`/`verified_by` (proposals/findings) chuyển từ user stub sang user login thật.
- Docs quy chiếu: Spec §3.8, §4.7, IC§10, IC§3.2. PHẢI xong trước deploy (TASK-15).

## Non-goals

- KHÔNG refresh token (hết hạn 72h → login lại; chưa revoke-list — Known Limitation).
- KHÔNG RBAC phức tạp: chỉ 2 role `user/admin`, 403 `FORBIDDEN` chừa sẵn, chưa route admin ở MVP.
- KHÔNG MODIFY `backend/requirements.txt` — `authlib`/`python-jose` đã pin tại TASK-00.
