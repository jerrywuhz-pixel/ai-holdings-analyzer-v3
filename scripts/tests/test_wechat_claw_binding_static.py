from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_clawbot_qr_start_matches_tencent_openclaw_weixin_protocol():
    source = read("webapp/src/lib/clawbot.ts")

    assert "method: 'POST'" in source
    assert "get_bot_qrcode" in source
    assert "local_token_list" in source
    assert "qrcode_img_content" in source


def test_wechat_onboarding_uses_modal_api_flow():
    page = read("webapp/src/app/onboarding/wechat/page.tsx")
    component = read("webapp/src/components/wechat-binding-panel.tsx")

    assert "WechatBindingPanel" in page
    assert "扫码登录" in component
    assert "/api/onboarding/wechat/binding" in component
    assert "重新生成" in component


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
