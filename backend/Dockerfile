# TASK-00: multi-stage build — stage 1 build frontend, stage 2 Python runtime.
# Build context = repo root: docker build -f backend/Dockerfile .

# ---------- Stage 1: build frontend ----------
FROM node:20 AS frontend-build
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---------- Stage 2: Python runtime ----------
FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY --from=frontend-build /frontend/dist /app/static
# WPI_DATA_PATH=/app/data/wpi_ports.csv (IC§7) — file nguồn do TASK-07 tạo
COPY backend/data/ /app/data/
EXPOSE 1476
# 1 worker: background tasks embedded, xem §3.1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "1476"]
