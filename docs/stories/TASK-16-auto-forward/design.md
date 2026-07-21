# TASK-16 — Auto-forward theo monitoring_mode: Design

## Status

planned

## Lane

high-risk

## Flow

1. TASK-13 `email_service.py` xử lý xong 1 mail, tạo proposal cho container khớp.
2. Hook (MODIFY `email_service.py`): với mỗi shipment khớp, nếu `shipment.monitoring_mode == 'auto_email'` → `await forward_service.auto_forward(email, shipment)`; `manual` → bỏ qua.
3. `forward_service.auto_forward`:
   - Guard đầu hàm: re-check `monitoring_mode == 'auto_email'` (defense in depth — không tin caller).
   - Recipient = parse `settings.AUTO_FORWARD_RECIPIENTS` (env, IC§7). Hàm KHÔNG nhận tham số recipient — không có đường truyền địa chỉ từ ngoài vào.
   - Gửi qua SMTP mailbox delegate bằng `aiosmtplib` (async, khớp stack FastAPI).
   - Log structured mỗi lần forward: `recipient, message_id, shipment_id, timestamp` (tz-aware UTC — IC§15).
   - SMTP fail → log error, KHÔNG raise xuyên lên poll loop (fallback êm — Ràng buộc toàn cục Error handling), KHÔNG ảnh hưởng proposal đã tạo.

## Rào an toàn (quyết định chốt — §7.4)

- Whitelist **cấu hình trước** qua env duy nhất `AUTO_FORWARD_RECIPIENTS`; đổi người nhận = đổi env + restart, không có API/DB path.
- Nội dung mail gốc (To/CC/Reply-To/body) TUYỆT ĐỐI không tham gia quyết định recipient — mail là untrusted input (§7.2). Đây là rào chống rò rỉ: mail độc nhúng địa chỉ lạ không thể khiến hệ gửi dữ liệu ra ngoài whitelist.
- `monitoring_mode` derive từ `derive_monitoring_mode(direction, incoterm)` (IC§1.1) — forward_service chỉ đọc cột đã lưu, không tự cài lại bảng §5.

## Ranh giới module

- `forward_service.py` là service mỏng: SMTP call + guard + log. Transport SMTP nếu tách được thì nằm cùng nguyên tắc `integrations/` (Option 1.5) — nhưng với 1 chỗ dùng, gọi `aiosmtplib` trực tiếp trong service là chấp nhận được (nhóm "client cực mỏng", không Interface/Factory).
- KHÔNG business logic mới: không đụng proposal, ETA, leg.

## Dependency (ngoại lệ có chủ đích)

- TASK-16 nằm trong danh sách task được MODIFY `backend/requirements.txt` (Ràng buộc toàn cục): thêm + pin `aiosmtplib`, sau đó regenerate + commit `requirements.lock.txt` (`pip freeze`) theo quy tắc Lock reproducibility [v0.9.17].
- Chỉ đúng gói `aiosmtplib` — không thêm/bump gì khác.

## Contract tham chiếu

- Bảng forward theo mode + rào an toàn: **§7.4**.
- `AUTO_FORWARD_RECIPIENTS` + SMTP env: **IC§7**.
- Allowlist/hãng: **IC§8** (ngữ cảnh — allowlist ĐỌC là chuyện TASK-13; task này chỉ lo allowlist GỬI).
