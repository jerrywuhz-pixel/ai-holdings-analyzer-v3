import os
from unittest.mock import patch


PRODUCT_ENV = {
    "NEXT_PUBLIC_SUPABASE_URL": "https://prod.supabase.co",
    "NEXT_PUBLIC_SUPABASE_ANON_KEY": "anon",
    "SUPABASE_URL": "https://prod.supabase.co",
    "SUPABASE_ANON_KEY": "anon",
    "SUPABASE_SERVICE_ROLE_KEY": "service",
    "SUPABASE_JWT_SECRET": "jwt-secret",
    "WEBAPP_BASE_URL": "https://app.ai-holdings.cn",
    "NEXT_PUBLIC_DATA_SERVICE_URL": "https://api.ai-holdings.cn",
    "DATA_SERVICE_URL": "https://api.ai-holdings.cn",
    "WECHAT_APP_ID": "wx-app",
    "WECHAT_APP_SECRET": "wx-secret",
    "WECHAT_CLAWBOT_API_BASE_URL": "https://ilinkai.weixin.qq.com",
    "ONBOARDING_CREDENTIAL_ENCRYPTION_KEY": "0123456789abcdef0123456789abcdef",
    "OPENCLAW_DELIVERY_MODE": "webhook",
    "OPENCLAW_DELIVERY_WEBHOOK_URL": "https://api.ai-holdings.cn/openclaw/delivery",
    "OPENCLAW_DELIVERY_WEBHOOK_SECRET": "delivery-secret",
    "OPENCLAW_SKILL_KEY": "skill-key",
    "OPENCLAW_CRON_SECRET": "cron-secret",
    "FUTU_CONNECTOR_MODE": "user_local_polling",
    "FUTU_CONNECTOR_READ_ONLY": "true",
    "FUTU_CONNECTOR_POLL_ENDPOINT": "https://api.ai-holdings.cn/connectors/poll",
    "FUTU_CONNECTOR_UPLOAD_ENDPOINT": "https://api.ai-holdings.cn/connectors/upload",
    "FUTU_CONNECTOR_PAIRING_TOKEN": "pairing-token",
    "DATA_SERVICE_INTERNAL_TOKEN": "data-service-token",
    "TUSHARE_TOKEN": "tushare",
    "GBRAIN_LIVE_MODELS_ENABLED": "true",
    "OPENAI_API_KEY": "openai",
    "MINIMAX_API_KEY": "minimax",
    "HERMES_ARTIFACT_STORAGE_BACKEND": "supabase",
    "HERMES_ARTIFACT_BASE_URI": "supabase://artifacts",
    "FX_RATES_SOURCE": "trusted_http_fx",
    "FX_RATE_ENDPOINT": "https://fx.ai-holdings.cn/latest",
    "ALIYUN_REGION": "cn-shanghai",
    "ALIYUN_ACCOUNT_ID": "1234567890123456",
    "ALIYUN_ACR_REGISTRY": "registry.cn-shanghai.aliyuncs.com",
    "ALIYUN_ACR_NAMESPACE": "ai-holdings",
    "ALIYUN_SAE_NAMESPACE_ID": "cn-shanghai:production",
    "ALIYUN_SAE_WEBAPP_APP_ID": "webapp-id",
    "ALIYUN_SAE_GATEWAY_APP_ID": "gateway-id",
    "ALIYUN_SAE_DATA_SERVICE_APP_ID": "data-service-id",
    "ALIYUN_RDS_INSTANCE_ID": "pgm-prod001",
    "ALIYUN_REDIS_INSTANCE_ID": "r-prod001",
    "ALIYUN_OSS_BUCKET_ARTIFACTS": "ai-holdings-artifacts",
    "ALIYUN_OSS_BUCKET_MARKET_DATA": "ai-holdings-market-data",
    "ALIYUN_EVENTBRIDGE_BUS": "ai-holdings",
    "ICP_BEIAN_NUMBER": "沪ICP备00000000号-1",
}


LIGHTWEIGHT_ENV = {
    **PRODUCT_ENV,
    "NEXT_PUBLIC_SUPABASE_URL": "",
    "NEXT_PUBLIC_SUPABASE_ANON_KEY": "",
    "SUPABASE_URL": "",
    "SUPABASE_ANON_KEY": "",
    "SUPABASE_SERVICE_ROLE_KEY": "",
    "SUPABASE_JWT_SECRET": "",
    "AUTH_MODE": "local",
    "LOCAL_AUTH_ENABLED": "true",
    "LOCAL_AUTH_REGISTRATION_ENABLED": "true",
    "DATABASE_URL": "postgresql://app:password@postgres:5432/ai_holdings",
    "WEBAPP_DATABASE_URL": "",
    "AUTH_SESSION_SECRET": "local-session-secret",
    "SMTP_HOST": "smtp.mailprovider.cn",
    "SMTP_FROM": "no-reply@ai-holdings.cn",
}


def _feature(summary, feature_id):
    return next(feature for feature in summary["features"] if feature["id"] == feature_id)


def _dependency(feature, dependency_name):
    return next(dep for dep in feature["dependencies"] if dep["name"] == dependency_name)


def test_webapp_registration_feature_passes_when_signup_and_supabase_env_are_ready():
    from scripts.product_feature_readiness import summarize_product_readiness

    with patch.dict(os.environ, PRODUCT_ENV, clear=True):
        summary = summarize_product_readiness(profile="production")

    feature = _feature(summary, "webapp_registration_auth")
    assert feature["status"] == "pass"
    assert _dependency(feature, "webapp_signup_ui")["status"] == "pass"
    assert _dependency(feature, "tenant_bootstrap_triggers")["status"] == "pass"


def test_lightweight_registration_feature_passes_with_local_auth_and_smtp():
    from scripts.product_feature_readiness import summarize_product_readiness

    with patch.dict(os.environ, LIGHTWEIGHT_ENV, clear=True):
        summary = summarize_product_readiness(profile="lightweight")

    feature = _feature(summary, "webapp_registration_auth")
    assert feature["status"] == "pass"
    assert _dependency(feature, "local_auth_mode")["status"] == "pass"
    assert _dependency(feature, "local_auth_database_url")["status"] == "pass"
    assert _dependency(feature, "smtp_verification_delivery")["status"] == "pass"


def test_lightweight_registration_feature_fails_without_local_auth_database():
    from scripts.product_feature_readiness import summarize_product_readiness

    env = {
        **LIGHTWEIGHT_ENV,
        "DATABASE_URL": "",
        "WEBAPP_DATABASE_URL": "",
    }

    with patch.dict(os.environ, env, clear=True):
        summary = summarize_product_readiness(profile="lightweight")

    feature = _feature(summary, "webapp_registration_auth")
    assert feature["status"] == "fail"
    assert _dependency(feature, "local_auth_database_url")["status"] == "fail"


def test_lightweight_registration_feature_accepts_compose_postgres_env():
    from scripts.product_feature_readiness import summarize_product_readiness

    env = {
        **LIGHTWEIGHT_ENV,
        "DATABASE_URL": "",
        "WEBAPP_DATABASE_URL": "",
        "POSTGRES_USER": "postgres",
        "POSTGRES_PASSWORD": "strong-postgres-password",
        "POSTGRES_DB": "ai_holdings",
    }

    with patch.dict(os.environ, env, clear=True):
        summary = summarize_product_readiness(profile="lightweight")

    feature = _feature(summary, "webapp_registration_auth")
    assert feature["status"] == "pass"
    assert _dependency(feature, "local_auth_database_url")["status"] == "pass"


def test_registration_onboarding_feature_passes_when_initialization_flow_exists():
    from scripts.product_feature_readiness import summarize_product_readiness

    with patch.dict(os.environ, PRODUCT_ENV, clear=True):
        summary = summarize_product_readiness(profile="production")

    feature = _feature(summary, "registration_onboarding_initialization")
    assert feature["status"] == "pass"
    assert _dependency(feature, "onboarding_schema")["status"] == "pass"
    assert _dependency(feature, "register_redirects_to_onboarding")["status"] == "pass"
    assert _dependency(feature, "wechat_clawbot_onboarding")["status"] == "pass"
    assert _dependency(feature, "futu_pairing_onboarding")["status"] == "pass"
    assert _dependency(feature, "onboarding_review_gate")["status"] == "pass"


def test_registration_onboarding_accepts_welcome_entrypoint(monkeypatch):
    import scripts.product_feature_readiness as readiness

    original_read = readiness._read_repo_file

    def read_repo_file(relative_path: str) -> str:
        if relative_path == "webapp/src/app/login/LoginForm.tsx":
            return "router.push('/onboarding/welcome')"
        return original_read(relative_path)

    monkeypatch.setattr(readiness, "_read_repo_file", read_repo_file)
    with patch.dict(os.environ, PRODUCT_ENV, clear=True):
        summary = readiness.summarize_product_readiness(profile="production")

    feature = _feature(summary, "registration_onboarding_initialization")
    assert _dependency(feature, "register_redirects_to_onboarding")["status"] == "pass"


def test_futu_user_local_sync_feature_passes_when_control_plane_and_env_are_ready():
    from scripts.product_feature_readiness import summarize_product_readiness

    with patch.dict(os.environ, PRODUCT_ENV, clear=True):
        summary = summarize_product_readiness(profile="production")

    feature = _feature(summary, "futu_user_local_sync")
    assert feature["status"] == "pass"
    assert _dependency(feature, "cloud_connector_poll_upload")["status"] == "pass"


def test_futu_user_local_sync_rejects_relative_control_plane_urls():
    from scripts.product_feature_readiness import summarize_product_readiness

    env = {
        **PRODUCT_ENV,
        "FUTU_CONNECTOR_POLL_ENDPOINT": "/broker/futu/poll",
        "FUTU_CONNECTOR_UPLOAD_ENDPOINT": "/broker/futu/upload",
    }

    with patch.dict(os.environ, env, clear=True):
        summary = summarize_product_readiness(profile="lightweight")

    feature = _feature(summary, "futu_user_local_sync")
    assert feature["status"] == "fail"
    assert _dependency(feature, "FUTU_CONNECTOR_POLL_ENDPOINT")["status"] == "fail"
    assert _dependency(feature, "FUTU_CONNECTOR_UPLOAD_ENDPOINT")["status"] == "fail"


def test_wechat_claw_binding_feature_passes_when_env_and_binding_ui_are_ready():
    from scripts.product_feature_readiness import summarize_product_readiness

    with patch.dict(os.environ, PRODUCT_ENV, clear=True):
        summary = summarize_product_readiness(profile="production")

    feature = _feature(summary, "wechat_claw_binding")
    assert feature["status"] == "pass"
    assert _dependency(feature, "webapp_self_service_binding")["status"] == "pass"


def test_wechat_claw_binding_lightweight_uses_clawbot_qr_without_wechat_app_secret():
    from scripts.product_feature_readiness import summarize_product_readiness

    env = {
        **LIGHTWEIGHT_ENV,
        "WECHAT_APP_ID": "",
        "WECHAT_APP_SECRET": "",
        "WECHAT_CLAWBOT_API_BASE_URL": "https://ilinkai.weixin.qq.com",
        "OPENCLAW_DELIVERY_MODE": "log",
        "OPENCLAW_DELIVERY_WEBHOOK_URL": "",
        "OPENCLAW_DELIVERY_WEBHOOK_SECRET": "",
        "OPENCLAW_CRON_SECRET": "",
    }

    with patch.dict(os.environ, env, clear=True):
        summary = summarize_product_readiness(profile="lightweight")

    feature = _feature(summary, "wechat_claw_binding")
    assert feature["status"] == "pass"
    assert _dependency(feature, "wechat_clawbot_api")["status"] == "pass"
    assert _dependency(feature, "openclaw_delivery_mode")["status"] == "pass"


def test_tenant_live_data_feature_passes_when_webapp_fetch_is_tenant_scoped():
    from scripts.product_feature_readiness import summarize_product_readiness

    with patch.dict(os.environ, PRODUCT_ENV, clear=True):
        summary = summarize_product_readiness(profile="production")

    feature = _feature(summary, "tenant_live_data_webapp")
    assert feature["status"] == "pass"
    assert _dependency(feature, "tenant_scoped_fetch")["status"] == "pass"


def test_stock_option_analysis_includes_ftshare_market_data_skill():
    from scripts.product_feature_readiness import summarize_product_readiness

    with patch.dict(os.environ, PRODUCT_ENV, clear=True):
        summary = summarize_product_readiness(profile="production")

    feature = _feature(summary, "stock_option_query_analysis")
    assert _dependency(feature, "ftshare_market_data_adapter")["status"] == "pass"
    assert _dependency(feature, "ftshare_market_data_skill")["status"] == "pass"


def test_ai_analysis_accepts_system_codex_bridge_without_openai_api_key():
    from scripts.product_feature_readiness import summarize_product_readiness

    env = {
        **PRODUCT_ENV,
        "OPENAI_API_KEY": "",
        "MODEL_AUTH_MODE": "openai_codex",
        "HERMES_DEEP_PROVIDER": "openai-codex",
        "HERMES_DEEP_MODEL": "gpt-5.5",
        "OPENAI_CODEX_AUTH_PROFILE": "system-pro",
        "OPENAI_CODEX_BRIDGE_BASE_URL": "http://127.0.0.1:8091/v1",
    }

    with patch.dict(os.environ, env, clear=True):
        summary = summarize_product_readiness(profile="production")

    feature = _feature(summary, "ai_research_analysis")
    assert feature["status"] == "pass"
    assert _dependency(feature, "openai_deep_model_auth")["status"] == "pass"


def test_lightweight_aliyun_foundation_uses_swas_not_sae_stack():
    from scripts.product_feature_readiness import summarize_product_readiness

    env = {
        **LIGHTWEIGHT_ENV,
        "ALIYUN_REGION": "ap-southeast-5",
        "ALIYUN_SWAS_INSTANCE_ID": "swas-instance-id",
        "ALIYUN_DOMAIN_NAME": "11office.top",
        "ALIYUN_SSL_CERTIFICATE_ID": "cert-id",
        "POSTGRES_HOST": "127.0.0.1",
        "REDIS_HOST": "127.0.0.1",
        "MINIO_HOST": "127.0.0.1",
        "ICP_BEIAN_NUMBER": "",
        "ALIYUN_ACCOUNT_ID": "",
        "ALIYUN_ACR_REGISTRY": "",
        "ALIYUN_SAE_NAMESPACE_ID": "",
    }

    with patch.dict(os.environ, env, clear=True):
        summary = summarize_product_readiness(profile="lightweight")

    feature = _feature(summary, "aliyun_cloud_foundation")
    assert feature["status"] == "pass"
    assert _dependency(feature, "ALIYUN_SWAS_INSTANCE_ID")["status"] == "pass"
    assert _dependency(feature, "ICP_BEIAN_NUMBER")["status"] == "pass"


def test_lightweight_mainland_aliyun_requires_icp():
    from scripts.product_feature_readiness import summarize_product_readiness

    env = {
        **LIGHTWEIGHT_ENV,
        "ALIYUN_REGION": "cn-shanghai",
        "ALIYUN_SWAS_INSTANCE_ID": "swas-instance-id",
        "ALIYUN_DOMAIN_NAME": "11office.top",
        "ALIYUN_SSL_CERTIFICATE_ID": "cert-id",
        "POSTGRES_HOST": "127.0.0.1",
        "REDIS_HOST": "127.0.0.1",
        "MINIO_HOST": "127.0.0.1",
        "ICP_BEIAN_NUMBER": "",
    }

    with patch.dict(os.environ, env, clear=True):
        summary = summarize_product_readiness(profile="lightweight")

    feature = _feature(summary, "aliyun_cloud_foundation")
    assert feature["status"] == "fail"
    assert _dependency(feature, "ICP_BEIAN_NUMBER")["status"] == "fail"


def test_placeholder_values_are_treated_as_missing_in_production():
    from scripts.product_feature_readiness import configured_env

    with patch.dict(os.environ, {"SUPABASE_URL": "https://your-project.supabase.co"}, clear=True):
        result = configured_env("SUPABASE_URL", profile="production")

    assert result.status == "fail"
    assert "placeholder" in result.detail


def test_example_domains_are_treated_as_placeholders_in_production():
    from scripts.product_feature_readiness import configured_env

    with patch.dict(os.environ, {"DATA_SERVICE_URL": "https://api.example.cn"}, clear=True):
        result = configured_env("DATA_SERVICE_URL", profile="production")

    assert result.status == "fail"
    assert "placeholder" in result.detail
