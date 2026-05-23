#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.production_readiness import ENV_FILE, load_env_file


Status = str


@dataclass(frozen=True)
class DependencyResult:
    name: str
    kind: str
    status: Status
    detail: str
    required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "status": self.status,
            "detail": self.detail,
            "required": self.required,
        }


@dataclass(frozen=True)
class ProductFeature:
    id: str
    name: str
    description: str
    dependencies: list[DependencyResult]
    actions: list[str]

    @property
    def status(self) -> Status:
        required_failures = [dep for dep in self.dependencies if dep.required and dep.status == "fail"]
        if required_failures:
            return "fail"
        if any(dep.status == "warn" for dep in self.dependencies):
            return "warn"
        return "pass"

    @property
    def blockers(self) -> list[str]:
        return [
            dep.detail
            for dep in self.dependencies
            if dep.required and dep.status == "fail"
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "dependencies": [dep.to_dict() for dep in self.dependencies],
            "blockers": self.blockers,
            "actions": self.actions,
        }


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def _is_placeholder(value: str) -> bool:
    normalized = value.strip().strip('"').strip("'").lower()
    if not normalized:
        return True
    exact_placeholders = {
        "todo",
        "tbd",
        "changeme",
        "change-me",
        "replace-me",
        "placeholder",
        "your-value",
    }
    if normalized in exact_placeholders:
        return True
    placeholder_markers = (
        "your-project",
        "your_",
        "example.",
        "<",
        ">",
        "user:password@",
        "rds-internal-host",
        "redis-internal-host",
    )
    return any(marker in normalized for marker in placeholder_markers)


def configured_env(
    name: str,
    *,
    profile: str,
    expected: str | None = None,
    allowed: set[str] | None = None,
    required: bool = True,
) -> DependencyResult:
    value = _env(name)
    if _is_placeholder(value):
        status = "warn" if profile == "local" or not required else "fail"
        detail = f"{name} is missing or still a placeholder"
        return DependencyResult(name, "env", status, detail, required)

    normalized = value.lower()
    if expected is not None and normalized != expected.lower():
        status = "warn" if profile == "local" else "fail"
        return DependencyResult(
            name,
            "env",
            status,
            f"{name}={value}; expected {expected}",
            required,
        )

    if allowed is not None and normalized not in {item.lower() for item in allowed}:
        status = "warn" if profile == "local" else "fail"
        return DependencyResult(
            name,
            "env",
            status,
            f"{name}={value}; expected one of {sorted(allowed)}",
            required,
        )

    return DependencyResult(name, "env", "pass", f"{name} is configured", required)


def configured_env_as(dependency_name: str, name: str, **kwargs: Any) -> DependencyResult:
    result = configured_env(name, **kwargs)
    return DependencyResult(
        dependency_name,
        result.kind,
        result.status,
        result.detail,
        result.required,
    )


def any_configured_env(names: Iterable[str], *, profile: str, dependency_name: str) -> DependencyResult:
    configured = [name for name in names if not _is_placeholder(_env(name))]
    if configured:
        return DependencyResult(
            dependency_name,
            "env",
            "pass",
            f"configured via {', '.join(configured)}",
        )
    status = "warn" if profile == "local" else "fail"
    return DependencyResult(
        dependency_name,
        "env",
        status,
        f"set one of: {', '.join(names)}",
    )


def all_configured_env(names: Iterable[str], *, profile: str, dependency_name: str, required: bool = True) -> DependencyResult:
    missing = [name for name in names if _is_placeholder(_env(name))]
    if not missing:
        return DependencyResult(
            dependency_name,
            "env",
            "pass",
            f"configured via {', '.join(names)}",
            required,
        )
    status = "warn" if profile == "local" or not required else "fail"
    return DependencyResult(
        dependency_name,
        "env",
        status,
        f"set all of: {', '.join(missing)}",
        required,
    )


def local_auth_database_url(profile: str) -> DependencyResult:
    direct = any_configured_env(
        ["WEBAPP_DATABASE_URL", "DATABASE_URL"],
        profile=profile,
        dependency_name="local_auth_database_url",
    )
    if direct.status == "pass" or profile != "lightweight":
        return direct

    compose_postgres = all_configured_env(
        ["POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"],
        profile=profile,
        dependency_name="local_auth_database_url",
    )
    if compose_postgres.status == "pass":
        return DependencyResult(
            "local_auth_database_url",
            "env",
            "pass",
            "configured via docker-compose DATABASE_URL from POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB",
        )
    return direct


def openai_deep_model_auth(profile: str) -> DependencyResult:
    if not _is_placeholder(_env("OPENAI_API_KEY")):
        return DependencyResult(
            "openai_deep_model_auth",
            "env",
            "pass",
            "configured via OPENAI_API_KEY",
        )

    profile_names = ["OPENAI_CODEX_AUTH_PROFILE", "HERMES_AUTH_PROFILE_ID", "OPENCLAW_AUTH_PROFILE"]
    bridge_names = ["OPENAI_CODEX_BRIDGE_BASE_URL", "HERMES_CODEX_GATEWAY_BASE_URL", "OPENCLAW_CODEX_GATEWAY_BASE_URL"]
    configured_profiles = [name for name in profile_names if not _is_placeholder(_env(name))]
    configured_bridges = [name for name in bridge_names if not _is_placeholder(_env(name))]
    if configured_profiles and configured_bridges:
        return DependencyResult(
            "openai_deep_model_auth",
            "env",
            "pass",
            f"configured via {configured_profiles[0]} + {configured_bridges[0]}",
        )

    status = "warn" if profile == "local" else "fail"
    return DependencyResult(
        "openai_deep_model_auth",
        "env",
        status,
        "set OPENAI_API_KEY or OPENAI_CODEX_AUTH_PROFILE+OPENAI_CODEX_BRIDGE_BASE_URL",
    )


def _read_repo_file(relative_path: str) -> str:
    path = PROJECT_ROOT / relative_path
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def repo_file_contains(
    name: str,
    relative_path: str,
    patterns: list[str],
    detail: str,
) -> DependencyResult:
    text = _read_repo_file(relative_path)
    missing = [pattern for pattern in patterns if pattern not in text]
    if not text:
        return DependencyResult(name, "repo", "fail", f"{relative_path} is missing")
    if missing:
        return DependencyResult(
            name,
            "repo",
            "fail",
            f"{detail}; missing code marker(s): {', '.join(missing)}",
        )
    return DependencyResult(name, "repo", "pass", detail)


def repo_file_contains_any(
    name: str,
    relative_path: str,
    patterns: list[str],
    detail: str,
) -> DependencyResult:
    text = _read_repo_file(relative_path)
    if not text:
        return DependencyResult(name, "repo", "fail", f"{relative_path} is missing")
    if any(pattern in text for pattern in patterns):
        return DependencyResult(name, "repo", "pass", detail)
    return DependencyResult(
        name,
        "repo",
        "fail",
        f"{detail}; missing one of code marker(s): {', '.join(patterns)}",
    )


def repo_path_exists(name: str, relative_paths: list[str], detail: str) -> DependencyResult:
    found = [path for path in relative_paths if (PROJECT_ROOT / path).exists()]
    if found:
        return DependencyResult(name, "repo", "pass", detail)
    return DependencyResult(
        name,
        "repo",
        "fail",
        f"{detail}; missing path(s): {', '.join(relative_paths)}",
    )


def repo_tree_contains(
    name: str,
    roots: list[str],
    patterns: list[str],
    detail: str,
    *,
    suffixes: tuple[str, ...] = (".py", ".ts", ".tsx", ".sql", ".md"),
) -> DependencyResult:
    found = {pattern: False for pattern in patterns}
    for root in roots:
        root_path = PROJECT_ROOT / root
        if not root_path.exists():
            continue
        for path in root_path.rglob("*"):
            if not path.is_file() or path.suffix not in suffixes:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for pattern in patterns:
                if pattern in text:
                    found[pattern] = True
    missing = [pattern for pattern, exists in found.items() if not exists]
    if missing:
        return DependencyResult(
            name,
            "repo",
            "fail",
            f"{detail}; missing code marker(s): {', '.join(missing)}",
        )
    return DependencyResult(name, "repo", "pass", detail)


def _webapp_registration_auth(profile: str) -> ProductFeature:
    shared_dependencies = [
        repo_file_contains(
            "webapp_login_ui",
            "webapp/src/app/login/LoginForm.tsx",
            ["/api/auth/login"],
            "WebApp login form calls the server-side login API",
        ),
        repo_file_contains(
            "webapp_signup_ui",
            "webapp/src/app/login/LoginForm.tsx",
            ["/api/auth/register"],
            "WebApp login form exposes the server-side sign-up flow",
        ),
        repo_path_exists(
            "tenant_bootstrap_triggers",
            [
                "supabase/migrations/000006_auth_sync_trigger.sql",
                "supabase/migrations/000024_holdings_v3_p0_schema.sql",
            ],
            "Supabase auth sync and tenant account bootstrap migrations exist",
        ),
    ]
    if profile == "lightweight":
        auth_dependencies = [
            configured_env_as("local_auth_mode", "AUTH_MODE", profile=profile, expected="local"),
            configured_env("LOCAL_AUTH_ENABLED", profile=profile, expected="true"),
            configured_env("LOCAL_AUTH_REGISTRATION_ENABLED", profile=profile, expected="true"),
            local_auth_database_url(profile),
            configured_env("AUTH_SESSION_SECRET", profile=profile),
            all_configured_env(
                ["SMTP_HOST", "SMTP_FROM"],
                profile=profile,
                dependency_name="smtp_verification_delivery",
            ),
            configured_env("WEBAPP_BASE_URL", profile=profile),
        ]
        return ProductFeature(
            id="webapp_registration_auth",
            name="WebApp 注册 / 登录 / tenant 初始化",
            description="轻量服务器阶段使用本地 Auth 完成 WebApp 邮箱注册、验证码验证、登录与 tenant 初始化。",
            dependencies=shared_dependencies + auth_dependencies,
            actions=[
                "轻量服务器使用 AUTH_MODE=local、LOCAL_AUTH_REGISTRATION_ENABLED=true 和数据库连接完成第一阶段注册验收。",
                "上线前用真实邮箱完成注册、登录、onboarding tenant bootstrap 的烟测；正式切流仍需切换到 Supabase/Auth 或等价生产 Auth。",
            ],
        )

    return ProductFeature(
        id="webapp_registration_auth",
        name="WebApp 注册 / 登录 / tenant 初始化",
        description="用户可以通过 WebApp 邮箱密码注册或登录，并在注册初始化阶段确保 users 与 tenant_accounts 就绪。",
        dependencies=shared_dependencies + [
            configured_env("NEXT_PUBLIC_SUPABASE_URL", profile=profile),
            configured_env("NEXT_PUBLIC_SUPABASE_ANON_KEY", profile=profile),
            configured_env("SUPABASE_URL", profile=profile),
            configured_env("SUPABASE_ANON_KEY", profile=profile),
            configured_env("SUPABASE_SERVICE_ROLE_KEY", profile=profile),
            configured_env("SUPABASE_JWT_SECRET", profile=profile),
            configured_env("WEBAPP_BASE_URL", profile=profile),
        ],
        actions=[
            "在生产 Supabase/Auth 边界中启用邮箱注册策略，并完成回调域名白名单。",
            "上线前用真实邮箱完成注册、登录、onboarding tenant bootstrap 的烟测。",
        ],
    )


def _registration_onboarding_initialization(profile: str) -> ProductFeature:
    return ProductFeature(
        id="registration_onboarding_initialization",
        name="注册后的持仓系统初始化向导",
        description="新用户注册后必须完成资产画像、微信 Clawbot、Futu connector 和初始化检查，才能进入 3.0 持仓系统。",
        dependencies=[
            repo_path_exists(
                "onboarding_schema",
                ["supabase/migrations/000028_onboarding_registration_flow.sql"],
                "Onboarding sessions, tenant settings, WeChat auth, bot credentials, and audit schema exist",
            ),
            repo_file_contains_any(
                "register_redirects_to_onboarding",
                "webapp/src/app/login/LoginForm.tsx",
                ["router.push('/onboarding')", "router.push('/onboarding/welcome')"],
                "Registration and login enter the onboarding gate before the app home",
            ),
            repo_path_exists(
                "onboarding_profile_page",
                [
                    "webapp/src/app/onboarding/page.tsx",
                    "webapp/src/app/onboarding/profile/page.tsx",
                ],
                "WebApp has an onboarding entry and profile initialization page",
            ),
            repo_path_exists(
                "wechat_clawbot_onboarding",
                [
                    "webapp/src/app/onboarding/wechat/page.tsx",
                    "webapp/src/lib/clawbot.ts",
                ],
                "WebApp has Clawbot QR/status/getupdates onboarding support",
            ),
            repo_path_exists(
                "futu_pairing_onboarding",
                ["webapp/src/app/onboarding/broker/page.tsx"],
                "WebApp has Futu connector pairing onboarding page",
            ),
            repo_path_exists(
                "onboarding_review_gate",
                ["webapp/src/app/onboarding/review/page.tsx"],
                "WebApp has an onboarding review gate",
            ),
            configured_env("WECHAT_CLAWBOT_API_BASE_URL", profile=profile),
            configured_env("ONBOARDING_CREDENTIAL_ENCRYPTION_KEY", profile=profile),
            configured_env("DATA_SERVICE_INTERNAL_TOKEN", profile=profile),
        ],
        actions=[
            "注册后进入 /onboarding，按状态机推进 profile/wechat/broker/review。",
            "生产环境必须把 Clawbot token 加密密钥、Data Service internal token 放入阿里云 Secret/KMS。",
        ],
    )


def _tenant_live_data(profile: str) -> ProductFeature:
    return ProductFeature(
        id="tenant_live_data_webapp",
        name="WebApp 持仓视图 tenant 化实时数据",
        description="登录用户访问 holdings/data/sell-put 页面时读取自己的 tenant 数据，而不是 demo 或全局 tenant。",
        dependencies=[
            repo_file_contains(
                "portfolio_overview_endpoint",
                "data-service/src/routers/portfolio.py",
                ["/v3/portfolio/overview", "/v3/portfolio/positions"],
                "Data service exposes portfolio overview and positions endpoints",
            ),
            repo_path_exists(
                "webapp_holdings_pages",
                [
                    "webapp/src/app/holdings/page.tsx",
                    "webapp/src/app/data/page.tsx",
                    "webapp/src/app/sell-put/page.tsx",
                ],
                "WebApp has holdings, data, and sell-put surfaces",
            ),
            repo_file_contains(
                "tenant_scoped_fetch",
                "webapp/src/lib/p0-api.ts",
                ["tenantId", "fetchP0ApiSnapshot("],
                "WebApp data fetch can accept the authenticated user's tenant id",
            ),
            any_configured_env(
                ["NEXT_PUBLIC_DATA_SERVICE_URL", "DATA_SERVICE_URL"],
                profile=profile,
                dependency_name="data_service_url",
            ),
        ],
        actions=[
            "在阿里云 SAE WebApp/DataService 环境中配置 NEXT_PUBLIC_DATA_SERVICE_URL 或 DATA_SERVICE_URL。",
            "上线前用两个真实用户账号验证 tenant 隔离，确认 fallback/demo 只显示为 degraded/reference。",
        ],
    )


def _wechat_claw_binding(profile: str) -> ProductFeature:
    shared_dependencies = [
        repo_path_exists(
            "channel_bindings_schema",
            [
                "supabase/migrations/000024_holdings_v3_p0_schema.sql",
                "supabase/migrations/000029_wechat_clawbot_session_key.sql",
            ],
            "channel_bindings schema and WeChat QR session metadata migration exist",
        ),
        repo_file_contains(
            "wechat_message_gateway",
            "openclaw/gateway/routers/openclaw_gateway.py",
            ["prefix=\"/api/openclaw\"", "/wechat/messages", "channel_binding_id"],
            "OpenClaw gateway can resolve and persist channel binding context",
        ),
        repo_tree_contains(
            "webapp_self_service_binding",
            ["webapp/src"],
            ["/api/onboarding/wechat/binding", "channel_bindings", "get_bot_qrcode"],
            "WebApp has self-service QR binding and channel_bindings persistence for WeChat Claw",
        ),
    ]

    if profile == "lightweight":
        return ProductFeature(
            id="wechat_claw_binding",
            name="绑定微信 Claw 插件 / 消息路由",
            description="轻量服务器阶段通过 Tencent OpenClaw Weixin 二维码连接微信 ClawBot，并写入当前 tenant 的 channel_binding。",
            dependencies=shared_dependencies + [
                configured_env_as("wechat_clawbot_api", "WECHAT_CLAWBOT_API_BASE_URL", profile=profile),
                configured_env("ONBOARDING_CREDENTIAL_ENCRYPTION_KEY", profile=profile),
                configured_env_as(
                    "openclaw_delivery_mode",
                    "OPENCLAW_DELIVERY_MODE",
                    profile=profile,
                    allowed={"log", "webhook"},
                ),
                configured_env("OPENCLAW_SKILL_KEY", profile=profile),
            ],
            actions=[
                "轻量服务器阶段用 WebApp 二维码弹窗完成 ClawBot 授权，并确认 channel_bindings 写入。",
                "正式消息回写切流前再把 OPENCLAW_DELIVERY_MODE 从 log 切到 webhook 并配置 webhook secret。",
            ],
        )

    return ProductFeature(
        id="wechat_claw_binding",
        name="绑定微信 Claw 插件 / 消息路由",
        description="用户可在 WebApp 注册初始化阶段绑定微信 ClawBot，OpenClaw 微信消息能回到正确 tenant 与 channel_binding。",
        dependencies=shared_dependencies + [
            configured_env_as("wechat_clawbot_api", "WECHAT_CLAWBOT_API_BASE_URL", profile=profile),
            configured_env("ONBOARDING_CREDENTIAL_ENCRYPTION_KEY", profile=profile),
            configured_env("OPENCLAW_DELIVERY_MODE", profile=profile, expected="webhook"),
            configured_env("OPENCLAW_DELIVERY_WEBHOOK_URL", profile=profile),
            configured_env("OPENCLAW_DELIVERY_WEBHOOK_SECRET", profile=profile),
            configured_env("OPENCLAW_SKILL_KEY", profile=profile),
            configured_env("OPENCLAW_CRON_SECRET", profile=profile),
        ],
        actions=[
            "配置 WECHAT_CLAWBOT_API_BASE_URL、ClawBot token 加密密钥与 OpenClaw webhook delivery secret。",
            "用注册初始化流程完成二维码授权，再跑真实微信消息进入 tenant 解析的端到端烟测。",
        ],
    )


def _futu_user_local_sync(profile: str) -> ProductFeature:
    return ProductFeature(
        id="futu_user_local_sync",
        name="用户本地 Futu 连接器同步持仓",
        description="每个用户在本地运行只读 Futu connector，云端通过 poll/upload 控制面同步股票、期权、现金与保证金。",
        dependencies=[
            repo_path_exists(
                "futu_local_connector_package",
                [
                    "local_connectors/futu_opend/polling.py",
                    "local_connectors/requirements.txt",
                ],
                "Local Futu connector package and Python requirements exist",
            ),
            repo_path_exists(
                "broker_connector_schema",
                ["supabase/migrations/000027_broker_connector_instances.sql"],
                "broker_connector_instances schema exists",
            ),
            repo_file_contains(
                "futu_sync_endpoint",
                "data-service/src/routers/data_broker.py",
                ["/v3/broker/futu/sync", "/v3/broker/futu/snapshot"],
                "Data service exposes Futu snapshot/sync endpoints",
            ),
            repo_tree_contains(
                "cloud_connector_poll_upload",
                ["data-service/src", "openclaw"],
                ["/connectors/poll", "/connectors/upload"],
                "Cloud API exposes user-local connector poll/upload control plane",
            ),
            configured_env("FUTU_CONNECTOR_MODE", profile=profile, expected="user_local_polling"),
            configured_env("FUTU_CONNECTOR_READ_ONLY", profile=profile, expected="true"),
            configured_env("FUTU_CONNECTOR_POLL_ENDPOINT", profile=profile),
            configured_env("FUTU_CONNECTOR_UPLOAD_ENDPOINT", profile=profile),
            configured_env("FUTU_CONNECTOR_PAIRING_TOKEN", profile=profile),
        ],
        actions=[
            "设置 FUTU_CONNECTOR_MODE=user_local_polling、poll/upload URL 与每个用户本地 connector 的 pairing token。",
            "把当前 local_dev_direct 烟测扩展成 user_local_polling 云端端到端烟测。",
        ],
    )


def _stock_and_option_analysis(profile: str) -> ProductFeature:
    return ProductFeature(
        id="stock_option_query_analysis",
        name="股票 / 期权查询与 Sell Put 分析",
        description="用户可查询股票行情、期权链，并基于真实持仓/保证金做 Sell Put 分析。",
        dependencies=[
            repo_file_contains(
                "quote_endpoints",
                "data-service/src/routers/quotes.py",
                ["/quote/{symbol}", "/search"],
                "Data service exposes quote and search endpoints",
            ),
            repo_file_contains(
                "option_analysis_endpoints",
                "data-service/src/routers/data_broker.py",
                ["/v3/options/sell-put/analyze", "/v3/options/sell-put/analyze-from-futu"],
                "Data service exposes Sell Put analysis endpoints",
            ),
            configured_env("TUSHARE_TOKEN", profile=profile),
            repo_file_contains(
                "ftshare_market_data_adapter",
                "data-service/src/adapters/ftshare.py",
                ["FtShareMarketDataAdapter", "stock-security-info"],
                "Data service wraps the ClawHub ftshare-market-data skill",
            ),
            repo_path_exists(
                "ftshare_market_data_skill",
                ["openclaw/skills/ftshare-market-data/run.py"],
                "ClawHub ftshare-market-data skill is installed under OpenClaw skills",
            ),
            any_configured_env(
                ["FX_RATES_JSON", "FX_RATE_ENDPOINT"],
                profile=profile,
                dependency_name="trusted_fx_rates",
            ),
            configured_env("SELL_PUT_FRESHNESS_SECONDS", profile=profile, required=False),
            configured_env("BROKER_SNAPSHOT_MAX_STALENESS_SECONDS", profile=profile, required=False),
        ],
        actions=[
            "生产环境补齐 Tushare / FTShare / 长桥 / 腾讯财经数据源策略，明确 A 股、港股、美股兜底顺序。",
            "Sell Put 分析必须依赖新鲜期权链和保证金快照，过期时只给 observation，不给 actionable 建议。",
        ],
    )


def _ai_analysis(profile: str) -> ProductFeature:
    return ProductFeature(
        id="ai_research_analysis",
        name="AI 深度研究 / 分析输出",
        description="Hermes/gbrain 能调用真实模型、保存 artifact，并把分析结果回写 WebApp/OpenClaw。",
        dependencies=[
            configured_env("GBRAIN_LIVE_MODELS_ENABLED", profile=profile, expected="true"),
            openai_deep_model_auth(profile),
            any_configured_env(
                ["MINIMAX_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY"],
                profile=profile,
                dependency_name="minimax_light_model_auth",
            ),
            configured_env("HERMES_ARTIFACT_STORAGE_BACKEND", profile=profile, allowed={"supabase", "file"}),
            configured_env("HERMES_ARTIFACT_BASE_URI", profile=profile),
        ],
        actions=[
            "用生产 KMS/SAE Secret 管理模型 API Key；或在受控 Mac mini/OpenClaw 节点启动本机 Codex auth bridge。",
            "上线前跑一次 Hermes handoff 和 artifact 可读取烟测。",
        ],
    )


def _aliyun_cloud_foundation(profile: str) -> ProductFeature:
    return ProductFeature(
        id="aliyun_cloud_foundation",
        name="阿里云生产基础设施 / 备案",
        description="生产流量部署在阿里云大陆 Region，满足域名、备案、镜像、运行时、数据库、缓存、对象存储与调度依赖。",
        dependencies=[
            configured_env("ALIYUN_REGION", profile=profile),
            configured_env("ALIYUN_ACCOUNT_ID", profile=profile),
            configured_env("ALIYUN_ACR_REGISTRY", profile=profile),
            configured_env("ALIYUN_ACR_NAMESPACE", profile=profile),
            configured_env("ALIYUN_SAE_NAMESPACE_ID", profile=profile),
            configured_env("ALIYUN_SAE_WEBAPP_APP_ID", profile=profile),
            configured_env("ALIYUN_SAE_GATEWAY_APP_ID", profile=profile),
            configured_env("ALIYUN_SAE_DATA_SERVICE_APP_ID", profile=profile),
            configured_env("ALIYUN_RDS_INSTANCE_ID", profile=profile),
            configured_env("ALIYUN_REDIS_INSTANCE_ID", profile=profile),
            configured_env("ALIYUN_OSS_BUCKET_ARTIFACTS", profile=profile),
            configured_env("ALIYUN_OSS_BUCKET_MARKET_DATA", profile=profile),
            configured_env("ALIYUN_EVENTBRIDGE_BUS", profile=profile),
            configured_env("ICP_BEIAN_NUMBER", profile=profile),
        ],
        actions=[
            "用 `python3 scripts/aliyun_preflight.py --profile production --env-file .env.aliyun` 做云资源预检。",
            "完成 ICP 备案和域名解析后再切生产大陆流量。",
        ],
    )


def build_features(*, profile: str) -> list[ProductFeature]:
    return [
        _webapp_registration_auth(profile),
        _registration_onboarding_initialization(profile),
        _tenant_live_data(profile),
        _wechat_claw_binding(profile),
        _futu_user_local_sync(profile),
        _stock_and_option_analysis(profile),
        _ai_analysis(profile),
        _aliyun_cloud_foundation(profile),
    ]


def _count_status(items: Iterable[ProductFeature]) -> dict[str, int]:
    counts = {"pass": 0, "warn": 0, "fail": 0}
    for item in items:
        counts[item.status] += 1
    return counts


def summarize_product_readiness(*, profile: str) -> dict[str, Any]:
    features = build_features(profile=profile)
    counts = _count_status(features)
    return {
        "profile": profile,
        "status": "fail" if counts["fail"] else "pass",
        "counts": counts,
        "features": [feature.to_dict() for feature in features],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check 3.0 product feature dependency readiness.")
    parser.add_argument("--profile", choices=["local", "lightweight", "production"], default="production")
    parser.add_argument("--env-file", default=str(ENV_FILE))
    parser.add_argument("--output", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_env_file(Path(args.env_file))
    summary = summarize_product_readiness(profile=args.profile)
    rendered = json.dumps(summary, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if summary["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
