#!/bin/bash
# ============================================================
# OpenClaw 云端部署脚本 (Google Cloud Run)
# ============================================================
# 前置条件:
#   1. gcloud CLI 已安装并登录
#   2. GCP 项目已创建
#   3. Secret Manager 中已配置密钥
#
# 用法:
#   ./scripts/deploy-cloud.sh --target preflight     # 部署前置检查
#   ./scripts/deploy-cloud.sh --target gateway      # 部署 OpenClaw Gateway
#   ./scripts/deploy-cloud.sh --target data-service  # 部署 Data Service
#   ./scripts/deploy-cloud.sh --target all           # 全部部署
#   ./scripts/deploy-cloud.sh --target setup         # 初始化 GCP 资源

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step()  { echo -e "${CYAN}[STEP]${NC} $1"; }

# 默认配置
REGION="${GCP_REGION:-asia-southeast1}"
PROJECT_ID="${GCP_PROJECT_ID:-}"
REPO_NAME="openclaw"
GATEWAY_SERVICE="openclaw-gateway"
DATA_SERVICE="data-service"

# ── 环境检查 ──────────────────────────────────────────────

check_prerequisites() {
    log_step "检查前置条件..."

    if ! command -v gcloud &> /dev/null; then
        log_error "gcloud CLI 未安装"
        log_error "  安装: https://cloud.google.com/sdk/docs/install"
        exit 1
    fi

    if [ -z "$PROJECT_ID" ]; then
        PROJECT_ID=$(gcloud config get-value project 2>/dev/null || "")
    fi

    if [ -z "$PROJECT_ID" ]; then
        log_error "GCP 项目未设置"
        log_error "  设置: gcloud config set project YOUR_PROJECT_ID"
        log_error "  或:   export GCP_PROJECT_ID=your-project-id"
        exit 1
    fi

    log_info "GCP 项目: $PROJECT_ID"
    log_info "部署区域: $REGION"

    # 检查 .env 文件
    if [ -f "$PROJECT_ROOT/.env" ]; then
        set -a
        source "$PROJECT_ROOT/.env"
        set +a
        log_info "环境变量已加载"
    else
        log_warn ".env 文件不存在，部分变量可能缺失"
    fi
}

# ── 初始化 GCP 资源 ────────────────────────────────────────

setup_gcp() {
    log_step "初始化 GCP 资源..."

    # 启用 API
    log_info "启用 Cloud API..."
    gcloud services enable \
        run.googleapis.com \
        cloudbuild.googleapis.com \
        secretmanager.googleapis.com \
        artifactregistry.googleapis.com \
        cloudscheduler.googleapis.com \
        monitoring.googleapis.com \
        logging.googleapis.com \
        --project="$PROJECT_ID"

    # 创建 Artifact Registry
    log_info "创建 Artifact Registry..."
    gcloud artifacts repositories create "$REPO_NAME" \
        --repository-format=docker \
        --location="$REGION" \
        --project="$PROJECT_ID" \
        2>/dev/null || log_info "Registry 已存在"

    # 创建密钥
    log_info "创建 Secret Manager 密钥..."
    create_secret_if_missing "supabase-url" "${SUPABASE_URL:-}"
    create_secret_if_missing "supabase-service-role-key" "${SUPABASE_SERVICE_ROLE_KEY:-}"
    create_secret_if_missing "supabase-anon-key" "${SUPABASE_ANON_KEY:-}"
    create_secret_if_missing "wechat-app-id" "${WECHAT_APP_ID:-}"
    create_secret_if_missing "wechat-app-secret" "${WECHAT_APP_SECRET:-}"
    create_secret_if_missing "openai-api-key" "${OPENAI_API_KEY:-}"
    create_secret_if_missing "minimax-api-key" "${MINIMAX_API_KEY:-}"
    create_secret_if_missing "tushare-token" "${TUSHARE_TOKEN:-}"
    create_secret_if_missing "openclaw-delivery-webhook-url" "${OPENCLAW_DELIVERY_WEBHOOK_URL:-}"
    create_secret_if_missing "openclaw-delivery-webhook-secret" "${OPENCLAW_DELIVERY_WEBHOOK_SECRET:-}"
    create_secret_if_missing "sentry-dsn" "${SENTRY_DSN:-}"
    create_secret_if_missing "fx-rate-api-key" "${FX_RATE_API_KEY:-}"

    log_info "GCP 资源初始化完成"
}

create_secret_if_missing() {
    local name="$1"
    local value="$2"

    if [ -z "$value" ]; then
        log_warn "  跳过 $name (值为空)"
        return
    fi

    if gcloud secrets describe "$name" --project="$PROJECT_ID" &>/dev/null; then
        # 更新现有密钥版本
        echo -n "$value" | gcloud secrets versions add "$name" --data-file=- --project="$PROJECT_ID"
        log_info "  $name: 已更新"
    else
        # 创建新密钥
        echo -n "$value" | gcloud secrets create "$name" --data-file=- --project="$PROJECT_ID"
        log_info "  $name: 已创建"
    fi

    # 授权 Cloud Run 访问
    local SA="${PROJECT_ID}@appspot.gserviceaccount.com"
    gcloud secrets add-iam-policy-binding "$name" \
        --member="serviceAccount:$SA" \
        --role="roles/secretmanager.secretAccessor" \
        --project="$PROJECT_ID" \
        2>/dev/null || true
}

# ── 构建 Docker 镜像 ──────────────────────────────────────

build_gateway() {
    log_step "构建 OpenClaw Gateway 镜像..."

    cd "$PROJECT_ROOT"

    local image="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/gateway"

    # 使用 Cloud Build
    gcloud builds submit \
        --tag "${image}:latest" \
        --project="$PROJECT_ID" \
        --config=- \
        <<EOF
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-f', 'openclaw/Dockerfile', '-t', '${image}:latest', '.']
images:
  - '${image}:latest'
EOF

    log_info "Gateway 镜像构建完成: ${image}:latest"
}

build_data_service() {
    log_step "构建 Data Service 镜像..."

    cd "$PROJECT_ROOT/data-service"

    local image="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/data-service"

    gcloud builds submit \
        --tag "${image}:latest" \
        --project="$PROJECT_ID" \
        .

    log_info "Data Service 镜像构建完成: ${image}:latest"
}

# ── 部署 Cloud Run ────────────────────────────────────────

deploy_gateway() {
    log_step "部署 OpenClaw Gateway 到 Cloud Run..."

    local image="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/gateway:latest"

    gcloud run deploy "$GATEWAY_SERVICE" \
        --image="$image" \
        --region="$REGION" \
        --platform=managed \
        --port=8080 \
        --cpu=1 \
        --memory=512Mi \
        --min-instances=1 \
        --max-instances=10 \
        --set-env-vars="DEPLOYMENT_MODE=cloud,OPENCLAW_DEPLOYMENT_MODE=cloud,OPENCLAW_DELIVERY_MODE=webhook,GBRAIN_LIVE_MODELS_ENABLED=true,HERMES_ARTIFACT_STORAGE_BACKEND=supabase,HERMES_ARTIFACT_BASE_URI=supabase://hermes-artifacts,HISTORICAL_STORAGE_BACKEND=supabase_storage,FX_RATES_SOURCE=trusted_http_fx,WEBAPP_BASE_URL=${WEBAPP_BASE_URL:-}" \
        --set-secrets="SUPABASE_URL=supabase-url:latest,SUPABASE_SERVICE_ROLE_KEY=supabase-service-role-key:latest,WECHAT_APP_ID=wechat-app-id:latest,WECHAT_APP_SECRET=wechat-app-secret:latest,OPENAI_API_KEY=openai-api-key:latest,MINIMAX_API_KEY=minimax-api-key:latest,OPENCLAW_DELIVERY_WEBHOOK_URL=openclaw-delivery-webhook-url:latest,OPENCLAW_DELIVERY_WEBHOOK_SECRET=openclaw-delivery-webhook-secret:latest,SENTRY_DSN=sentry-dsn:latest,FX_RATE_API_KEY=fx-rate-api-key:latest" \
        --allow-unauthenticated \
        --project="$PROJECT_ID"

    # 获取服务 URL
    local gateway_url
    gateway_url=$(gcloud run services describe "$GATEWAY_SERVICE" \
        --region="$REGION" \
        --format="value(status.url)" \
        --project="$PROJECT_ID")

    log_info "Gateway 已部署: $gateway_url"
    echo ""
    echo "  OpenClaw Gateway URL: $gateway_url"
    echo "  Health Check:         $gateway_url/health"
    echo "  API Docs:             $gateway_url/docs"
    echo ""
}

deploy_data_service() {
    log_step "部署 Data Service 到 Cloud Run..."

    local image="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/data-service:latest"

    gcloud run deploy "$DATA_SERVICE" \
        --image="$image" \
        --region="$REGION" \
        --platform=managed \
        --port=8000 \
        --cpu=1 \
        --memory=512Mi \
        --min-instances=0 \
        --max-instances=5 \
        --set-env-vars="HISTORICAL_STORAGE_BACKEND=supabase_storage,FX_RATES_SOURCE=trusted_http_fx,FX_RATE_ENDPOINT=${FX_RATE_ENDPOINT:-},CORS_ALLOWED_ORIGINS=${CORS_ALLOWED_ORIGINS:-}" \
        --set-secrets="SUPABASE_URL=supabase-url:latest,SUPABASE_SERVICE_ROLE_KEY=supabase-service-role-key:latest,TUSHARE_TOKEN=tushare-token:latest,SENTRY_DSN=sentry-dsn:latest,FX_RATE_API_KEY=fx-rate-api-key:latest" \
        --no-allow-unauthenticated \
        --project="$PROJECT_ID"

    # 获取服务 URL
    local ds_url
    ds_url=$(gcloud run services describe "$DATA_SERVICE" \
        --region="$REGION" \
        --format="value(status.url)" \
        --project="$PROJECT_ID")

    log_info "Data Service 已部署: $ds_url"
}

# ── 配置 Cron 定时任务 ─────────────────────────────────────

setup_cron() {
    log_step "配置 Cloud Scheduler 定时任务..."

    local gateway_url
    gateway_url=$(gcloud run services describe "$GATEWAY_SERVICE" \
        --region="$REGION" \
        --format="value(status.url)" \
        --project="$PROJECT_ID")

    if [ -z "$gateway_url" ]; then
        log_error "Gateway URL 为空，请先部署 Gateway"
        return 1
    fi

    local SA_EMAIL="${PROJECT_ID}@appspot.gserviceaccount.com"

    # 每日市场扫描 (工作日 15:30 CST = 07:30 UTC)
    gcloud scheduler jobs create http daily-market-scan \
        --schedule="30 7 * * 1-5" \
        --uri="${gateway_url}/api/cron/daily-scan" \
        --http-method=POST \
        --oidc-service-account-email="$SA_EMAIL" \
        --oidc-token-audience="$gateway_url" \
        --project="$PROJECT_ID" \
        2>/dev/null || log_info "daily-market-scan 任务已存在"

    # 开盘前止盈行动计划 (工作日 09:00 CST = 01:00 UTC)
    gcloud scheduler jobs create http daily-profit-taking \
        --schedule="0 1 * * 1-5" \
        --uri="${gateway_url}/api/cron/profit-taking" \
        --http-method=POST \
        --oidc-service-account-email="$SA_EMAIL" \
        --oidc-token-audience="$gateway_url" \
        --project="$PROJECT_ID" \
        2>/dev/null || log_info "daily-profit-taking 任务已存在"

    # Sell Put 候选评分 (工作日 16:20 CST = 08:20 UTC)
    gcloud scheduler jobs create http sellput-score \
        --schedule="20 8 * * 1-5" \
        --uri="${gateway_url}/api/cron/sellput-score" \
        --http-method=POST \
        --oidc-service-account-email="$SA_EMAIL" \
        --oidc-token-audience="$gateway_url" \
        --project="$PROJECT_ID" \
        2>/dev/null || log_info "sellput-score 任务已存在"

    # 心跳检测 (每 5 分钟)
    gcloud scheduler jobs create http heartbeat-check \
        --schedule="*/5 * * * *" \
        --uri="${gateway_url}/api/cron/heartbeat" \
        --http-method=POST \
        --oidc-service-account-email="$SA_EMAIL" \
        --oidc-token-audience="$gateway_url" \
        --project="$PROJECT_ID" \
        2>/dev/null || log_info "heartbeat-check 任务已存在"

    # 超时任务检查 (每 10 分钟)
    gcloud scheduler jobs create http stale-jobs-check \
        --schedule="*/10 * * * *" \
        --uri="${gateway_url}/api/cron/stale-jobs" \
        --http-method=POST \
        --oidc-service-account-email="$SA_EMAIL" \
        --oidc-token-audience="$gateway_url" \
        --project="$PROJECT_ID" \
        2>/dev/null || log_info "stale-jobs-check 任务已存在"

    log_info "定时任务配置完成"
}

# ── 部署后验证 ──────────────────────────────────────────────

verify_deployment() {
    log_step "部署后验证..."

    local gateway_url
    gateway_url=$(gcloud run services describe "$GATEWAY_SERVICE" \
        --region="$REGION" \
        --format="value(status.url)" \
        --project="$PROJECT_ID" 2>/dev/null || echo "")

    if [ -n "$gateway_url" ]; then
        log_info "Gateway URL: $gateway_url"
        local health_resp
        health_resp=$(curl -sf "${gateway_url}/health" 2>/dev/null || echo "FAILED")
        if [ "$health_resp" != "FAILED" ]; then
            log_info "Gateway 健康检查: 通过"
            echo "$health_resp" | python3 -m json.tool 2>/dev/null || echo "$health_resp"
        else
            log_warn "Gateway 健康检查: 失败 (服务可能需要几分钟启动)"
        fi
    else
        log_warn "Gateway 服务未找到"
    fi

    log_step "运行云端部署监控探针..."
    python3 "$SCRIPT_DIR/cloud_deployment_monitor.py" \
        --project "$PROJECT_ID" \
        --region "$REGION"

    log_info "=== 部署验证完成 ==="
}

# ── 主入口 ─────────────────────────────────────────────────

main() {
    local target="${1:-all}"

    case "$target" in
        --target)
            shift
            target="$1"
            ;;
    esac

    echo ""
    echo "=========================================="
    echo " OpenClaw 云端部署 (Google Cloud Run)"
    echo " 项目: ${PROJECT_ID:-未设置}"
    echo " 区域: $REGION"
    echo " 目标: $target"
    echo "=========================================="
    echo ""

    if [ "$target" = "preflight" ]; then
        python3 "$SCRIPT_DIR/cloud_preflight.py" --profile production
        return
    fi

    check_prerequisites

    case "$target" in
        preflight)
            python3 "$SCRIPT_DIR/cloud_preflight.py" --profile production
            ;;
        setup)
            setup_gcp
            ;;
        gateway)
            build_gateway
            deploy_gateway
            ;;
        data-service)
            build_data_service
            deploy_data_service
            ;;
        cron)
            setup_cron
            ;;
        all)
            setup_gcp
            build_gateway
            build_data_service
            deploy_gateway
            deploy_data_service
            setup_cron
            verify_deployment
            ;;
        verify)
            verify_deployment
            ;;
        monitor)
            python3 "$SCRIPT_DIR/cloud_deployment_monitor.py" \
                --project "$PROJECT_ID" \
                --region "$REGION"
            ;;
        *)
            echo "用法: $0 --target {preflight|setup|gateway|data-service|cron|all|verify|monitor}"
            echo ""
            echo "  preflight    - 检查云端部署前置工具与生产环境变量"
            echo "  setup        - 初始化 GCP 资源 (API, Registry, Secrets)"
            echo "  gateway      - 构建并部署 OpenClaw Gateway"
            echo "  data-service - 构建并部署 Data Service"
            echo "  cron         - 配置 Cloud Scheduler 定时任务"
            echo "  all          - 全部部署"
            echo "  verify       - 验证部署状态"
            echo "  monitor      - 运行 Cloud Run / Scheduler 部署监控探针"
            exit 1
            ;;
    esac
}

main "$@"
