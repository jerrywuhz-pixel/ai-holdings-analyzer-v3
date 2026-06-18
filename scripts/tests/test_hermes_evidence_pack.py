import json
from pathlib import Path

from scripts.hermes_evidence_pack import build_evidence_pack, classify_pack, EvidenceItem, write_pack


def test_evidence_pack_collects_omx_state_and_logs(tmp_path):
    project = tmp_path
    (project / ".omx" / "state").mkdir(parents=True)
    (project / ".omx" / "logs").mkdir(parents=True)
    (project / ".omx" / "state" / "session.json").write_text('{"session_id":"abc"}', encoding="utf-8")
    (project / ".omx" / "logs" / "turns-2026-06-17.jsonl").write_text(
        "\n".join([json.dumps({"event": "turn", "token": "secret-value"})]),
        encoding="utf-8",
    )

    pack = build_evidence_pack(project_root=project, claim="test claim", run_git_status=False)

    assert pack["schema_version"] == "hermes_evidence_pack_v1"
    assert pack["claim"] == "test claim"
    state_item = pack["sections"]["service_health"][0]
    assert state_item["label"] == "local_omx_state"
    assert state_item["payload"]["session.json"]["session_id"] == "abc"
    logs = pack["sections"]["remaining_risks"][0]["payload"]
    assert "<redacted>" in logs[0]["tail"]


def test_evidence_pack_write_outputs_json_and_markdown(tmp_path):
    pack = build_evidence_pack(project_root=tmp_path, run_git_status=False)

    json_path, md_path = write_pack(pack, output_dir=tmp_path / "evidence")

    assert json_path.exists()
    assert md_path.exists()
    assert "Hermes Evidence Pack" in md_path.read_text(encoding="utf-8")


def test_classify_pack_fails_on_failed_command():
    class Command:
        status = "failed"

    verdict = classify_pack({"service_health": [EvidenceItem("x", "passed", "ok")]}, [Command()])

    assert verdict == "FAIL"
