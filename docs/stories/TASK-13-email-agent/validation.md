# TASK-13 — Email Agent (Module 2): Validation

## Status

planned

## Lane

high-risk

## Proof matrix (theo mục Verify TASK-13 — Spec)

Trỏ tới row **TASK-13** trong `docs/TEST_MATRIX.md`.

| Layer | Proof | Trạng thái |
|---|---|---|
| Unit/TDD | `pytest tests/test_email_matching.py -v` — allowlist kép (A domain hãng suffix-match, B forwarder nội bộ), dedup, multi-container có container lạ → `unmatched_containers` | not run |
| Unit/TDD | `pytest tests/test_email_idempotency.py -v` — xử lý cùng mail 2 lần → chỉ 1 proposal (unique `(source_email_id, shipment_id)`) | not run |
| Unit/TDD | `pytest tests/test_email_seen_flag.py -v` — thứ tự commit DB trước `STORE \Seen`; `\Seen` fail → poll kế dedup skip + retry set `\Seen` (`seen_set_at` NULL → filled); DB fail → mail vẫn unseen, poll kế fetch lại | not run |
| Unit/TDD | `pytest tests/test_proposal_service.py -v` — approve set `eta_current` + `eta_history(source='email_agent')`; 409 khi đã decided; rollover: leg mới cùng `leg_no`, `superseded_at` cũ, `resolve_and_activate_leg` mirror + 1 active leg | not run |
| Integration (offline) | Fixture smoke: feed 4 mail mẫu IC§14 qua `process_raw_email` → mail 1 rollover đủ chuỗi §6.8d; mail 2 chỉ ETA; mail 3 → 2 proposal + 1 unmatched; mail 4 forwarder → vẫn proposal, không auto-forward. Xử lý lại cùng mail → proposal count không tăng | not run |
| Integration (offline) | Kiểm 4 outcome đúng enum `proposals_created|no_match|rejected_allowlist|parse_failed`, không xuất hiện giá trị thứ 5 | not run |
| E2E | Nhánh email trong `test_e2e_demo.py` (TASK-17) — fixture mail → proposal → approve → WS delta | not run (thuộc TASK-17) |
| Platform (key-gated) | Smoke IMAP thật: gửi mail thật vào delegate mailbox → proposal tạo, `\Seen` set, `seen_set_at` filled. Thiếu key → PASS cấu trúc + ghi Session Log `cần smoke lại: TASK-13 (IMAP + LLM key)` | not run — smoke-key checklist |

## Ghi chú

- Mail = untrusted input: test khẳng định KHÔNG có đường nào tự update `eta_current`/leg mà không qua approve.
- LLM extract retry đúng 1 lần; fail sau retry → `parse_failed`, app không crash (fallback êm — Ràng buộc toàn cục).
- Known Limitation ghi kèm khi đánh [x]: single poller, không advisory lock; multi-poller ngoài scope.
- Task chỉ đánh [x] khi mọi dòng offline PASS; dòng key-gated không block nhưng BẮT BUỘC ghi smoke-key checklist.
