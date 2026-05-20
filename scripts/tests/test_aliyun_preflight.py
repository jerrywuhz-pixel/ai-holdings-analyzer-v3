import os
from unittest.mock import patch

from scripts.tests.test_production_readiness import PRODUCTION_ENV


ALIYUN_ENV = {
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


def test_aliyun_preflight_passes_when_tools_and_env_are_ready():
    from scripts.aliyun_preflight import ToolProbe, summarize_preflight

    probes = [
        ToolProbe("aliyun", "pass", "aliyun version 3.3.14", True),
        ToolProbe("aliyun_auth", "pass", "configured profile detected", True),
        ToolProbe("bun", "pass", "1.3.13", True),
        ToolProbe("node", "pass", "v24", True),
        ToolProbe("docker", "pass", "Docker", True),
        ToolProbe("supabase", "warn", "not installed", False),
    ]

    env = dict(PRODUCTION_ENV)
    env.update(ALIYUN_ENV)
    with patch.dict(os.environ, env, clear=True), patch(
        "scripts.aliyun_preflight.run_tool_probes", return_value=probes
    ):
        summary = summarize_preflight(profile="production")

    assert summary["status"] == "pass"
    assert summary["cloud_provider"] == "aliyun"
    assert summary["tool_counts"]["fail"] == 0
    assert summary["aliyun_counts"]["fail"] == 0
    assert summary["readiness_counts"]["fail"] == 0


def test_aliyun_preflight_fails_with_missing_cli_and_cloud_env():
    from scripts.aliyun_preflight import ToolProbe, summarize_preflight

    probes = [
        ToolProbe("aliyun", "fail", "not installed", True),
        ToolProbe("aliyun_auth", "fail", "aliyun CLI is not installed", True),
        ToolProbe("bun", "pass", "1.3.13", True),
        ToolProbe("node", "pass", "v24", True),
        ToolProbe("docker", "pass", "Docker", True),
        ToolProbe("supabase", "warn", "not installed", False),
    ]

    with patch.dict(os.environ, {}, clear=True), patch(
        "scripts.aliyun_preflight.run_tool_probes", return_value=probes
    ):
        summary = summarize_preflight(profile="production")

    assert summary["status"] == "fail"
    assert summary["tool_counts"]["fail"] == 2
    assert summary["aliyun_counts"]["fail"] > 0
    assert any("Alibaba Cloud CLI" in action for action in summary["next_actions"])
    assert any("ALIYUN_REGION" in action for action in summary["next_actions"])
