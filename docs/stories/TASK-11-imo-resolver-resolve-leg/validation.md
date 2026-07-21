# TASK-11 — Validation

## Status

planned

## Lane

high-risk

## Proof (theo Verify TASK-11 — TDD mirror là lõi)

| # | Check | Cách chạy | Kết quả |
| --- | --- | --- | --- |
| 1 | **TDD mirror (lõi)** | `pytest tests/test_leg_service.py -v`: resolve_leg trên leg active pending → CẢ leg lẫn shipments có imo/mmsi/resolved khớp nhau | not run |
| 2 | TDD fallback | `mark_leg_manual` → manual_required + onboarding_error mirror đúng lên shipments | not run |
| 3 | Atomicity | mirror + leg update cùng 1 transaction (test rollback: fail giữa chừng → cả hai không ghi) | not run |
| 4 | Smoke resolve | `docker compose up -d db redis playwright-mcp` → POST lô mới không imo → log scrape → `SELECT onboarding_status,imo FROM shipments/shipment_legs` khớp (resolved hoặc manual_required) | not run |
| 5 | Tàu trùng tên | 2 kết quả cùng tên khác voyage → lọc đúng bằng voyage/flag (không LLM) | not run |
| 6 | error_code mapping | captcha/not_found/ambiguous/timeout/login → mark_leg_manual với đúng mã | not run |
| 7 | Cache hit | lô có vessel trong `vessel_registry` → resolve_leg 'cache_hit', KHÔNG gọi scrape | not run |
| 8 | Signal | sau resolve: ResubscribeSignal bắn + broadcast_onboarding_update được gọi | not run |

## Ghi chú

- Check 1-3 là TDD bắt buộc (test fail → code → pass) — weak-proof flag nghĩa là smoke VesselFinder thật (check 4-5) KHÔNG thay thế được TDD mirror.
- Smoke 4-5 phụ thuộc VesselFinder live (captcha/selector đổi) — nếu bị chặn, ghi rõ fallback manual_required hoạt động đúng là đạt; không tính smoke-key (không cần key) nhưng ghi chú kết quả live vào Session Log.
- Ma trận test: xem row **TASK-11** trong `docs/TEST_MATRIX.md` (expected observation + risk flags đồng bộ với file này).
