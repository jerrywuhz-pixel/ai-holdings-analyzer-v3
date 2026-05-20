from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os

from routers import quotes, billing, data_broker, portfolio
from services.sentry_service import init_sentry
from services.health_cache import HealthCache

# 健康缓存（减少 Supabase 读取，提升缓存命中率）
_health_cache = HealthCache()
APP_VERSION = os.getenv("APP_VERSION", "3.0.0-p0")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理。"""
    # Sentry 错误追踪（SENTRY_DSN 未配置时静默跳过）
    init_sentry()
    yield
    # 关闭时清理资源（如有需要）


app = FastAPI(title="AI Holdings Data Service", version=APP_VERSION, lifespan=lifespan)

# CORS: 生产环境必须通过环境变量指定具体域名，禁止 * + credentials 组合
_cors_origins = os.getenv("CORS_ALLOWED_ORIGINS", "")
if _cors_origins:
    allow_origins = [o.strip() for o in _cors_origins.split(",") if o.strip()]
else:
    # 开发环境默认值
    allow_origins = ["http://localhost:3000", "http://127.0.0.1:3000"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

# 注册行情路由，统一前缀 /api
app.include_router(quotes.router, prefix="/api")
app.include_router(billing.router, prefix="/api")
app.include_router(data_broker.router, prefix="/api")
app.include_router(portfolio.router, prefix="/api")


@app.get("/")
def root():
    """根路径返回服务基础信息。"""
    return {
        "service": "AI Holdings Data Service",
        "version": APP_VERSION,
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health")
async def health():
    """增强版健康检查：返回服务状态 + 网关心跳 + 数据源健康。"""
    gateway_status = await _health_cache.get_gateway_status()
    return {
        "status": "ok",
        "version": APP_VERSION,
        "gateway": gateway_status["gateway"],
        "data_sources": gateway_status["data_sources"],
    }
