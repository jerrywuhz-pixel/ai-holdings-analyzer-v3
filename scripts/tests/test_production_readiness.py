import os
from unittest.mock import patch

from scripts.production_readiness import run_checks, summarize


PRODUCTION_ENV = {
    "SUPABASE_URL": "https://example.supabase.co",
    "SUPABASE_ANON_KEY": "anon",
    "SUPABASE_SERVICE_ROLE_KEY": "service",
    "OPENCLAW_DELIVERY_MODE": "webhook",
    "OPENCLAW_DELIVERY_WEBHOOK_URL": "https://claw.example/send",
    "OPENCLAW_DELIVERY_WEBHOOK_SECRET": "secret",
    "GBRAIN_LIVE_MODELS_ENABLED": "true",
    "OPENAI_API_KEY": "openai",
    "MINIMAX_API_KEY": "minimax",
    "HERMES_ARTIFACT_STORAGE_BACKEND": "supabase",
    "HERMES_ARTIFACT_BASE_URI": "supabase://artifacts",
    "HISTORICAL_STORAGE_BACKEND": "supabase_storage",
    "FX_RATES_SOURCE": "trusted_fx",
    "FX_RATE_ENDPOINT": "https://fx.example/latest",
    "SENTRY_DSN": "https://sentry.example/1",
    "CORS_ALLOWED_ORIGINS": "https://app.example.com",
    "WEBAPP_BASE_URL": "https://app.example.com",
}


def test_production_readiness_passes_with_required_config():
    with patch.dict(os.environ, PRODUCTION_ENV, clear=True):
        summary = summarize(run_checks(profile="production"), profile="production")

    assert summary["status"] == "pass"
    assert summary["counts"]["fail"] == 0


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
