# TASK-12 — Carrier ETA Agent (agentic qua Playwright MCP): Overview

## Status

planned

## Lane

high-risk

## Current behavior

- Chưa build. Sau TASK-11, lô hàng có thể đạt `onboarding_status='resolved'` (đã biết IMO/MMSI) nhưng `eta_original` chỉ có khi user nhập tay (`PATCH` với `eta_original` → source `manual`, TASK-03). Chưa có đường tự động nào đọc website tracking của hãng tàu.
- Container `playwright-mcp` (TASK-10) đã expose MCP SSE endpoint port 3001 (IC§12) nhưng chưa có code backend nào dùng, ngoài compatibility gate `spike_mcp.py` của TASK-01.

## Target behavior

Agent LLM agentic đọc web hãng tàu lấy ETA công bố làm `eta_original` baseline:

- Sau khi IMO resolve thành công, nếu lô chưa có `eta_original` → chạy Carrier ETA agent ở background (§6.7b).
- Agent điều khiển browser qua **cửa MCP** (`http://playwright-mcp:3001/sse` — IC§3.3/IC§12): navigate/click/snapshot trên trang tracking hãng (URL theo carrier — IC§8), điền B/L/booking, trích ETA cập cảng đích. Đây KHÔNG phải đường REST `/scrape-jobs` — cửa đó dành riêng cho IMO Resolver deterministic.
- Thành công → ghi `shipments.eta_original` + `eta_original_source='carrier_scrape'` + INSERT `eta_history(source='original')`. TUYỆT ĐỐI không đụng `eta_current` (§6.7c).
- Fail bất kỳ (LLM lỗi, MCP down, captcha, login wall, layout đổi) → giữ nguyên lô: vẫn `resolved`, nhập tay vẫn là đường chính song song, AIS tracking không bị ảnh hưởng. Tính non-blocking này là **acceptance criterion bắt buộc** (v0.9.12).

## Affected users / docs

- User: người phụ trách lô — có ETA baseline không cần nhập tay; fallback nhập tay giữ nguyên, không workflow nào bị bỏ.
- Spec: §6.7/§6.7b (agentic browser, 2-3 hãng, fallback nhập tay), §6.7c (chỉ đọc, không login credential thật, chỉ ghi `eta_original`), §3.4 (LLM qua env), §8 bước 12.
- Interface-Contract: IC§3.3 (Carrier ETA đi cửa MCP), IC§12 (SSE host/port), IC§8 (URL tracking 5 hãng).
- Repo docs: Spec §12; `docs/TEST_MATRIX.md` row TASK-12.

## Non-goals

- KHÔNG ghi `eta_current` hay bất kỳ state nào của ETA engine (nguyên tắc: carrier ETA là tiện ích baseline, tracking không bao giờ phụ thuộc nó).
- KHÔNG login credential thật của hãng — chỉ đọc trang tracking công khai.
- KHÔNG thêm dependency / bump version — dùng lại `mcp==1.12.4` + AG2 bản đã gate ở TASK-01.
- KHÔNG đổi contract `/scrape-jobs` REST hay đường IMO Resolver.
- KHÔNG retry/queue infrastructure ngoài 1 lần thử background; fail → fallback nhập tay.
