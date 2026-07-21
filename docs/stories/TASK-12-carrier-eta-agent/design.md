# TASK-12 — Carrier ETA Agent: Design

## Status

planned

## Lane

high-risk

## Domain model

- **Carrier ETA fetch** = 1 lần thử best-effort đọc ETA hãng công bố cho 1 lô. Kết quả: datetime tz-aware UTC (IC§15) HOẶC failure có log — không có trạng thái lửng.
- Chỉ ghi 2 field domain: `shipments.eta_original` + `eta_original_source` (§4.1, giá trị `carrier_scrape`) và 1 dòng `eta_history(source='original')`.
- Agent stateless mỗi lần chạy — không giữ transcript/session.

## Application flow

1. Onboarding TASK-11 hoàn tất (`resolve_leg` → resolved).
2. `api/shipments.py` (MODIFY): lô chưa có `eta_original` → schedule `carrier_eta_service.fetch_carrier_eta(shipment_id)` background — KHÔNG block response onboarding.
3. `fetch_carrier_eta` load lô (carrier, B/L/booking, POD) → chạy `carrier_eta_agent` với browser tools → parse/validate ETA trích được.
4. Thành công → 1 transaction: ghi `eta_original` + `eta_original_source='carrier_scrape'` + INSERT `eta_history(source='original')`.
5. Fail bất kỳ → log kèm lý do, không đổi gì. Nhập tay (`PATCH eta_original` → source `manual`) luôn khả dụng.

## Ranh giới cứng (Interface contract)

- **Chỉ cửa MCP** (IC§3.3): browser tools của agent connect `http://playwright-mcp:3001/sse` (IC§12). Cửa REST `/scrape-jobs` (port 3000) dành riêng job `imo_resolve` deterministic — task này CẤM đụng.
- **Gateway cô lập** (Ràng buộc toàn cục v0.9.12, Option 1.5): `integrations/browser_agent_client.py` định nghĩa `BrowserAgentClient` — module **DUY NHẤT** được import package `mcp` (`mcp==1.12.4`, `mcp.client.sse.sse_client` — đã gate ở TASK-01 `spike_mcp.py`; đọc docstring bản pin, KHÔNG bịa API). Gateway lo transport/handshake/timeout, map mọi lỗi → `ExternalIntegrationError(retryable: bool)`. `carrier_eta_agent.py` và `carrier_eta_service.py` CẤM import MCP package trực tiếp.
- LLM đi qua `LLMClient` sẵn có (boundary TASK-08), config từ `settings.LLM_*` (§3.4, IC§7).

## Data model

Không đổi schema. Ghi giới hạn:

- `shipments.eta_original` (timestamptz), `shipments.eta_original_source` (`'carrier_scrape'`) — chỉ khi đang trống.
- 1 dòng `eta_history` với `source='original'`.

`eta_current`, `onboarding_status`, `shipment_legs` KHÔNG BAO GIỜ bị ghi.

## Observability

- Log mỗi lần thử: shipment_id, carrier, outcome (ok / captcha / login-wall / timeout / parse-fail / mcp-down / llm-error), duration.
- Fail là sự kiện vận hành bình thường (hãng chặn bot) — log warning, không raise lên API layer.

## Alternatives considered

- **Script Playwright deterministic từng hãng qua `/scrape-jobs`** — spec loại (§6.7b): layout mỗi hãng khác nhau và đổi thường xuyên; agentic LLM chính là điểm của task này. IMO Resolver giữ cửa deterministic.
- **Fetch blocking trong onboarding** — loại: vi phạm acceptance non-blocking; site hãng chậm/không ổn định.
- **Import MCP trực tiếp trong agent module** — loại: API MCP experimental còn đổi, phải giam trong `BrowserAgentClient` (ràng buộc toàn cục).

## Chi tiết đầy đủ

Trỏ về Spec §6.7b/§6.7c/§3.4, IC§3.3/IC§8/IC§12 — không copy lại (Spec/IC là normative).
