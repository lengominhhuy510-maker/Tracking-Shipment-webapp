# TASK-16 — Auto-forward theo monitoring_mode: Execution Plan

## Status

planned

## Lane

high-risk

## Goal

Lô `auto_email` → auto-forward mail hợp lệ tới whitelist nội bộ từ env; lô `manual` → không. Rào an toàn: recipient KHÔNG BAO GIỜ từ nội dung mail; log mọi lần forward. §8 bước 16 [STRETCH].

## Scope — Output paths (CHỈ động vào đây, theo PROGRESS.md TASK-16)

- `backend/app/services/forward_service.py`
- `backend/app/services/email_service.py` (MODIFY: sau tạo proposal, lô auto_email → gọi forward)
- `backend/requirements.txt` (MODIFY: thêm + pin `aiosmtplib` — task này ĐƯỢC PHÉP `pip install` đúng gói này)
- `requirements.lock.txt` (regenerate `pip freeze` sau verify — [v0.9.17])
- `backend/tests/test_forward_service.py`

Cần file tracked ngoài danh sách → in `FAILED`, không tự sửa.

## Risk classification

- **Lane:** high-risk.
- **Risk flags:** external systems (SMTP outbound), audit/security (rào rò rỉ dữ liệu — hệ tự gửi mail ra ngoài).
- **Hard gate:** outbound provider + security — mọi thay đổi tới logic chọn recipient cần human review; smoke SMTP thật key-gated.

## Work phases (theo Worker Instruction TASK-16)

1. **TDD trước:** viết `test_forward_service.py` fail — 3 case bắt buộc (validation.md).
2. **`forward_service.py`:** `async auto_forward(email, shipment)` — guard `monitoring_mode`, recipient từ `AUTO_FORWARD_RECIPIENTS` env, gửi `aiosmtplib` qua mailbox delegate, log (recipient, message_id, shipment_id, thời điểm), SMTP fail → log không crash.
3. **`email_service.py` (MODIFY):** hook sau tạo proposal — `auto_email` → forward; `manual` → bỏ qua.
4. **Dependency:** thêm + pin `aiosmtplib` vào `backend/requirements.txt`, cài, chạy verify, regenerate `requirements.lock.txt`, commit cả hai.
5. **Verify + commit** 1 lần (`feat:`).

## Stop conditions — DỪNG và báo, không tự quyết

- Cần dependency ngoài `aiosmtplib` (VD template lib, queue lib) → DỪNG — TASK-16 chỉ được thêm đúng 1 gói này.
- Phát hiện bất kỳ yêu cầu/đường code nào lấy recipient từ nội dung mail hoặc nguồn runtime khác → DỪNG, escalate — vi phạm rào an toàn §7.4, không thương lượng.
- SMTP mailbox delegate không hỗ trợ gửi (VD delegate chỉ IMAP read-only) → DỪNG, báo lại phương án credential.
- `email_service.py` (TASK-13) chưa tồn tại/khác cấu trúc dự kiến → DỪNG — TASK-16 phụ thuộc TASK-13 xong trước.
- Task vượt sức 1 context → in `FAILED: TASK-16 — quá lớn, đề nghị chẻ: [...]` (v0.9.18).
