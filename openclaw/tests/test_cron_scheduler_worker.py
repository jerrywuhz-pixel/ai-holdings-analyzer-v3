from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from openclaw.gateway.cron_scheduler_worker import (
    CronHttpExecutor,
    CronHttpDispatchResult,
    CronSchedulerWorker,
    CronTaskDefinition,
    InMemoryCronSchedulerRepository,
    cron_matches,
)


class RecordingCronExecutor:
    def __init__(self, *, fail_names: set[str] | None = None) -> None:
        self.fail_names = fail_names or set()
        self.calls: list[dict] = []

    async def dispatch(self, job: dict, task: CronTaskDefinition) -> CronHttpDispatchResult:
        self.calls.append({"job_id": job["id"], "task_name": task.name})
        if task.name in self.fail_names:
            return CronHttpDispatchResult(
                ok=False,
                status_code=503,
                response={"ok": False, "message": "temporary outage"},
                error_message="temporary outage",
            )
        return CronHttpDispatchResult(
            ok=True,
            status_code=200,
            response={"ok": True, "task": task.name},
        )


def test_cron_matches_standard_weekday_expression_in_configured_timezone() -> None:
    monday_0900 = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)
    sunday_0900 = datetime(2026, 6, 7, 9, 0, tzinfo=timezone.utc)

    assert cron_matches("0 9 * * 1-5", monday_0900)
    assert not cron_matches("0 9 * * 1-5", sunday_0900)
    assert cron_matches("*/5 * * * *", datetime(2026, 6, 1, 9, 10, tzinfo=timezone.utc))
    assert not cron_matches("*/5 * * * *", datetime(2026, 6, 1, 9, 11, tzinfo=timezone.utc))


@pytest.mark.asyncio
async def test_http_executor_sends_scheduler_headers_and_cron_secret() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["authorization"] = request.headers["Authorization"]
        seen["scheduler_job_id"] = request.headers["X-OpenClaw-Scheduler-Job-Id"]
        seen["dedupe_key"] = request.headers["X-OpenClaw-Scheduler-Dedupe-Key"]
        return httpx.Response(200, json={"ok": True})

    task = CronTaskDefinition(
        id="task-heartbeat",
        name="heartbeat",
        job_type="heartbeat",
        cron_expression="*/5 * * * *",
        skill_name="heartbeat",
        config={"scheduler": {"enabled": True, "endpoint_path": "/api/cron/heartbeat"}},
    )
    executor = CronHttpExecutor(
        base_url="http://openclaw:8080",
        cron_secret="secret-123",
        transport=httpx.MockTransport(handler),
    )

    result = await executor.dispatch(
        {
            "id": "job-1",
            "config": {
                "scheduler": {
                    "dedupe_key": "heartbeat:202606010900",
                }
            },
        },
        task,
    )

    assert result.ok is True
    assert seen == {
        "path": "/api/cron/heartbeat",
        "authorization": "Bearer secret-123",
        "scheduler_job_id": "job-1",
        "dedupe_key": "heartbeat:202606010900",
    }


@pytest.mark.asyncio
async def test_scheduler_creates_one_due_job_and_dispatches_it_once() -> None:
    now = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)
    task = CronTaskDefinition(
        id="task-profit",
        name="daily-profit-taking",
        job_type="profit_taking",
        cron_expression="0 9 * * 1-5",
        skill_name="profit-taking",
        config={"scheduler": {"enabled": True, "endpoint_path": "/api/cron/profit-taking"}},
        timeout_seconds=300,
        max_retries=3,
    )
    repository = InMemoryCronSchedulerRepository(tasks=[task])
    executor = RecordingCronExecutor()
    worker = CronSchedulerWorker(repository, executor, timezone_name="UTC", lookback_minutes=0)

    first = await worker.process_once(now=now)
    second = await worker.process_once(now=now)

    assert first.created == 1
    assert first.dispatched == 1
    assert first.succeeded == 1
    assert second.created == 0
    assert second.dispatched == 0
    assert len(executor.calls) == 1
    job = next(iter(repository.jobs.values()))
    assert job["status"] == "SUCCESS"
    assert job["job_type"] == "profit_taking"
    assert job["config"]["scheduler"]["dedupe_key"] == "daily-profit-taking:202606010900"
    assert job["result_summary"]["scheduler"]["http_status"] == 200


@pytest.mark.asyncio
async def test_scheduler_retries_failed_scheduled_job_then_abandons_after_max_retries() -> None:
    now = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)
    task = CronTaskDefinition(
        id="task-heartbeat",
        name="heartbeat",
        job_type="heartbeat",
        cron_expression="*/5 * * * *",
        skill_name="heartbeat",
        config={"scheduler": {"enabled": True, "endpoint_path": "/api/cron/heartbeat"}},
        timeout_seconds=60,
        max_retries=2,
    )
    repository = InMemoryCronSchedulerRepository(tasks=[task])
    executor = RecordingCronExecutor(fail_names={"heartbeat"})
    worker = CronSchedulerWorker(
        repository,
        executor,
        timezone_name="UTC",
        lookback_minutes=0,
        retry_backoff_seconds=0,
    )

    first = await worker.process_once(now=now)
    retry = await worker.process_once(now=now + timedelta(seconds=1))
    abandon = await worker.process_once(now=now + timedelta(seconds=2))

    assert first.failed == 1
    assert retry.failed == 1
    assert abandon.abandoned == 1
    assert len(executor.calls) == 2
    job = next(iter(repository.jobs.values()))
    assert job["status"] == "ABANDONED"
    assert job["retry_count"] == 2
    assert "max retries" in job["error_message"]
