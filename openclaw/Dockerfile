FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    libpq-dev \
    curl \
    git \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# MiniMax CLI is used by OpenClaw operations and the bundled mmx-cli skill.
RUN npm install -g mmx-cli

WORKDIR /app

# Python 依赖
COPY openclaw/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir uvicorn[standard]

# 应用代码
COPY openclaw/ ./openclaw/
COPY data-service/src/services/health_cache.py ./openclaw/gateway/health_cache.py
COPY data-service/src/services/sentry_service.py ./openclaw/gateway/sentry_service.py

# 入口文件
COPY openclaw/gateway_app.py ./gateway_app.py

# Cloud Run 要求监听 PORT 环境变量，默认 8080
ENV PORT=8080
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=10s \
    CMD curl --fail --silent --show-error --connect-timeout 1 --max-time 3 http://localhost:${PORT}/health || exit 1

# Cloud Run 使用 PORT 环境变量
CMD ["sh", "-c", "if [ -n \"$MINIMAX_API_KEY\" ] && command -v mmx >/dev/null 2>&1; then mmx auth login --api-key \"$MINIMAX_API_KEY\" >/dev/null 2>&1 || true; fi; uvicorn gateway_app:app --host 0.0.0.0 --port ${PORT:-8080} --workers 2"]
