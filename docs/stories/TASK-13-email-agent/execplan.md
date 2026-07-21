# TASK-13 — Email Agent (Module 2): Execution Plan

## Status

planned

## Lane

high-risk

## Goal

Đọc mailbox delegate → LLM extract → tạo `agent_proposals` (human-in-the-loop) → dedup + `\Seen` đúng thứ tự giao dịch → rollover chain `resolve_and_activate_leg`. §8 bước 13.

## Scope — Output paths (CHỈ động vào đây, theo PROGRESS.md TASK-13)

- `backend/app/integrations/imap_client.py`
- `backend/app/agents/email_agent.py`
- `backend/app/services/email_service.py`
- `backend/app/services/proposal_service.py`
- `backend/app/services/leg_service.py` (MODIFY: thêm `resolve_and_activate_leg`)
- `backend/app/api/proposals.py`
- `backend/app/main.py` (MODIFY: lifespan email poll + include proposals router)
- `backend/tests/test_email_matching.py`, `test_email_idempotency.py`, `test_email_seen_flag.py`, `test_proposal_service.py`, `backend/tests/fixtures/emails/`

KHÔNG MODIFY `backend/requirements.txt` (imaplib stdlib + LLMClient đã có). Cần file tracked ngoài danh sách → in `FAILED`, không tự sửa.

## Risk classification

- **Lane:** high-risk.
- **Risk flags:** external systems (IMAP + LLM), audit/security (untrusted mail input, allowlist), data model (`processed_emails`, `shipment_legs` rollover), weak proof (IMAP thật key-gated).
- **Hard gate:** audit/security + external provider — cần human review trước merge; smoke IMAP thật ghi smoke-key checklist.

## Work phases (theo Worker Instruction TASK-13)

1. **Fixtures:** 4 file `.eml`/`.txt` theo IC§14 (rollover có new_vessel / vessel delay / multi-container có 1 lạ pass check-digit / forward tay). Biến khớp seed IC§13.
2. **`email_agent.py`:** LLM extract `EmailExtraction` qua `LLMClient`, JSON mode + validate + retry 1 lần; parse xuyên lớp forward (§7.4).
3. **`imap_client.py` + `email_service.py`:** transport tách business (design.md); poll UNSEEN; allowlist kép suffix-match; dedup; **commit `processed_emails` TRƯỚC `STORE \Seen`**; retry `\Seen` khi `seen_set_at` NULL; 4 outcome cố định.
4. **`proposal_service.py` + `leg_service.py` (MODIFY):** approve/reject + 409 đã decided; `new_eta` → `eta_current` + `eta_history(source='email_agent')`; rollover chain §6.8d qua `resolve_and_activate_leg` (session-first, cùng khuôn `resolve_leg`).
5. **`api/proposals.py` + `main.py`:** router IC§3.2, lifespan khởi động ĐÚNG 1 poller. `get_current_user` (stub TASK-03/thật TASK-14) cấp `decided_by`.
6. **Tests + verify** (xem validation.md) → commit 1 lần, Conventional Commits (`feat:`).

## Stop conditions — DỪNG và báo, không tự quyết

- **Mailbox dùng chung phát hiện ra** (có người đọc web UI trên mailbox delegate) → DỪNG, đánh giá lại cơ chế `\Seen` (đọc tay set `\Seen` → agent skip nhầm mail chưa xử lý — §7.2/Patch p2).
- Cần dependency mới ngoài stdlib/đã-pin (VD IMAP lib ngoài `imaplib`) → DỪNG (TASK-13 không được MODIFY requirements).
- `resolve_leg`/`scrape_client` (TASK-11) chưa tồn tại hoặc lệch chữ ký → DỪNG, không tự viết lại.
- Task vượt sức 1 context (sắp auto-compaction) → in `FAILED: TASK-13 — quá lớn, đề nghị chẻ: [...]` (v0.9.18), không spawn worker con.
- Phát sinh nhu cầu thêm outcome mới (VD `partial_match`) → KHÔNG thêm; nếu thấy 4 outcome không đủ → DỪNG, escalate.
