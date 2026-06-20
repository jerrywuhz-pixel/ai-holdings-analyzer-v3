from __future__ import annotations

import pytest

from services.hermes.ima_archive import HermesImaArchiveService, ima_archive_policy


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


def test_ima_archive_policy_uploads_user_and_review_knowledge_events():
    assert ima_archive_policy(source="wechat_user_reply", result_type="market_quote") == {
        "upload": True,
        "reason": "source_wechat_user_reply",
    }
    assert ima_archive_policy(source="wechat_gateway_reply", result_type="gateway_agent_reply") == {
        "upload": True,
        "reason": "source_wechat_gateway_reply",
    }
    assert ima_archive_policy(source="scheduled_task", result_type="p0-us-close-summary") == {
        "upload": True,
        "reason": "result_type_p0-us-close-summary",
    }
    assert ima_archive_policy(source="scheduled_task", result_type="p0-cn-close-summary") == {
        "upload": True,
        "reason": "result_type_p0-cn-close-summary",
    }
    assert ima_archive_policy(source="scheduled_task", result_type="p0-weekly-review") == {
        "upload": True,
        "reason": "result_type_p0-weekly-review",
    }


def test_ima_archive_policy_skips_routine_or_no_change_events():
    assert ima_archive_policy(source="scheduled_task", result_type="p0-delivery-retry") == {
        "upload": False,
        "reason": "routine_result_type_p0-delivery-retry",
    }
    assert ima_archive_policy(source="scheduled_task", result_type="p0-health-heartbeat") == {
        "upload": False,
        "reason": "routine_result_type_p0-health-heartbeat",
    }
    assert ima_archive_policy(source="scheduled_analysis", result_type="alert_center_run", metadata={"cycle": "intraday"}) == {
        "upload": False,
        "reason": "routine_result_type_alert_center_run",
    }
    assert ima_archive_policy(source="scheduled_task", result_type="p0-market-watchlist-refresh", payload={"status": "skipped_no_change"}) == {
        "upload": False,
        "reason": "status_skipped_no_change",
    }


@pytest.mark.asyncio
async def test_ima_archive_policy_saves_but_skips_ima_upload_for_routine_task(tmp_path):
    service = HermesImaArchiveService(
        archive_root=tmp_path,
        skill_dir=tmp_path / "missing-skill",
        knowledge_base_id="kb-test",
        enabled=True,
        upload_enabled=True,
    )

    result = await service.archive(
        source="scheduled_task",
        title="Hermes 定时任务 - p0-delivery-retry",
        content_markdown="delivery retry ok",
        payload={"status": "ok", "result_type": "p0-delivery-retry"},
        result_type="p0-delivery-retry",
    )

    assert result["status"] == "saved"
    assert result["ima"] == {"status": "skipped", "reason": "routine_result_type_p0-delivery-retry"}
    assert result["ima_sync_policy"] == {"upload": False, "reason": "routine_result_type_p0-delivery-retry"}
    assert (tmp_path / result["date"] / result["filename"]).exists()


@pytest.mark.asyncio
async def test_ima_archive_backs_up_knowledge_events_to_github(monkeypatch, tmp_path):
    class BackupArchiveService(HermesImaArchiveService):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.commands = []

        async def _run_text(self, *args):
            self.commands.append(args)
            if args[:3] == ("gh", "repo", "clone"):
                (self.github_worktree / ".git").mkdir(parents=True)
            if args[:4] == ("git", "-C", str(self.github_worktree), "status"):
                return "A  持仓分析系统知识库/example.md"
            return ""

    monkeypatch.setattr("services.hermes.ima_archive.shutil.which", lambda name: f"/usr/bin/{name}")
    service = BackupArchiveService(
        archive_root=tmp_path / "archive",
        skill_dir=tmp_path / "missing-skill",
        knowledge_base_id="kb-test",
        enabled=True,
        upload_enabled=False,
        github_backup_enabled=True,
        github_repo="jerrywuhz-pixel/obsidan-vault",
        github_branch="main",
        github_base_path="持仓分析系统知识库",
        github_worktree=tmp_path / "repo",
    )

    result = await service.archive(
        source="wechat_user_reply",
        title="Hermes 用户回复",
        content_markdown="用户问答内容",
        payload={"reply_text": "用户问答内容"},
        result_type="market_quote",
    )

    backup = result["github_backup"]
    assert backup["status"] == "synced"
    assert backup["repo"] == "jerrywuhz-pixel/obsidan-vault"
    assert backup["path"].startswith("持仓分析系统知识库/")
    assert (tmp_path / "repo" / backup["path"]).read_text(encoding="utf-8").find("用户问答内容") >= 0
    assert any(command[:3] == ("gh", "repo", "clone") for command in service.commands)
    assert any("commit" in command for command in service.commands)


@pytest.mark.asyncio
async def test_ima_archive_skips_github_backup_for_routine_task(monkeypatch, tmp_path):
    monkeypatch.setattr("services.hermes.ima_archive.shutil.which", lambda name: f"/usr/bin/{name}")
    service = HermesImaArchiveService(
        archive_root=tmp_path,
        skill_dir=tmp_path / "missing-skill",
        knowledge_base_id="kb-test",
        enabled=True,
        upload_enabled=True,
        github_backup_enabled=True,
        github_repo="jerrywuhz-pixel/obsidan-vault",
        github_base_path="持仓分析系统知识库",
        github_worktree=tmp_path / "repo",
    )

    result = await service.archive(
        source="scheduled_task",
        title="Hermes 定时任务 - p0-delivery-retry",
        content_markdown="delivery retry ok",
        payload={"status": "ok", "result_type": "p0-delivery-retry"},
        result_type="p0-delivery-retry",
    )

    assert result["github_backup"] == {"status": "skipped", "reason": "routine_result_type_p0-delivery-retry"}
    assert not (tmp_path / "repo").exists()


@pytest.mark.asyncio
async def test_ima_archive_marks_quota_limited_upload_failures(tmp_path):
    class QuotaLimitedArchiveService(HermesImaArchiveService):
        async def _upload_file(self, path, filename, day):
            raise RuntimeError("IMA add_knowledge failed: code=200005 msg=请求超量，请明日再试")

    service = QuotaLimitedArchiveService(
        archive_root=tmp_path,
        skill_dir=tmp_path / "missing-skill",
        knowledge_base_id="kb-test",
        enabled=True,
        upload_enabled=True,
    )

    result = await service.archive(
        source="wechat_user_reply",
        title="Hermes 用户回复",
        content_markdown="用户问答内容",
        payload={"reply_text": "用户问答内容"},
        result_type="market_quote",
    )

    assert result["status"] == "saved"
    assert result["ima"]["status"] == "quota_limited"
