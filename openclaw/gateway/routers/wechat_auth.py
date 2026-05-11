"""
OpenClaw Gateway — 微信小程序认证路由

处理微信小程序的登录认证流程：
- wx.login code → 微信 openid → Supabase user + session
- Token 刷新
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional

import httpx
from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# 微信小程序配置
WECHAT_APP_ID = os.getenv("WECHAT_APP_ID", "")
WECHAT_APP_SECRET = os.getenv("WECHAT_APP_SECRET", "")
WECHAT_JSCODE2SESSION_URL = "https://api.weixin.qq.com/sns/jscode2session"


async def _exchange_code_for_openid(code: str) -> dict[str, Any]:
    """用 wx.login 的 code 换取 openid 和 session_key"""
    params = {
        "appid": WECHAT_APP_ID,
        "secret": WECHAT_APP_SECRET,
        "js_code": code,
        "grant_type": "authorization_code",
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(WECHAT_JSCODE2SESSION_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

    if "errcode" in data and data["errcode"] != 0:
        raise HTTPException(
            status_code=400,
            detail=f"WeChat API error: {data.get('errmsg', 'unknown')}",
        )

    return {
        "openid": data["openid"],
        "session_key": data.get("session_key", ""),
        "unionid": data.get("unionid", ""),
    }


def _generate_tokens(tenant_id: str, supabase_client) -> dict[str, str]:
    """生成 access_token 和 refresh_token"""
    # 使用 Supabase auth 签发 JWT
    try:
        result = supabase_client.auth.admin.generate_link(
            type="magiclink",
            email=f"wx_{tenant_id[:8]}@openclaw.internal",
        )
        # 从生成的链接中提取 token 信息
        # 实际生产中应使用 Supabase auth.admin.issue_token 或自定义 JWT
    except Exception:
        pass

    # 简化实现：使用 Supabase service_role 直接创建会话
    import jwt as pyjwt

    jwt_secret = os.getenv("SUPABASE_JWT_SECRET", "")
    if not jwt_secret:
        # 开发环境回退
        jwt_secret = "dev-secret-change-in-production"

    now = int(time.time())
    access_payload = {
        "sub": tenant_id,
        "role": "authenticated",
        "tenant_id": tenant_id,
        "iat": now,
        "exp": now + 3600,  # 1 小时
    }
    refresh_payload = {
        "sub": tenant_id,
        "type": "refresh",
        "tenant_id": tenant_id,
        "iat": now,
        "exp": now + 86400 * 30,  # 30 天
    }

    access_token = pyjwt.encode(access_payload, jwt_secret, algorithm="HS256")
    refresh_token = pyjwt.encode(refresh_payload, jwt_secret, algorithm="HS256")

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_in": 3600,
    }


def _verify_refresh_token(refresh_token: str) -> Optional[str]:
    """验证 refresh_token 并返回 tenant_id"""
    import jwt as pyjwt

    jwt_secret = os.getenv("SUPABASE_JWT_SECRET", "dev-secret-change-in-production")
    try:
        payload = pyjwt.decode(refresh_token, jwt_secret, algorithms=["HS256"])
        if payload.get("type") != "refresh":
            return None
        return payload.get("sub") or payload.get("tenant_id")
    except Exception:
        return None


@router.post("/wechat/login")
async def wechat_login(request: Request) -> dict[str, Any]:
    """
    微信小程序登录端点。

    流程：
    1. 用 code 换取 openid
    2. 查找或创建 Supabase user
    3. 生成 JWT token
    4. 创建 gbrain source（触发器自动完成）
    """
    body = await request.json()
    code = body.get("code", "")
    profile = body.get("profile", {})

    if not code:
        raise HTTPException(status_code=400, detail="Missing wx.login code")
    if not WECHAT_APP_ID or not WECHAT_APP_SECRET:
        raise HTTPException(
            status_code=500,
            detail="WECHAT_APP_ID or WECHAT_APP_SECRET not configured",
        )

    # 1. code → openid
    try:
        wx_result = await _exchange_code_for_openid(code)
    except httpx.HTTPError as exc:
        logger.error("[WeChatAuth] code2session failed: %s", exc)
        raise HTTPException(status_code=502, detail="WeChat API call failed")

    openid = wx_result["openid"]
    session_key = wx_result["session_key"]
    unionid = wx_result.get("unionid", "")

    # 2. 查找或创建用户
    supabase = request.app.state.supabase

    user_resp = (
        supabase.table("users")
        .select("*")
        .eq("wechat_openid", openid)
        .limit(1)
        .execute()
    )

    if user_resp.data:
        user = user_resp.data[0]
        tenant_id = user["id"]

        # 更新用户资料
        update_data: dict[str, Any] = {}
        if profile.get("nickName") and profile["nickName"] != user.get("nickname"):
            update_data["nickname"] = profile["nickName"]
        if profile.get("avatarUrl") and profile["avatarUrl"] != user.get("avatar_url"):
            update_data["avatar_url"] = profile["avatarUrl"]

        if update_data:
            supabase.table("users").update(update_data).eq("id", tenant_id).execute()
    else:
        # 创建新用户
        insert_data = {
            "wechat_openid": openid,
            "nickname": profile.get("nickName", "微信用户"),
            "avatar_url": profile.get("avatarUrl", ""),
        }
        if unionid:
            insert_data["wechat_unionid"] = unionid

        create_resp = supabase.table("users").insert(insert_data).execute()
        user = create_resp.data[0] if create_resp.data else {}
        tenant_id = user["id"]
        logger.info("[WeChatAuth] New user created: %s", tenant_id)

    # 3. 保存微信认证信息
    supabase.table("weixin_auth_providers").upsert(
        {
            "user_id": tenant_id,
            "openid": openid,
            "unionid": unionid or None,
            "session_key": session_key,
            "appid": WECHAT_APP_ID,
        },
        on_conflict="openid,appid",
    ).execute()

    # 4. 生成 JWT token
    tokens = _generate_tokens(tenant_id, supabase)

    # 5. 记录会话
    supabase.table("miniprogram_sessions").insert(
        {
            "tenant_id": tenant_id,
            "access_token": tokens["access_token"],
            "refresh_token": tokens["refresh_token"],
            "expires_at": f"now() + interval '{tokens['expires_in']} seconds'",
        }
    ).execute()

    return {
        "session": {
            "openid": openid,
            "tenant_id": tenant_id,
            "nickname": profile.get("nickName", user.get("nickname", "微信用户")),
            "avatar_url": profile.get("avatarUrl", user.get("avatar_url", "")),
        },
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "expires_in": tokens["expires_in"],
        "mode": "gateway",
    }


@router.post("/refresh")
async def refresh_token(request: Request) -> dict[str, Any]:
    """刷新 access_token"""
    body = await request.json()
    refresh_tok = body.get("refresh_token", "")

    if not refresh_tok:
        raise HTTPException(status_code=400, detail="Missing refresh_token")

    tenant_id = _verify_refresh_token(refresh_tok)
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh_token")

    # 生成新 token
    supabase = request.app.state.supabase
    tokens = _generate_tokens(tenant_id, supabase)

    # 更新会话
    supabase.table("miniprogram_sessions").insert(
        {
            "tenant_id": tenant_id,
            "access_token": tokens["access_token"],
            "refresh_token": tokens["refresh_token"],
            "expires_at": f"now() + interval '{tokens['expires_in']} seconds'",
        }
    ).execute()

    return tokens
