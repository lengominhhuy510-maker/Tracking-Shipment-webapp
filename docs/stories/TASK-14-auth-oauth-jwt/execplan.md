# TASK-14 — Execution Plan

## Status

planned

## Lane

high-risk

## Goal

OAuth OIDC + JWT tự phát hành + middleware bảo vệ mọi route `/api/v1/*` và WS. PHẢI xong trước deploy (TASK-15).

## Scope (Output paths — CHỈ động vào đây)

- `backend/app/auth/oauth.py` (Authlib client Google+Microsoft)
- `backend/app/auth/jwt.py` (issue/verify session JWT — IC§10)
- `backend/app/auth/routes.py` (`/auth/login/{provider}`, `/auth/callback/{provider}`, `/auth/me`, `/auth/logout`)
- `backend/app/api/deps.py` (MODIFY: `get_current_user` thật — thay stub TASK-03)
- `backend/app/main.py` (MODIFY: SessionMiddleware + include auth router + verify WS cookie)
- `backend/app/api/ws.py` (MODIFY: verify session cookie, close 4401)
- `frontend/src/components/Login.tsx`, `frontend/src/App.tsx` (MODIFY)
- `backend/tests/test_jwt.py`, `backend/tests/test_auth_coverage.py`
- `backend/requirements.txt`: **KHÔNG MODIFY theo thiết kế** (authlib/python-jose đã pin TASK-00).

## Risk classification

- **Flags:** auth, authorization, public API/contract (mọi route `/api/v1/*` đổi hành vi từ open → protected; WS thêm close code).
- **Hard gates:** auth + authorization — coverage test bắt buộc pass, stub TASK-03 phải biến mất.

## Work phases (theo Worker Instruction Spec §14)

1. **`oauth.py`** — Authlib `OAuth` đăng ký Google + Microsoft (client_id/secret từ env, scope `email profile`, redirect `{APP_BASE_URL}/auth/callback/{provider}`).
2. **`jwt.py`** (TDD) — `issue_token(user_id, role)` (HS256, `SESSION_JWT_SECRET`, exp 72h), `verify_token(token)->claims|None`.
3. **`routes.py`** — login/callback/me/logout theo design.md; upsert users; set cookie; 302 `/`.
4. **`deps.py`** (MODIFY) — `get_current_user` thật; 401 `UNAUTHENTICATED` JSON.
5. **`main.py`** (MODIFY) — SessionMiddleware + include auth router.
6. **`ws.py`** (MODIFY) — verify cookie, close 4401.
7. **Frontend** — `Login.tsx` + `App.tsx` gọi `/auth/me`.
8. **`test_auth_coverage.py`** — duyệt `app.routes` assert mọi route `/api/v1/*` có `get_current_user`; no-cookie → 401; WS → 4401.

## Stop conditions

- **Phát sinh đổi dependency → DỪNG**: bổ sung cả `backend/requirements.txt` + `requirements.lock.txt` vào Output paths trước, rồi mới MODIFY và regenerate lock theo quy tắc Lock reproducibility — không tự cài/bump.
- Authlib API khác docstring bản pin 1.7.2 → đọc lại docstring, KHÔNG bịa tham số; bế tắc → `FAILED` + lý do.
- Còn bất kỳ route `/api/v1/*` nào thiếu `get_current_user` (coverage test fail) → KHÔNG đánh [x].
- Cần đụng file tracked ngoài Output paths → in `FAILED`, không tự sửa.
- Task vượt sức 1 context → `FAILED: TASK-14 — quá lớn, đề nghị chẻ: [...]`.
- Kết thúc = 1 commit Conventional Commits, không push.
