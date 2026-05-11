#!/bin/bash
# ============================================================
# AI Holdings Analyzer v2 — 本地开发一键启动
# ============================================================
# 用法: ./scripts/dev.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

GREEN='\033[0;32m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }

# 加载环境变量
if [ -f "$PROJECT_ROOT/.env" ]; then
    set -a
    source "$PROJECT_ROOT/.env"
    set +a
    log_info "已加载 .env"
else
    log_info "未找到 .env，使用默认开发配置"
fi

# 启动 Data Service（后台）
log_info "启动 Data Service..."
cd "$PROJECT_ROOT/data-service"

if [ ! -d ".venv" ]; then
    log_info "创建 Python 虚拟环境..."
    python3 -m venv .venv
    .venv/bin/pip install -q -r requirements.txt
fi

.venv/bin/uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload &
DATA_PID=$!
log_info "Data Service 已启动 (PID=$DATA_PID, http://localhost:8000)"

# 启动 WebApp（前台）
log_info "启动 WebApp..."
cd "$PROJECT_ROOT/webapp"

if [ ! -d "node_modules" ]; then
    log_info "安装 WebApp 依赖..."
    npm install
fi

log_info "WebApp 启动中... (Ctrl+C 停止所有服务)"
trap "kill $DATA_PID 2>/dev/null; exit 0" INT TERM

npm run dev

# npm run dev 退出后，清理 Data Service
kill $DATA_PID 2>/dev/null || true
