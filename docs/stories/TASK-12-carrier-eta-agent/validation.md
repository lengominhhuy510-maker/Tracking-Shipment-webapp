# TASK-12 — Validation

## Status

planned

## Lane

high-risk

## Proof (theo Verify TASK-12 — mock + nonblocking regression là lõi)

Trỏ tới row **TASK-12** trong `docs/TEST_MATRIX.md`.

| # | Check | Cách chạy | Kết quả |
| --- | --- | --- | --- |
| 1 | Mock service | `pytest tests/test_carrier_eta_service.py -v`: mock MCP trả trang giả → ghi `eta_original` + `eta_original_source='carrier_scrape'` + `eta_history(source='original')` | not run |
| 2 | **Nonblocking regression (acceptance criterion bắt buộc)** | `pytest tests/test_carrier_eta_nonblocking.py -v`: mock MCP/LLM raise → shipment KHÔNG chuyển `manual_required`, vẫn `resolved`; `eta_current` không đổi; lô chỉ có IMO/MMSI (thiếu eta_original) vẫn được AIS tracking bình thường | not run |
| 3 | Boundary import | grep: chỉ `browser_agent_client.py` import package `mcp`; agent/service không import trực tiếp | not run |
| 4 | eta_current untouched | assert code path service không có write nào tới `eta_current` (test + review) | not run |
| 5 | Lock | `requirements.lock.txt` regenerate + commit; `mcp==1.12.4`, AG2 đúng bản gate, không dependency mới | not run |
| 6 | Smoke tay (key-gated) | cần LLM key + playwright-mcp up: trigger onboarding lô carrier Maersk/MSC/ONE → log agent thao tác → `SELECT eta_original,eta_original_source` = carrier_scrape (hoặc fallback log đúng nếu hãng chặn — chấp nhận, đúng thiết kế) | not run |

## Ghi chú

- Check 6 là **smoke key-gated**: thiếu LLM key → PASS cấu trúc (check 1-5) + ghi Session Log `cần smoke lại: TASK-12 (LLM key)` theo Smoke-key checklist toàn cục.
- Task `[x]` ở mức cấu trúc KHÔNG đồng nghĩa demo end-to-end chạy — orchestrator chạy lại check 6 khi có key thật.
- Không auto-retry vô hạn: fail 1 lần → log + fallback nhập tay (đường chính) — retry chỉ khi user bấm lại.
