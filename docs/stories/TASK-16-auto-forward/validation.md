# TASK-16 — Auto-forward theo monitoring_mode: Validation

## Status

planned

## Lane

high-risk

## Proof matrix (theo mục Verify TASK-16 — PROGRESS.md, TDD)

Trỏ tới row **TASK-16** trong `docs/TEST_MATRIX.md`.

| Layer | Proof | Trạng thái |
|---|---|---|
| Unit/TDD | `pytest tests/test_forward_service.py -v` — lô `auto_email` → forward tới ĐÚNG whitelist `AUTO_FORWARD_RECIPIENTS` (mock SMTP, assert recipient list khớp env từng địa chỉ) | not run |
| Unit/TDD | Lô `manual` → KHÔNG có SMTP call nào (mock assert not called) | not run |
| Unit/TDD | **Rào an toàn:** mail chứa To/CC/Reply-To lạ trong nội dung → recipient gửi đi VẪN chỉ là env whitelist, KHÔNG chứa bất kỳ địa chỉ nào từ nội dung mail | not run |
| Unit/TDD | Log forward có đủ 4 trường: recipient, message_id, shipment_id, thời điểm (tz-aware UTC) | not run |
| Unit | SMTP fail (mock raise) → log error, không exception xuyên lên, proposal đã tạo không bị ảnh hưởng | not run |
| Integration (offline) | Fixture smoke qua đường TASK-13: mail hợp lệ lô auto_email → log forward tới whitelist; cùng mail cho lô manual → không forward | not run |
| Platform | `pip install` sạch với `aiosmtplib` mới pin; `requirements.lock.txt` regenerate + commit; các test suite khác vẫn PASS (không vỡ lock) | not run |
| Platform (key-gated) | Smoke SMTP thật qua mailbox delegate: 1 mail forward thật tới whitelist test. Thiếu credential → PASS cấu trúc + ghi Session Log `cần smoke lại: TASK-16 (SMTP delegate)` | not run — smoke-key checklist |

## Ghi chú

- 3 case TDD đầu là bắt buộc theo Worker Instruction TASK-16 — viết fail TRƯỚC khi code.
- Case rào an toàn là hard gate security: nếu test này không thể viết pass mà không đọc nội dung mail để lấy địa chỉ → thiết kế sai, quay lại design.md.
- Task chỉ đánh [x] khi mọi dòng offline + lock PASS; dòng key-gated ghi smoke-key checklist, không block.
