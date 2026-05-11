#!/bin/bash
# ============================================================
# 配置 Vercel 环境变量
# ============================================================
# 用法: ./scripts/setup-vercel-env.sh
# 需要先创建 .env 文件并填入真实值

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
WEBAPP_DIR="$PROJECT_ROOT/webapp"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# 检查 .env
if [ ! -f "$PROJECT_ROOT/.env" ]; then
    log_error ".env 文件不存在，请先: cp .env.example .env && 填入真实值"
    exit 1
fi

set -a
source "$PROJECT_ROOT/.env"
set +a

cd "$WEBAPP_DIR"

# 检查 Vercel 关联
if [ ! -d ".vercel" ]; then
    log_error "WebApp 未关联 Vercel 项目，请先运行: cd webapp && vercel link --project ai-holdings-webapp --yes"
    exit 1
fi

# Vercel 环境变量映射（.env 变量名 → Vercel 环境变量名）
declare -A ENV_MAP=(
    ["SUPABASE_URL"]="NEXT_PUBLIC_SUPABASE_URL"
    ["SUPABASE_ANON_KEY"]="NEXT_PUBLIC_SUPABASE_ANON_KEY"
    ["SUPABASE_SERVICE_ROLE_KEY"]="SUPABASE_SERVICE_ROLE_KEY"
)

# 可选环境变量
declare -A OPTIONAL_ENV_MAP=(
    ["SENTRY_DSN"]="NEXT_PUBLIC_SENTRY_DSN"
)

log_info "配置 Vercel 生产环境变量..."

for src_key in "${!ENV_MAP[@]}"; do
    dest_key="${ENV_MAP[$src_key]}"
    value="${!src_key:-}"

    if [ -z "$value" ] || [[ "$value" == *"your"* ]] || [[ "$value" == *"placeholder"* ]]; then
        log_error "必需变量 $src_key 未配置，跳过"
        continue
    fi

    log_info "设置 $dest_key ..."
    echo "$value" | vercel env add "$dest_key" production 2>/dev/null || {
        # 如果变量已存在，先删除再添加
        vercel env rm "$dest_key" production -y 2>/dev/null || true
        echo "$value" | vercel env add "$dest_key" production 2>/dev/null || {
            log_error "设置 $dest_key 失败，请手动在 Vercel Dashboard 中配置"
        }
    }
done

for src_key in "${!OPTIONAL_ENV_MAP[@]}"; do
    dest_key="${OPTIONAL_ENV_MAP[$src_key]}"
    value="${!src_key:-}"

    if [ -n "$value" ] && [[ "$value" != *"your"* ]]; then
        log_info "设置可选变量 $dest_key ..."
        echo "$value" | vercel env add "$dest_key" production 2>/dev/null || true
    fi
done

log_info "环境变量配置完成"
log_info ""
log_info "下一步: 部署 WebApp"
log_info "  cd webapp && vercel --prod"
