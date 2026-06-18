import base64
import json

from scripts.hermes_swas_runbook import (
    build_runbook_script,
    decode_output,
    extract_invocation_id,
    parse_invocation_result,
    run_runbook,
    summarize_steps,
    RunbookStep,
)


def test_runbook_script_contains_fixed_truth_layers():
    script = build_runbook_script(
        project_dir="/opt/ai-holdings-analyzer-v3",
        env_file=".env.server",
        compose_file="docker-compose.server.yml",
        public_url="https://www.11office.top",
    )

    assert "section 'docker compose'" in script
    assert "section 'routes'" in script
    assert "section 'cron'" in script
    assert "section 'wechat bridge'" in script
    assert "section 'db evidence'" in script
    assert "verify-foundation-runtime.sh" in script
    assert "openclaw service present" in script


def test_dry_run_does_not_require_aliyun_cli():
    summary = run_runbook(
        instance_id="i-123",
        region="ap-southeast-5",
        project_dir="/opt/app",
        env_file=".env.server",
        compose_file="docker-compose.server.yml",
        public_url="https://example.test",
        dry_run=True,
        timeout_seconds=5,
    )

    assert summary["status"] == "partial"
    assert summary["steps"][1]["stage"] == "cloud_assistant"
    assert summary["steps"][1]["status"] == "planned"


def test_missing_instance_id_fails_fast():
    summary = run_runbook(
        instance_id="",
        region="ap-southeast-5",
        project_dir="/opt/app",
        env_file=".env.server",
        compose_file="docker-compose.server.yml",
        public_url="",
        dry_run=True,
        timeout_seconds=5,
    )

    assert summary["status"] == "fail"
    assert summary["steps"][-1]["stage"] == "instance"


def test_invocation_helpers_parse_common_shapes():
    assert extract_invocation_id(json.dumps({"InvocationId": "abc"})) == "abc"
    assert extract_invocation_id(json.dumps({"Data": {"InvocationId": "def"}})) == "def"

    output = "hello"
    encoded = base64.b64encode(output.encode()).decode()
    parsed = parse_invocation_result(json.dumps({"Data": {"Output": encoded, "ExitCode": 0, "Status": "Finished"}}))

    assert parsed["finished"] is True
    assert parsed["output"] == output
    assert parsed["exit_code"] == 0


def test_decode_output_leaves_plain_text_unchanged():
    assert decode_output("not base64 output") == "not base64 output"


def test_summarize_steps_marks_warn_as_partial():
    summary = summarize_steps([RunbookStep("cloud_assistant", "warn", "non-zero")])

    assert summary["status"] == "partial"
