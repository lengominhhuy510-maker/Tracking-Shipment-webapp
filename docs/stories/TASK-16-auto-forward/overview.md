# TASK-16 — Auto-forward theo monitoring_mode: Overview

## Status

planned

## Lane

high-risk

## Current behavior

- Email Agent (TASK-13) tạo proposal cho mọi mail hợp lệ bất kể `monitoring_mode`, nhưng KHÔNG forward mail đi đâu — người dùng lô `manual` tự forward tay, lô `auto_email` cũng chưa có gì tự động.
- Chưa có SMTP outbound trong hệ thống; `aiosmtplib` chưa nằm trong `requirements.txt` (chủ đích — TASK-16 mới được thêm).

## Target behavior

- Sau khi TASK-13 tạo proposal cho container khớp: nếu lô `monitoring_mode == 'auto_email'` → `forward_service.auto_forward(email, shipment)` gửi mail tới `AUTO_FORWARD_RECIPIENTS` (env, IC§7) qua SMTP mailbox delegate bằng `aiosmtplib`.
- Lô `manual` → KHÔNG forward (người tự forward tay — bảng §7.4).
- **Rào an toàn §7.4 (hard gate):** địa chỉ nhận CHỈ từ env whitelist cấu hình trước — **KHÔNG BAO GIỜ lấy từ nội dung mail**, kể cả To/CC/Reply-To bên trong mail (rào rò rỉ: mail độc có thể nhúng địa chỉ ngoài để exfiltrate).
- Log MỌI lần forward: recipient, message_id, shipment_id, thời điểm — audit trail.

## Affected docs

- Spec §16 + Ràng buộc toàn cục (Lock reproducibility — task này MODIFY requirements)
- Spec `§7.4` (bảng auto_email/manual + rào an toàn)
- Interface-Contract `IC§7` (`AUTO_FORWARD_RECIPIENTS`), `IC§8`

## Non-goals

- KHÔNG lấy recipient động từ bất kỳ nguồn runtime nào (nội dung mail, DB user input, API param) — chỉ env.
- KHÔNG gửi tới địa chỉ ngoài whitelist trong mọi nhánh code.
- KHÔNG forward cho lô `manual`.
- KHÔNG thêm dependency nào ngoài `aiosmtplib` (dependency duy nhất task này được phép thêm + pin).
- KHÔNG retry-queue/outbox phức tạp — fail thì log, không crash (fallback êm); hạ tầng gửi lại là future work.
