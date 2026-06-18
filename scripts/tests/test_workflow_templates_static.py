from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_workflow_templates_define_required_entry_points():
    content = (ROOT / "docs" / "hermes" / "workflow-templates.md").read_text(encoding="utf-8")

    assert "Entry Template: New Feature" in content
    assert "Entry Template: Cloud Operations" in content
    assert "Entry Template: Verification Closure" in content
    assert "Entry Template: Product/Docs Sync" in content


def test_workflow_templates_include_five_agent_slots_and_evidence_contract():
    content = (ROOT / "docs" / "hermes" / "workflow-templates.md").read_text(encoding="utf-8")

    for slot in ["explore", "ops-runtime", "product-doc", "executor", "verifier"]:
        assert f"`{slot}`" in content
    for layer in ["service health", "route truth", "persistence truth", "delivery truth", "user-surface truth", "remaining risks"]:
        assert layer in content


def test_workflow_templates_reference_new_runbook_tools():
    content = (ROOT / "docs" / "hermes" / "workflow-templates.md").read_text(encoding="utf-8")

    assert "scripts/hermes_evidence_pack.py" in content
    assert "scripts/hermes_wechat_trace_bundle.py" in content
    assert "scripts/hermes_swas_runbook.py" in content
    assert "scripts/hermes_explain_routing.py" in content
