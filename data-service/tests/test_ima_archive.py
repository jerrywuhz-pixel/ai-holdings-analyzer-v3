from __future__ import annotations

import pytest

from services.hermes.ima_archive import HermesImaArchiveService


@pytest.mark.asyncio
async def test_ima_archive_writes_daily_markdown_and_redacts(tmp_path):
    service = HermesImaArchiveService(
        archive_root=tmp_path,
        skill_dir=tmp_path / "missing-skill",
        knowledge_base_id="kb-test",
        enabled=True,
        upload_enabled=False,
    )

    result = await service.archive(
        source="wechat_user_reply",
        title="stock_analysis NVDA",
        content_markdown="NVDA 当前结论：观察。",
        payload={"reply_text": "NVDA 当前结论：观察。", "api_key": "secret-value"},
        tenant_id="tenant-1",
        prompt="分析 NVDA",
        result_type="stock_analysis",
    )

    assert result["status"] == "saved"
    assert result["ima"] == {"status": "skipped", "reason": "ima_upload_disabled"}
    path = tmp_path / result["date"] / result["filename"]
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "NVDA 当前结论：观察。" in content
    assert "分析 NVDA" in content
    assert "secret-value" not in content
    assert "<redacted>" in content
