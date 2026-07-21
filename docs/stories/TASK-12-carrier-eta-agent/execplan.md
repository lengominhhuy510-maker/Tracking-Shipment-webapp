# TASK-12 — Execution Plan

## Status

planned

## Lane

high-risk

## Goal

Agent LLM agentic đọc web hãng tàu qua cửa MCP lấy `eta_original` baseline, cô lập sau gateway `BrowserAgentClient`, tuyệt đối không chặn tracking khi fail.

## Scope — Output paths (đúng PROGRESS.md, CHỈ động vào đây)

- `backend/app/integrations/browser_agent_client.py`
- `backend/app/agents/carrier_eta_agent.py`
- `backend/app/services/carrier_eta_service.py`
- `backend/app/api/shipments.py` (MODIFY)
- `backend/requirements.txt` (MODIFY: xác nhận `mcp==1.12.4` + AG2 bản đã gate; KHÔNG thêm/bump)
- `requirements.lock.txt` (regenerate `pip freeze` sau verify)
- `backend/tests/test_carrier_eta_service.py`, `backend/tests/test_carrier_eta_nonblocking.py`

## Risk classification

- **Lane:** high-risk. **Risk flags:** external systems (LLM + MCP + web hãng tàu — 3 tầng bất định), weak proof (agentic không deterministic — proof lõi là mock + nonblocking regression, smoke thật chỉ là bonus), existing behavior (đụng shipments.py onboarding flow — không được làm hỏng luồng resolved của TASK-11).
- **Hard gate:** external provider behavior (agentic) — mọi failure mode của agent phải thoát êm, không lan sang tracking.

## Work phases (theo Worker Instruction TASK-12)

1. Đọc Spec §6.7b/§6.7c, IC§3.3, IC§8, IC§12, §3.4. Đối chiếu kết quả `spike_mcp.py` TASK-01 + docstring `mcp==1.12.4` bản pin (KHÔNG bịa API).
2. `browser_agent_client.py`: gateway SSE client (nơi duy nhất import `mcp`), error mapping → `ExternalIntegrationError(retryable)`.
3. `carrier_eta_agent.py`: AG2 agent + browser tools qua gateway; system prompt chỉ-đọc, trích ETA.
4. `carrier_eta_service.py`: fetch → parse → ghi eta_original/source + eta_history('original'); mọi fail → log + return, không raise xuyên.
5. `shipments.py`: hook background sau IMO resolve, chưa có eta_original mới gọi.
6. Tests: `test_carrier_eta_service.py` (mock MCP trang giả → ghi đúng source); `test_carrier_eta_nonblocking.py` (mock raise → vẫn resolved, eta_current không đổi, AIS tracking bình thường).
7. Requirements xác nhận pin + regenerate lock. Verify → 1 commit.

## Stop conditions

- **`spike_mcp` TASK-01 fail (transport/handshake/API khác giả định) → DỪNG, chốt lại wrapper hoặc giảm scope Carrier ETA — KHÔNG build tiếp trên giả định.**
- `test_carrier_eta_nonblocking.py` không pass → KHÔNG đánh [x] (acceptance criterion bắt buộc v0.9.12).
- Phát hiện agent/service cần import trực tiếp package `mcp` ngoài gateway → DỪNG, sửa kiến trúc, không nới lỏng.
- Cần thêm/bump dependency ngoài bản đã gate → DỪNG, không tự cài.
- Cần file tracked ngoài Output paths → in FAILED + lý do.
- Task vượt sức 1 context → in `FAILED: TASK-12 — quá lớn, đề nghị chẻ: [...]`.
