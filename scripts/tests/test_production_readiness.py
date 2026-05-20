import os
from unittest.mock import patch

from scripts.production_readiness import run_checks, summarize


PRODUCTION_ENV = {
    "SUPABASE_URL": "https://prod.supabase.co",
    "SUPABASE_ANON_KEY": "anon",
    "SUPABASE_SERVICE_ROLE_KEY": "service",
    "OPENCLAW_DELIVERY_MODE": "webhook",
    "OPENCLAW_DELIVERY_WEBHOOK_URL": "https://claw.ai-holdings.cn/send",
    "OPENCLAW_DELIVERY_WEBHOOK_SECRET": "secret",
    "GBRAIN_LIVE_MODELS_ENABLED": "true",
    "OPENAI_API_KEY": "openai",
    "MINIMAX_API_KEY": "minimax",
    "HERMES_ARTIFACT_STORAGE_BACKEND": "supabase",
    "HERMES_ARTIFACT_BASE_URI": "supabase://artifacts",
    "HISTORICAL_STORAGE_BACKEND": "supabase_storage",
    "FX_RATES_SOURCE": "trusted_fx",
    "FX_RATE_ENDPOINT": "https://fx.ai-holdings.cn/latest",
    "SENTRY_DSN": "https://sentry.ai-holdings.cn/1",
    "CORS_ALLOWED_ORIGINS": "https://app.ai-holdings.cn",
    "WEBAPP_BASE_URL": "https://app.ai-holdings.cn",
}

LIGHTWEIGHT_ENV = {
    "AUTH_MODE": "local",
    "LOCAL_AUTH_ENABLED": "true",
    "OPENCLAW_DELIVERY_MODE": "log",
    "GBRAIN_LIVE_MODELS_ENABLED": "true",
    "MINIMAX_API_KEY": "minimax",
    "HERMES_ARTIFACT_STORAGE_BACKEND": "file",
    "HERMES_ARTIFACT_BASE_URI": "file:///opt/ai-holdings/artifacts",
    "HISTORICAL_STORAGE_BACKEND": "file",
    "FX_RATES_SOURCE": "fallback_estimate",
    "CORS_ALLOWED_ORIGINS": "http://149.129.240.111:3000",
    "WEBAPP_BASE_URL": "http://149.129.240.111:3000",
}


def test_production_readiness_passes_with_required_config():
    with patch.dict(os.environ, PRODUCTION_ENV, clear=True):
        summary = summarize(run_checks(profile="production"), profile="production")

    assert summary["status"] == "pass"
    assert summary["counts"]["fail"] == 0


def test_production_readiness_accepts_system_codex_bridge_for_deep_model():
    env = dict(PRODUCTION_ENV)
    env.pop("OPENAI_API_KEY")
    env["MODEL_AUTH_MODE"] = "openai_codex"
    env["HERMES_DEEP_PROVIDER"] = "openai-codex"
    env["OPENAI_CODEX_AUTH_PROFILE"] = "system-pro"
    env["OPENAI_CODEX_BRIDGE_BASE_URL"] = "http://mac-mini:8091/v1"

    with patch.dict(os.environ, env, clear=True):
        summary = summarize(run_checks(profile="production"), profile="production")

    assert summary["status"] == "pass"
    assert summary["counts"]["fail"] == 0


def test_lightweight_profile_passes_with_local_auth_minimax_and_log_delivery():
    with patch.dict(os.environ, LIGHTWEIGHT_ENV, clear=True):
        summary = summarize(run_checks(profile="lightweight"), profile="lightweight")

    assert summary["status"] == "pass"
    assert summary["counts"]["fail"] == 0
    warned = {check["name"] for check in summary["checks"] if check["status"] == "warn"}
    assert "supabase_core" in warned
    assert "openclaw_webhook_delivery" in warned
    assert "live_model_provider" in warned
    assert "fx_rates" in warned


def test_lightweight_profile_fails_without_minimax_light_model():
    env = dict(LIGHTWEIGHT_ENV)
    env.pop("MINIMAX_API_KEY")

    with patch.dict(os.environ, env, clear=True):
        summary = summarize(run_checks(profile="lightweight"), profile="lightweight")

    assert summary["status"] == "fail"
    failed = {check["name"] for check in summary["checks"] if check["status"] == "fail"}
    assert "live_model_provider" in failed


def test_production_readiness_fails_without_live_delivery_and_fx():
    env = dict(PRODUCTION_ENV)
    env["OPENCLAW_DELIVERY_MODE"] = "log"
    env.pop("FX_RATE_ENDPOINT")
    env.pop("FX_RATES_JSON", None)

    with patch.dict(os.environ, env, clear=True):
        summary = summarize(run_checks(profile="production"), profile="production")

    assert summary["status"] == "fail"
    failed = {check["name"] for check in summary["checks"] if check["status"] == "fail"}
    assert "OPENCLAW_DELIVERY_MODE" in failed
    assert "fx_rates" in failed


def test_local_profile_warns_instead_of_failing_for_missing_production_hooks():
    with patch.dict(os.environ, {"CORS_ALLOWED_ORIGINS": "http://localhost:3000"}, clear=True):
        summary = summarize(run_checks(profile="local"), profile="local")

    assert summary["status"] == "pass"
    assert summary["counts"]["fail"] == 0
    assert summary["counts"]["warn"] > 0


def test_production_readiness_treats_example_domains_as_missing():
    env = dict(PRODUCTION_ENV)
    env["WEBAPP_BASE_URL"] = "https://app.example.cn"
    env["CORS_ALLOWED_ORIGINS"] = "https://app.example.cn"

    with patch.dict(os.environ, env, clear=True):
        summary = summarize(run_checks(profile="production"), profile="production")

    failed = {check["name"] for check in summary["checks"] if check["status"] == "fail"}
    assert "public_origins" in failed
