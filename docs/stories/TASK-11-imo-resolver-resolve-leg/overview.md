# TASK-11 — IMO Resolver (script Playwright cứng) + client Python + resolve_leg()

## Status

planned

## Lane

high-risk

## Current behavior

- `playwright-mcp/src/jobs/imo_resolve.ts` là placeholder (TASK-10) trả kết quả giả.
- TASK-03 `POST /shipments`: mirror imo/mmsi inline + comment `# TASK-11 thay bằng resolve_leg()`; `retry-onboarding` stub 202; chưa có enqueue scrape thật.
- Chưa có `scrape_client.py`, chưa có `leg_service.py`.

## Target behavior

1. **`jobs/imo_resolve.ts`** (MODIFY) — script Playwright **deterministic, KHÔNG LLM**: mở VesselFinder, điền vessel_name, đọc bảng (selector cố định), lọc trùng tên bằng voyage/flag trong code. Trả `IMOResolverResult` (IC§4.1) qua job result; lỗi → `error_code` ∈ `captcha/not_found/ambiguous/timeout/login`. KHÔNG ghi DB (IC§0.1).
2. **`scrape_client.py`** — `resolve_imo(...)`: POST `http://playwright-mcp:3000/scrape-jobs` → poll GET mỗi **3s**, timeout **120s** → validate Pydantic `IMOResolverResult`; fail trả error_code.
3. **`leg_service.py`** — `resolve_leg()` = **nguồn ghi định danh tàu DUY NHẤT** toàn hệ: UPDATE `shipment_legs` + NẾU `is_active_leg` thì mirror lên `shipments` — **CÙNG 1 transaction**. Fallback `mark_leg_manual(leg_id, error_code)` (manual_required + mirror). Sau resolve/mark → bắn `ResubscribeSignal` + `broadcast_onboarding_update`.
4. **`shipments.py`** (MODIFY) — POST tạo lô không imo → check cache `vessel_registry` TRƯỚC khi scrape (hit → `resolve_leg` với `'cache_hit'`), miss → background scrape; `resolve-manual` → `resolve_leg(..., 'manual')`; `retry-onboarding` → re-scrape thật.

## Affected docs

- Spec §11; Spec §6.7a, §4.6, §4.8/§4.1; IC§0.1, IC§3.3, IC§4.1, IC§9.

## Non-goals

- KHÔNG dùng LLM trong resolver (agentic là TASK-12, cửa khác).
- KHÔNG build `resolve_and_activate_leg` / rollover chain (TASK-13) hay `switch_active_leg` (STRETCH).
- KHÔNG MODIFY dependency/lock nào — dùng httpx/Playwright đã có.
- Node KHÔNG ghi DB — mọi ghi qua Python `resolve_leg`.
