# TASK-11 — Execution Plan

## Status

planned

## Lane

high-risk

## Goal

Script Playwright deterministic tra VesselFinder + client Python poll + `resolve_leg()` là nguồn ghi định danh tàu duy nhất (mirror atomic), thay toàn bộ inline/stub TASK-03.

## Scope — Output paths (đúng Spec, CHỈ động vào đây)

- `playwright-mcp/src/jobs/imo_resolve.ts` (MODIFY: script Playwright thật)
- `backend/app/services/scrape_client.py`
- `backend/app/services/leg_service.py`
- `backend/app/api/shipments.py` (MODIFY)
- `backend/tests/test_leg_service.py`

## Risk classification

- **Lane:** high-risk. **Risk flags:** external systems (VesselFinder scrape — selector/captcha đổi ngoài tầm kiểm soát), data model (mirror leg↔shipments, nguồn ghi duy nhất), weak proof (scrape thật không deterministic — proof lõi phải là TDD mirror, không phải smoke).
- **Hard gate:** external provider + data integrity — mirror lệch transaction là fail cứng.

## Work phases (theo Worker Instruction TASK-11)

1. Đọc Spec §6.7a, §4.6, §4.8/§4.1; IC§0.1, IC§3.3, IC§4.1, IC§9.
2. **TDD trước:** viết `test_leg_service.py` fail — resolve_leg → leg + shipments cùng imo/mmsi/resolved; mark_leg_manual → manual_required + error mirror.
3. `leg_service.py`: `resolve_leg(session, leg_id, imo, mmsi, resolved_via)` + `mark_leg_manual` đúng pseudo-code §6.7a, 1 transaction; bắn ResubscribeSignal + `broadcast_onboarding_update` (import từ `app.services.broadcast`, KHÔNG stub cục bộ) → test pass.
4. `scrape_client.py`: POST + poll 3s/timeout 120s, validate `IMOResolverResult`, error mapping.
5. `jobs/imo_resolve.ts`: thay placeholder bằng script Playwright cứng (selector cố định, lọc voyage/flag, error_code 5 loại), KHÔNG ghi DB.
6. `shipments.py`: cache `vessel_registry` trước scrape; background task không block response; nối resolve-manual/retry-onboarding vào resolve_leg/scrape_client thật.
7. Verify (validation.md) → 1 commit.

## Stop conditions

- Test mirror (bước 2-3) không pass → KHÔNG tiếp sang scrape, KHÔNG đánh [x].
- Cần thêm cột DB mà schema TASK-02 thiếu → DỪNG, quay lại sửa TASK-02 theo quy trình (KHÔNG ghi tắt bỏ qua leg/mirror).
- Phát hiện cần Node ghi DB / thêm `DATABASE_URL` → DỪNG (vi phạm IC§0.1 BLOCKING).
- Cần file tracked ngoài Output paths → in FAILED + lý do.
- Task vượt sức 1 context → in `FAILED: TASK-11 — quá lớn, đề nghị chẻ: [...]`.
