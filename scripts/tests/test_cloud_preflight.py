import os
from unittest.mock import patch

from scripts.cloud_preflight import ToolProbe, summarize_preflight
from scripts.tests.test_production_readiness import PRODUCTION_ENV


def test_preflight_passes_when_tools_and_env_are_ready():
    probes = [
        ToolProbe("gcloud", "pass", "Google Cloud SDK", True),
        ToolProbe("bun", "pass", "1.3.13", True),
        ToolProbe("node", "pass", "v24", True),
        ToolProbe("docker", "warn", "not installed", False),
        ToolProbe("supabase", "warn", "not installed", False),
        ToolProbe("gcloud_project", "pass", "project=p", True),
        ToolProbe("gcloud_auth", "pass", "active account configured", True),
    ]

    with patch.dict(os.environ, PRODUCTION_ENV, clear=True), patch(
        "scripts.cloud_preflight.run_tool_probes", return_value=probes
    ):
        summary = summarize_preflight(profile="production")

    assert summary["status"] == "pass"
    assert summary["tool_counts"]["fail"] == 0
    assert summary["readiness_counts"]["fail"] == 0


def test_preflight_fails_with_missing_required_tool_and_env():
    probes = [
        ToolProbe("gcloud", "fail", "not installed", True),
        ToolProbe("bun", "pass", "1.3.13", True),
        ToolProbe("node", "pass", "v24", True),
        ToolProbe("docker", "pass", "Docker", False),
        ToolProbe("supabase", "warn", "not installed", False),
        ToolProbe("gcloud_project", "fail", "gcloud is not installed", True),
        ToolProbe("gcloud_auth", "fail", "gcloud is not installed", True),
    ]

    with patch.dict(os.environ, {}, clear=True), patch(
        "scripts.cloud_preflight.run_tool_probes", return_value=probes
    ):
        summary = summarize_preflight(profile="production")

    assert summary["status"] == "fail"
    assert summary["tool_counts"]["fail"] == 3
    assert summary["readiness_counts"]["fail"] > 0
    assert any("Google Cloud CLI" in action for action in summary["next_actions"])
