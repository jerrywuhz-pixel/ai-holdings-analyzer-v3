"""
Sentry 错误追踪集成

提供统一的 Sentry 初始化和错误上报能力。
sentry-sdk 为可选依赖，未安装时所有方法静默跳过。

使用方式：
    # 应用启动时初始化
    from services.sentry_service import init_sentry
    init_sentry()

    # 在异常处理中上报
    from services.sentry_service import capture_exception
    try:
        ...
    except Exception as exc:
        capture_exception(exc)
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

try:
    import sentry_sdk
    from sentry_sdk.integrations.asyncio import AsyncioIntegration
    _HAS_SENTRY = True
except ImportError:
    _HAS_SENTRY = False


def init_sentry(
    dsn: Optional[str] = None,
    environment: Optional[str] = None,
    release: Optional[str] = None,
    traces_sample_rate: float = 0.1,
) -> bool:
    """
    初始化 Sentry SDK。

    Args:
        dsn: Sentry DSN，默认从环境变量 SENTRY_DSN 读取。
        environment: 环境标识，默认从 SENTRY_ENVIRONMENT 读取。
        release: 版本号，默认从 SENTRY_RELEASE 读取。
        traces_sample_rate: 性能追踪采样率，默认 0.1 (10%)。

    Returns:
        True 初始化成功，False 未配置或 SDK 不可用。
    """
    if not _HAS_SENTRY:
        logger.info("sentry-sdk not installed, skipping Sentry initialization")
        return False

    sentry_dsn = dsn or os.getenv("SENTRY_DSN")
    if not sentry_dsn:
        logger.info("SENTRY_DSN not configured, skipping Sentry initialization")
        return False

    sentry_env = environment or os.getenv("SENTRY_ENVIRONMENT", "development")
    sentry_release = release or os.getenv("SENTRY_RELEASE") or os.getenv("APP_VERSION", "3.0.0-p0")

    try:
        sentry_sdk.init(
            dsn=sentry_dsn,
            environment=sentry_env,
            release=sentry_release,
            traces_sample_rate=traces_sample_rate,
            integrations=[AsyncioIntegration()],
            # Don't send PII
            send_default_pii=False,
            # Attach stack traces to all log messages
            attach_stacktrace=True,
        )
        logger.info(
            "Sentry initialized: env=%s, release=%s, sample_rate=%.2f",
            sentry_env, sentry_release, traces_sample_rate,
        )
        return True
    except Exception as exc:
        logger.error("Failed to initialize Sentry: %s", exc)
        return False


def capture_exception(
    exc: Optional[BaseException] = None,
    context: Optional[dict[str, Any]] = None,
) -> None:
    """
    上报异常到 Sentry。

    Args:
        exc: 异常对象，为 None 时捕获当前异常。
        context: 附加上下文信息。
    """
    if not _HAS_SENTRY:
        return

    try:
        if context:
            with sentry_sdk.push_scope() as scope:
                for key, value in context.items():
                    scope.set_extra(key, value)
                sentry_sdk.capture_exception(exc)
        else:
            sentry_sdk.capture_exception(exc)
    except Exception:
        # Sentry 本身出错不应影响业务
        logger.debug("Failed to capture exception in Sentry")


def capture_message(
    message: str,
    level: str = "info",
    context: Optional[dict[str, Any]] = None,
) -> None:
    """
    上报消息到 Sentry。

    Args:
        message: 消息文本。
        level: 日志级别 "debug"/"info"/"warning"/"error"/"fatal"。
        context: 附加上下文信息。
    """
    if not _HAS_SENTRY:
        return

    try:
        with sentry_sdk.push_scope() as scope:
            scope.set_level(level)
            if context:
                for key, value in context.items():
                    scope.set_extra(key, value)
            sentry_sdk.capture_message(message, level=level)
    except Exception:
        logger.debug("Failed to capture message in Sentry")


def set_user(user_id: str, email: Optional[str] = None) -> None:
    """设置 Sentry 用户上下文。"""
    if not _HAS_SENTRY:
        return

    try:
        sentry_sdk.set_user({"id": user_id, "email": email or ""})
    except Exception:
        pass


def add_breadcrumb(
    category: str,
    message: str,
    level: str = "info",
    data: Optional[dict[str, Any]] = None,
) -> None:
    """添加面包屑（用于追踪错误前的事件序列）。"""
    if not _HAS_SENTRY:
        return

    try:
        sentry_sdk.add_breadcrumb(
            category=category,
            message=message,
            level=level,
            data=data or {},
        )
    except Exception:
        pass
