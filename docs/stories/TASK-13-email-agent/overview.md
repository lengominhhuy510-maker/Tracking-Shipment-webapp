# TASK-13 — Email Agent (Module 2): Overview

## Status

planned

## Lane

high-risk

## Current behavior

- Chưa có module email nào. Mail hãng tàu/forwarder vào mailbox delegate không được đọc tự động; ETA thay đổi/rollover phải nhập tay hoàn toàn.
- Schema đã sẵn sàng (schema-ahead từ TASK-02): `agent_proposals`, `processed_emails` (gồm 3 cột trace `imap_uid`/`imap_folder`/`seen_set_at` — Patch p2), `shipment_legs` + `resolve_leg()` (TASK-11).

## Target behavior

- 1 email poller duy nhất (lifespan khởi động) poll mailbox delegate mỗi `EMAIL_POLL_INTERVAL_MINUTES` qua `imap_client.py` (transport-only, tách khỏi business — ranh giới Option 1.5).
- LLM extract `EmailExtraction` (IC§4.2) qua `LLMClient`: JSON mode + validate + retry 1 lần.
- Allowlist KÉP §7.4: (A) domain hãng `CARRIER_EMAIL_DOMAINS` + (B) forwarder nội bộ `INTERNAL_FORWARDER_EMAILS`, suffix-match (IC§8).
- **Human-in-the-loop (§7.2):** mail = untrusted input → hệ CHỈ tạo `agent_proposals`, người approve/reject; approve có `new_eta` → update `eta_current` + `eta_history(source='email_agent')`; 409 nếu đã decided.
- Dedup qua `processed_emails`; **commit `processed_emails` TRƯỚC khi STORE `\Seen`** (Patch p2 — xem design.md).
- Rollover chain §6.8d: proposal có `new_vessel_name` → `resolve_imo` tàu mới → leg mới cùng `leg_no` + `superseded_at` cũ → `resolve_and_activate_leg()`.
- Đúng 4 outcome: `proposals_created | no_match | rejected_allowlist | parse_failed`.

## Affected docs

- Spec §13 + Ràng buộc toàn cục + Patch p2 (cuối Summary Table)
- Spec `§7.1`, `§7.2`, `§7.4`, `§6.8d`
- Interface-Contract `IC§0.2`, `IC§4.2`, `IC§8`, `IC§9`, `IC§14`

## Non-goals

- KHÔNG multi-poller / advisory lock — mô hình single-process, 1 poller/lifespan; multi-poller cần locking là **Known Limitation** ghi nhận, không build.
- KHÔNG `\Deleted` + expunge — chốt `\Seen` + giữ mail trong inbox (audit trail 3 lớp, Patch p2).
- KHÔNG thêm outcome `partial_match` — `unmatched_containers` jsonb đã mang thông tin đó.
- KHÔNG auto-apply proposal — mọi thay đổi ETA/leg đều qua người approve.
- KHÔNG `switch_active_leg` (tín hiệu kép transit §6.8c) — STRETCH ngoài đợt này.
- Auto-forward SMTP thuộc TASK-16, không làm ở đây.
