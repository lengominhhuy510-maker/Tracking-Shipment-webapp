# Container playwright-mcp (Node) — cửa scrape 2 ngõ: REST /scrape-jobs (3000) + MCP SSE (3001).
# Base mcr.microsoft.com/playwright: đã có toàn bộ OS libs cho headless Chromium.
# Build cho linux/amd64 (chạy trên host amd64):
#   docker buildx build --platform linux/amd64 -t playwright-mcp ./playwright-mcp
FROM mcr.microsoft.com/playwright:v1.61.1-noble

WORKDIR /app

# npm ci reproducible từ lock đã commit. Copy manifest trước để tận dụng cache layer.
COPY package.json package-lock.json ./
RUN npm ci

# playwright npm đã pin (1.62.0-alpha-...) lệch browser bundle trong base image →
# cài đúng Chromium khớp bản pin. OS libs đã có sẵn từ base nên KHÔNG cần --with-deps.
RUN npx playwright install chromium

COPY tsconfig.json ./
COPY src ./src
RUN npm run build

# IC§12: REST 3000 + MCP SSE 3001 — chỉ nội bộ compose network (không map ra host).
EXPOSE 3000 3001

# IC§0.1: container KHÔNG nhận DATABASE_URL — env chỉ REDIS_URL + SCRAPE_*/MCP_SSE_PORT.
CMD ["npm", "start"]
