from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_clawbot_qr_start_matches_tencent_openclaw_weixin_protocol():
    source = read("webapp/src/lib/clawbot.ts")

    assert "DEFAULT_ILINK_APP_ID = 'bot'" in source
    assert "DEFAULT_ILINK_CLIENT_VERSION = '132099'" in source
    assert "DEFAULT_CHANNEL_VERSION = '2.4.3'" in source
    assert "DEFAULT_BOT_AGENT = 'OpenClaw'" in source
    assert "method: 'POST'" in source
    assert "get_bot_qrcode" in source
    assert "local_token_list" in source
    assert "qrcode_img_content" in source
    assert "localTokenList.slice(0, 10)" in source


def test_clawbot_qr_status_handles_redirect_and_pair_code_flow():
    clawbot = read("webapp/src/lib/clawbot.ts")
    binding = read("webapp/src/lib/wechat-binding.ts")
    route = read("webapp/src/app/api/onboarding/wechat/binding/route.ts")
    component = read("webapp/src/components/wechat-binding-panel.tsx")

    assert "redirect_host" in clawbot
    assert "redirectHost" in clawbot
    assert "verify_code" in clawbot
    status_block = clawbot.split("export async function requestClawbotQrStatus", 1)[1].split(
        "export async function requestClawbotUpdates",
        1,
    )[0]
    assert "headers: clawbotCommonHeaders()" in status_block
    assert "clawbotHeaders()" not in status_block
    assert "requestClawbotQrStatus(authSession.qrcode, {" in binding
    assert "baseUrl: authSession.base_url" in binding
    assert "status.redirectHost" in binding
    assert "need_verifycode" in binding
    assert "verifyCode" in route
    assert "pairCode" in component
    assert "请输入手机微信显示的数字验证码" in component


def test_bind_redirect_requires_existing_clawbot_credential():
    binding = read("webapp/src/lib/wechat-binding.ts")

    assert "const credential = await latestAuthorizedCredential(user.id)" in binding
    assert "status.alreadyConnected && credential" in binding


def test_wechat_onboarding_uses_modal_api_flow():
    page = read("webapp/src/app/onboarding/wechat/page.tsx")
    component = read("webapp/src/components/wechat-binding-panel.tsx")

    assert "WechatBindingPanel" in page
    assert "扫码登录" in component
    assert "/api/onboarding/wechat/binding" in component
    assert "重新生成" in component
    assert "window.setTimeout(poll" in component
    assert "setInterval" not in component


def test_onboarding_state_does_not_require_supabase_admin_client():
    source = read("webapp/src/lib/onboarding.ts")

    assert "postgres" in source
    assert "createAdminClient" not in source
    assert "ensureOnboardingSchema" in source


def test_openclaw_delivery_webhook_sends_via_tencent_ilink_sendmessage():
    route = read("webapp/src/app/api/openclaw/delivery/wechat/route.ts")
    clawbot = read("webapp/src/lib/clawbot.ts")
    compose = read("docker-compose.server.yml")

    assert "x-openclaw-delivery-signature" in route
    assert "OPENCLAW_DELIVERY_WEBHOOK_SECRET" in route
    assert "wechat_bot_credentials" in route
    assert "channel_bindings" in route
    assert "decryptCredential" in route
    assert "sendClawbotTextMessage" in route
    assert "sendmessage" in clawbot
    assert "base_info: clawbotBaseInfo()" in clawbot
    assert "context_token" in clawbot
    assert "to_user_id" in clawbot
    assert "openclaw-outbox-worker" in compose
    assert "openclaw.gateway.outbox_worker" in compose
    assert "openclaw-post-confirmation-worker" in compose


def test_openclaw_delivery_webhook_is_not_blocked_by_login_middleware():
    middleware = read("webapp/src/middleware.ts")

    assert "'/api/openclaw/delivery'" in middleware


def test_openclaw_workers_do_not_inherit_http_gateway_healthcheck():
    compose = read("docker-compose.server.yml")

    assert "openclaw-outbox-worker:" in compose
    assert "openclaw-post-confirmation-worker:" in compose
    assert "os.kill(1, 0)" in compose
