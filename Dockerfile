# ============================================================
# Single-container build: React + FastAPI + Redis (in-memory)
# ============================================================
#
# Stage 1 — build the React app
# Stage 2 — run Redis + FastAPI, serving the built frontend
# ============================================================

# ── Stage 1: Build frontend ─────────────────────────────────
FROM node:22-alpine AS frontend-build

WORKDIR /build

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install && npm cache clean --force

COPY frontend/ ./

ENV REACT_APP_API_URL=""
RUN npm run build


# ── Stage 2: Python + Redis runtime ─────────────────────────
FROM python:3.13-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apk add --no-cache gcc musl-dev libffi-dev redis

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .

COPY --from=frontend-build /build/build /app/static

ENV STATIC_DIR=/app/static \
    REDIS_URL=redis://localhost:6379/0

RUN printf '#!/bin/sh\nredis-server --daemonize yes --save "" --appendonly no\nexec uvicorn app.main:app --host 0.0.0.0 --port 8000\n' > /app/start.sh && \
    chmod +x /app/start.sh

EXPOSE 8000

CMD ["/app/start.sh"]
