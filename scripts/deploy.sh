#!/bin/bash
# ============================================================
# AI Holdings Analyzer v2 — 一键部署脚本
# ============================================================
# 用法:
#   ./scripts/deploy.sh --target webapp       # 部署 Next.js 到 Vercel
#   ./scripts/deploy.sh --target data-service # 部署 Data Service (Docker)
#   ./scripts/deploy.sh --target openclaw     # 部署 OpenClaw Gateway (Docker)
#   ./scripts/deploy.sh --target migrate      # 执行数据库迁移
#   ./scripts/deploy.sh --target all          # 全部部署
#
# 云端部署请使用: ./scripts/deploy-cloud.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# 检查环境变量文件
check_env() {
    if [ ! -f "$PROJECT_ROOT/.env" ]; then
        log_error ".env 文件不存在，请先复制 .env.example 并填入真实值"
        log_error "  cp .env.example .env"
        exit 1
    fi

    # 加载环境变量
    set -a
    source "$PROJECT_ROOT/.env"
    set +a

    # 检查必需变量
    local missing=0
    for var in SUPABASE_URL SUPABASE_SERVICE_ROLE_KEY; do
        if [ -z "${!var:-}" ] || [[ "${!var}" == *"your"* ]] || [[ "${!var}" == *"placeholder"* ]]; then
            log_error "必需环境变量 $var 未配置"
            missing=1
        fi
    done

    if [ $missing -eq 1 ]; then
        log_error "请先在 .env 中配置必需的环境变量"
        exit 1
    fi

    log_info "环境变量检查通过"
}

# === 数据库迁移 ===
deploy_migrate() {
    log_info "=== 执行数据库迁移 ==="

    local migrations_dir="$PROJECT_ROOT/supabase/migrations"

    if [ ! -d "$migrations_dir" ]; then
        log_error "迁移目录不存在: $migrations_dir"
        exit 1
    fi

    local migration_count
    migration_count=$(ls "$migrations_dir"/*.sql 2>/dev/null | wc -l)
    log_info "发现 $migration_count 个迁移文件"

    # 检查 Supabase CLI
    if command -v supabase &> /dev/null; then
        log_info "使用 Supabase CLI 执行迁移..."
        cd "$PROJECT_ROOT"
        supabase db push --linked
        log_info "迁移完成"
    else
        log_warn "Supabase CLI 未安装，请手动执行迁移:"
        log_warn "  1. 安装: brew install supabase/tap/supabase"
        log_warn "  2. 登录: supabase login"
        log_warn "  3. 关联: supabase link --project-ref <your-project-ref>"
        log_warn "  4. 推送: supabase db push"
        log_warn ""
        log_warn "或者通过 Supabase Dashboard SQL 编辑器手动执行:"
        for f in "$migrations_dir"/*.sql; do
            log_warn "  - $(basename "$f")"
        done
    fi
}

# === WebApp 部署到 Vercel ===
deploy_webapp() {
    log_info "=== 部署 WebApp 到 Vercel ==="

    local webapp_dir="$PROJECT_ROOT/webapp"

    if [ ! -d "$webapp_dir" ]; then
        log_error "WebApp 目录不存在: $webapp_dir"
        exit 1
    fi

    # 检查 Vercel CLI
    if ! command -v vercel &> /dev/null; then
        log_error "Vercel CLI 未安装，请先安装:"
        log_error "  npm install -g vercel"
        exit 1
    fi

    cd "$webapp_dir"

    # 检查依赖是否安装
    if [ ! -d "node_modules" ]; then
        log_info "安装 WebApp 依赖..."
        npm install
    fi

    # 设置 Vercel 环境变量
    log_info "配置 Vercel 环境变量..."

    # 检查是否已关联 Vercel 项目
    if [ ! -f ".vercel/project.json" ]; then
        log_info "首次部署，需要关联 Vercel 项目..."
        vercel link --yes
    fi

    # 设置环境变量（仅在变量存在时设置）
    set_env_if_present "NEXT_PUBLIC_SUPABASE_URL" "$SUPABASE_URL"
    set_env_if_present "NEXT_PUBLIC_SUPABASE_ANON_KEY" "$SUPABASE_ANON_KEY"
    set_env_if_present "SUPABASE_SERVICE_ROLE_KEY" "$SUPABASE_SERVICE_ROLE_KEY"

    if [ -n "${SENTRY_DSN:-}" ]; then
        set_env_if_present "NEXT_PUBLIC_SENTRY_DSN" "$SENTRY_DSN"
    fi

    # 部署到生产环境
    log_info "构建并部署到 Vercel..."
    vercel --prod

    log_info "WebApp 部署完成"
}

set_env_if_present() {
    local key="$1"
    local value="$2"
    if [ -n "$value" ]; then
        vercel env add "$key" production <<< "$value" 2>/dev/null || \
        vercel env rm "$key" production -y 2>/dev/null && \
        vercel env add "$key" production <<< "$value" 2>/dev/null || true
    fi
}

# === Data Service 部署 ===
deploy_data_service() {
    log_info "=== 部署 Data Service ==="

    local ds_dir="$PROJECT_ROOT/data-service"

    if [ ! -d "$ds_dir" ]; then
        log_error "Data Service 目录不存在: $ds_dir"
        exit 1
    fi

    # 检查 Docker
    if ! command -v docker &> /dev/null; then
        log_error "Docker 未安装，请先安装 Docker"
        exit 1
    fi

    cd "$ds_dir"

    # 构建 Docker 镜像
    log_info "构建 Data Service Docker 镜像..."
    docker build -t ai-holdings-data-service:2.0.0 .

    # 停止旧容器（如果存在）
    if docker ps -a --format '{{.Names}}' | grep -q 'ai-holdings-data-service'; then
        log_info "停止旧容器..."
        docker stop ai-holdings-data-service 2>/dev/null || true
        docker rm ai-holdings-data-service 2>/dev/null || true
    fi

    # 运行新容器
    log_info "启动 Data Service 容器..."
    docker run -d \
        --name ai-holdings-data-service \
        --restart unless-stopped \
        -p 8000:8000 \
        --env-file "$PROJECT_ROOT/.env" \
        ai-holdings-data-service:2.0.0

    # 等待启动
    log_info "等待 Data Service 启动..."
    local retries=10
    while [ $retries -gt 0 ]; do
        if curl -s http://localhost:8000/health > /dev/null 2>&1; then
            log_info "Data Service 启动成功"
            curl -s http://localhost:8000/health | python3 -m json.tool
            return
        fi
        retries=$((retries - 1))
        sleep 2
    done

    log_error "Data Service 启动超时，请检查日志:"
    log_error "  docker logs ai-holdings-data-service"
    exit 1
}

# === OpenClaw Gateway 部署 (本地 Docker) ===
deploy_openclaw() {
    log_info "=== 部署 OpenClaw Gateway ==="

    local openclaw_dir="$PROJECT_ROOT/openclaw"

    if [ ! -d "$openclaw_dir" ]; then
        log_error "OpenClaw 目录不存在: $openclaw_dir"
        exit 1
    fi

    # 检查 Docker
    if ! command -v docker &> /dev/null; then
        log_error "Docker 未安装，请先安装 Docker"
        exit 1
    fi

    cd "$PROJECT_ROOT"

    # 构建 Docker 镜像
    log_info "构建 OpenClaw Gateway Docker 镜像..."
    docker build -f openclaw/Dockerfile -t ai-holdings-openclaw-gateway:2.0.0 .

    # 停止旧容器（如果存在）
    if docker ps -a --format '{{.Names}}' | grep -q 'ai-holdings-openclaw-gateway'; then
        log_info "停止旧容器..."
        docker stop ai-holdings-openclaw-gateway 2>/dev/null || true
        docker rm ai-holdings-openclaw-gateway 2>/dev/null || true
    fi

    # 运行新容器
    log_info "启动 OpenClaw Gateway 容器..."
    docker run -d \
        --name ai-holdings-openclaw-gateway \
        --restart unless-stopped \
        -p 8080:8080 \
        --env-file "$PROJECT_ROOT/.env" \
        ai-holdings-openclaw-gateway:2.0.0

    # 等待启动
    log_info "等待 OpenClaw Gateway 启动..."
    local retries=10
    while [ $retries -gt 0 ]; do
        if curl -s http://localhost:8080/health > /dev/null 2>&1; then
            log_info "OpenClaw Gateway 启动成功"
            curl -s http://localhost:8080/health | python3 -m json.tool
            return
        fi
        retries=$((retries - 1))
        sleep 2
    done

    log_error "OpenClaw Gateway 启动超时，请检查日志:"
    log_error "  docker logs ai-holdings-openclaw-gateway"
    exit 1
}

# === 部署后验证 ===
deploy_verify() {
    log_info "=== 部署后验证 ==="

    local failed=0

    # 验证 OpenClaw Gateway
    log_info "验证 OpenClaw Gateway..."
    if curl -sf http://localhost:8080/health > /dev/null 2>&1; then
        log_info "OpenClaw Gateway: 健康"
    else
        log_warn "OpenClaw Gateway: 不可达 (如果部署在远程服务器，请手动验证)"
        failed=1
    fi

    # 验证 Data Service
    log_info "验证 Data Service..."
    if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
        log_info "Data Service: 健康"
    else
        log_warn "Data Service: 不可达 (如果部署在远程服务器，请手动验证)"
        failed=1
    fi

    # 验证 WebApp
    log_info "验证 WebApp..."
    if command -v vercel &> /dev/null; then
        local webapp_url
        webapp_url=$(vercel ls --prod 2>/dev/null | head -1 || echo "")
        if [ -n "$webapp_url" ]; then
            log_info "WebApp URL: $webapp_url"
        fi
    fi

    # 验证数据库
    log_info "验证 Supabase 连接..."
    if [ -n "${SUPABASE_URL:-}" ]; then
        log_info "Supabase URL: $SUPABASE_URL"
    fi

    log_info "=== 部署验证完成 ==="
    if [ $failed -eq 0 ]; then
        log_info "所有服务正常运行"
    else
        log_warn "部分服务需要手动验证"
    fi
}

# === 主入口 ===
main() {
    local target="${1:-all}"

    echo ""
    echo "=========================================="
    echo " AI Holdings Analyzer v2 — 部署"
    echo " 目标: $target"
    echo "=========================================="
    echo ""

    check_env

    case "$target" in
        --target)
            shift
            target="$1"
            ;;
    esac

    case "$target" in
        migrate)
            deploy_migrate
            ;;
        webapp)
            deploy_webapp
            ;;
        data-service)
            deploy_data_service
            ;;
        openclaw)
            deploy_openclaw
            ;;
        all)
            deploy_migrate
            deploy_webapp
            deploy_data_service
            deploy_openclaw
            deploy_verify
            ;;
        *)
            echo "用法: $0 --target {migrate|webapp|data-service|openclaw|all}"
            exit 1
            ;;
    esac
}

main "$@"
