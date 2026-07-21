# Spike scripts (TASK-01)

Bốn script chứng minh I/O thật + compatibility gate cho dependency experimental.
Chạy tất cả từ thư mục `backend/`.

## Chuẩn bị env

1. Từ gốc repo: `cp .env.devtest2 .env` rồi tự điền secret cần thiết vào `.env`
   (KHÔNG commit). Script đọc key qua biến môi trường (tên biến theo IC§7).
2. Load `.env` vào shell trước khi chạy, ví dụ (PowerShell):

   ```powershell
   Get-Content ..\.env | Where-Object { $_ -match '^[A-Z_]+=' } | ForEach-Object {
     $k, $v = $_ -split '=', 2; Set-Item "env:$k" $v
   }
   ```

   hoặc (bash): `set -a; source ../.env; set +a`

## spike_openmeteo.py — KHÔNG cần key

```
python scripts/spike_openmeteo.py
```

In wave_height / ocean_current_velocity / ocean_current_direction (Marine API)
+ wind_speed_10m / wind_direction_10m (Forecast API) giờ hiện tại tại ~Cát Lái.

## spike_ais.py — cần `AISSTREAM_API_KEY`

```
python scripts/spike_ais.py
```

Connect `wss://stream.aisstream.io/v0/stream`, subscribe bounding box biển Đông/
Singapore, in 5-10 PositionReport (MMSI, lat, lon, SOG, COG) rồi thoát. Nhận đủ
≥5 bản tin sẽ dump fixture `tests/fixtures/ais_positions.json` (dùng cho parser
test, replay mode TASK-04, E2E TASK-17). 30s không có message → in cảnh báo,
exit 0.

> **Fixture hiện tại là SYNTHETIC** (ShipName = "SYNTHETIC FIXTURE ..") — tạo
> đúng schema aisstream khi chưa có key. Khi có `AISSTREAM_API_KEY`, chạy script
> này để dump đè bản thật (cần smoke lại: TASK-01 spike_ais).

## spike_ag2.py — compatibility gate `ag2==0.14.0`, cần LLM key

```
python scripts/spike_ag2.py
```

Cần `LLM_API_KEY` + `LLM_MODEL` (+ `LLM_BASE_URL` nếu endpoint OpenAI-compatible
khác). Dựng ConversableAgent + register_function tool `add_numbers`, chạy 1 chat
tool-call rồi thoát. Thiếu key → PASS cấu trúc (import/agent/tool registration)
và in nhắc smoke lại.

## spike_mcp.py — compatibility gate `mcp==1.12.4` ↔ `@playwright/mcp@0.0.78`

Terminal 1 (từ `playwright-mcp/`, sau `npm install`):

```
npx @playwright/mcp --port 3001 --headless
```

Terminal 2 (từ `backend/`):

```
python scripts/spike_mcp.py
```

Client SSE (`mcp.client.sse.sse_client`) initialize → list_tools → gọi
`browser_navigate` tới example.com. Server không chạy → in cảnh báo, exit 0.
Port đọc từ `MCP_SSE_PORT` (default 3001).
