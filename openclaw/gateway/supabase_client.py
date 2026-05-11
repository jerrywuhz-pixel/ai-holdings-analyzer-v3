"""
安全的 Supabase 客户端封装 — Skill 级 API Key 隔离

每个 Skill 分配独立的 Supabase API Key（通常为携带 service_role 声明的
自定义 JWT）。本模块在创建客户端时，通过请求头注入 ``X-Skill-Name``，
使网关层或数据库 Trigger 能够追踪调用来源。
"""
from __future__ import annotations

from typing import Any

def create_skill_client(
    skill_name: str,
    api_key: str,
    supabase_url: str,
) -> Any:
    """
    创建带 Skill 标识的 Supabase 异步客户端。

    请求头中自动附加 ``X-Skill-Name: <skill_name>``，便于：
    - 网关层按 Skill 维度统计调用量
    - 数据库层（通过 Trigger 或扩展）记录调用来源

    Args:
        skill_name: Skill 标识名，如 ``portfolio-analyzer``。
        api_key: 该 Skill 专属的 Supabase API Key（JWT）。
            建议为携带 ``role = 'service_role'`` 声明的自定义 JWT，
            以确保中间件能写入 audit_logs 等受保护资源。
        supabase_url: Supabase Project URL，如
            ``https://<project-ref>.supabase.co``。

    Returns:
        初始化完成的 ``AsyncClient`` 实例。

    Raises:
        ImportError: ``supabase`` 包未安装或版本不兼容。
    """
    try:
        from supabase._async.client import AsyncClient
        try:
            from supabase.lib.client_options import AsyncClientOptions as ClientOptions
        except ImportError:  # pragma: no cover - older supabase-py
            from supabase.lib.client_options import ClientOptions
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "supabase>=2.4.0 is required. "
            "Install with: pip install 'supabase>=2.4.0,<3.0.0'"
        ) from exc

    options = ClientOptions(
        headers={"X-Skill-Name": skill_name},
    )
    return AsyncClient(supabase_url, api_key, options)
