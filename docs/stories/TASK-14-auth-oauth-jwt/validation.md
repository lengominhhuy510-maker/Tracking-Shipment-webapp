# TASK-14 — Validation

## Status

planned

## Lane

high-risk

## Proof strategy

Trỏ tới row **TASK-14** trong `docs/TEST_MATRIX.md`.

Theo mục Verify Spec §14: **TDD** cho JWT + auth coverage (offline, không cần key); **smoke OAuth thật là key-gated** — cần OAuth client_id/secret + redirect URI đăng ký `localhost:1476`. Thiếu key → PASS cấu trúc + ghi smoke-key checklist, KHÔNG coi là demo end-to-end đã chạy. **Tất cả check dưới đây: not run — chưa claim pass.**

## Checks — TDD/offline

| # | Check | Lệnh / cách kiểm | Trạng thái |
| --- | --- | --- | --- |
| 1 | JWT round-trip: issue→verify; hết hạn→None; sai secret→None | `pytest tests/test_jwt.py -v` | not run |
| 2 | Auth coverage: mọi route `/api/v1/*` có `get_current_user` | `pytest tests/test_auth_coverage.py -v` | not run |
| 3 | Endpoint không cookie → 401 JSON `UNAUTHENTICATED` (không redirect) | trong test_auth_coverage | not run |
| 4 | WS không cookie → close 4401 | trong test_auth_coverage | not run |
| 5 | Stub TASK-03 biến mất — `deps.get_current_user` không còn trả cứng user seed | code review + coverage test | not run |

## Checks — smoke OAuth thật (KEY-GATED)

| # | Check | Cách kiểm | Trạng thái |
| --- | --- | --- | --- |
| 6 | Login Google thật: nút login → OAuth → callback set cookie `session_token` | mở app, login tay | not run |
| 7 | `/auth/me` trả user thật sau login | browser / curl kèm cookie | not run |
| 8 | `curl localhost:1476/api/v1/shipments` không cookie → 401 JSON | curl | not run |
| 9 | WS không cookie → close 4401 (client thật) | wscat / browser devtools | not run |

## Smoke-key checklist

Nếu thiếu OAuth client_id/secret lúc chạy task: đánh [x] mức cấu trúc và ghi vào Session Log Spec:

```
cần smoke lại: TASK-14 (OAuth Google/Microsoft client_id/secret + redirect URI localhost:1476)
```

Orchestrator chạy lại các check 6–9 sau khi có key thật (trước demo — xem thêm TASK-17 checklist thủ công).
