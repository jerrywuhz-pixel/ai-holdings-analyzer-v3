"""Cron scheduler worker for task_definitions-backed scheduled jobs."""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Protocol
from zoneinfo import ZoneInfo

import httpx

logger = logging.getLogger(__name__)

SCHEDULER_SOURCE = "openclaw-cron-scheduler"


@dataclass(frozen=True)
class CronTaskDefinition:
    id: str
    name: str
    job_type: str
    cron_expression: str
    skill_name: str
    config: dict[str, Any]
    timeout_seconds: int = 120
    max_retries: int = 3
    is_enabled: bool = True


@dataclass
class CronHttpDispatchResult:
    ok: bool
    status_code: Optional[int] = None
    response: Any = None
    error_message: Optional[str] = None


@dataclass
class CronSchedulerStats:
    scanned_tasks: int = 0
    scheduler_enabled_tasks: int = 0
    due: int = 0
    created: int = 0
    skipped_existing: int = 0
    retried: int = 0
    dispatched: int = 0
    succeeded: int = 0
    failed: int = 0
    abandoned: int = 0


class CronTaskExecutor(Protocol):
    async def dispatch(self, job: dict[str, Any], task: CronTaskDefinition) -> CronHttpDispatchResult:
        ...


class CronSchedulerRepository(Protocol):
    async def list_enabled_task_definitions(self) -> list[CronTaskDefinition]:
        ...

    async def find_job_by_dedupe_key(self, dedupe_key: str) -> Optional[dict[str, Any]]:
        ...

    async def create_scheduled_job(
        self,
        task: CronTaskDefinition,
        *,
        scheduled_for: datetime,
        scheduled_for_local: datetime,
        dedupe_key: str,
        now: datetime,
    ) -> dict[str, Any]:
        ...

    async def list_retryable_scheduler_jobs(
        self,
        *,
        now: datetime,
        retry_backoff_seconds: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        ...

    async def list_abandonable_scheduler_jobs(self, *, limit: int) -> list[dict[str, Any]]:
        ...

    async def get_task_definition(self, task_definition_id: str) -> Optional[CronTaskDefinition]:
        ...

    async def start_job(self, job_id: str, now: datetime) -> None:
        ...

    async def complete_job(self, job_id: str, result: dict[str, Any], now: datetime) -> None:
        ...

    async def fail_job(self, job_id: str, error: str, result: dict[str, Any], now: datetime) -> None:
        ...

    async def abandon_job(self, job_id: str, reason: str, now: datetime) -> None:
        ...


def cron_matches(expression: str, local_time: datetime) -> bool:
    parts = expression.split()
    if len(parts) != 5:
        raise ValueError(f"Unsupported cron expression '{expression}': expected 5 fields")
    minute, hour, day_of_month, month, day_of_week = parts
    cron_weekday = (local_time.weekday() + 1) % 7
    return (
        _field_matches(minute, local_time.minute, 0, 59)
        and _field_matches(hour, local_time.hour, 0, 23)
        and _field_matches(day_of_month, local_time.day, 1, 31)
        and _field_matches(month, local_time.month, 1, 12)
        and _field_matches(day_of_week, cron_weekday, 0, 7, sunday_alias=True)
    )


def _field_matches(field: str, value: int, minimum: int, maximum: int, *, sunday_alias: bool = False) -> bool:
    for token in field.split(","):
        token = token.strip()
        if not token:
            continue
        if _token_matches(token, value, minimum, maximum, sunday_alias=sunday_alias):
            return True
    return False


def _token_matches(token: str, value: int, minimum: int, maximum: int, *, sunday_alias: bool) -> bool:
    step = 1
    base = token
    if "/" in token:
        base, step_raw = token.split("/", 1)
        step = int(step_raw)
        if step <= 0:
            raise ValueError(f"Invalid cron step in '{token}'")

    if base == "*":
        start, end = minimum, maximum
    elif "-" in base:
        start_raw, end_raw = base.split("-", 1)
        start, end = int(start_raw), int(end_raw)
    else:
        expected = int(base)
        if sunday_alias and expected == 7:
            expected = 0
        return value == expected

    if sunday_alias and end == 7:
        end = 6 if start > 0 else 7
    if start > end:
        return False
    return start <= value <= end and ((value - start) % step == 0)


def scheduler_config(task: CronTaskDefinition) -> dict[str, Any]:
    raw = task.config.get("scheduler") if isinstance(task.config, dict) else None
    return raw if isinstance(raw, dict) else {}


def is_scheduler_enabled(task: CronTaskDefinition) -> bool:
    config = scheduler_config(task)
    return task.is_enabled and bool(config.get("enabled")) and bool(config.get("endpoint_path"))


def scheduler_dedupe_key(task: CronTaskDefinition, scheduled_for_local: datetime) -> str:
    return f"{task.name}:{scheduled_for_local.strftime('%Y%m%d%H%M')}"


class CronHttpExecutor:
    def __init__(
        self,
        *,
        base_url: str,
        cron_secret: Optional[str] = None,
        timeout_seconds: float = 30.0,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._cron_secret = cron_secret
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    async def dispatch(self, job: dict[str, Any], task: CronTaskDefinition) -> CronHttpDispatchResult:
        config = scheduler_config(task)
        endpoint_path = str(config.get("endpoint_path") or "")
        if not endpoint_path.startswith("/"):
            return CronHttpDispatchResult(ok=False, error_message="scheduler endpoint_path must start with /")
        url = f"{self._base_url}{endpoint_path}"
        headers = {
            "X-OpenClaw-Scheduler-Job-Id": str(job["id"]),
            "X-OpenClaw-Task-Name": task.name,
        }
        dedupe_key = _job_scheduler_metadata(job).get("dedupe_key")
        if dedupe_key:
            headers["X-OpenClaw-Scheduler-Dedupe-Key"] = str(dedupe_key)
        if self._cron_secret:
            headers["Authorization"] = f"Bearer {self._cron_secret}"
        payload = config.get("payload")
        if payload is None:
            payload = {}
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout_seconds,
                transport=self._transport,
            ) as client:
                response = await client.post(url, json=payload, headers=headers)
            try:
                body: Any = response.json()
            except ValueError:
                body = {"text": response.text[:1000]}
            ok = 200 <= response.status_code < 300
            if isinstance(body, dict) and body.get("ok") is False:
                ok = False
            return CronHttpDispatchResult(
                ok=ok,
                status_code=response.status_code,
                response=body,
                error_message=None if ok else _response_error_message(body, response.status_code),
            )
        except Exception as exc:
            return CronHttpDispatchResult(ok=False, error_message=str(exc))


class InMemoryCronSchedulerRepository:
    def __init__(
        self,
        *,
        tasks: list[CronTaskDefinition],
        jobs: Optional[dict[str, dict[str, Any]]] = None,
    ) -> None:
        self.tasks = {task.id: task for task in tasks}
        self.jobs = jobs if jobs is not None else {}

    async def list_enabled_task_definitions(self) -> list[CronTaskDefinition]:
        return [task for task in self.tasks.values() if task.is_enabled]

    async def find_job_by_dedupe_key(self, dedupe_key: str) -> Optional[dict[str, Any]]:
        for job in self.jobs.values():
            if _job_scheduler_metadata(job).get("dedupe_key") == dedupe_key:
                return dict(job)
        return None

    async def create_scheduled_job(
        self,
        task: CronTaskDefinition,
        *,
        scheduled_for: datetime,
        scheduled_for_local: datetime,
        dedupe_key: str,
        now: datetime,
    ) -> dict[str, Any]:
        job_id = str(uuid.uuid4())
        config = _scheduled_job_config(task, scheduled_for, scheduled_for_local, dedupe_key)
        job = {
            "id": job_id,
            "job_type": task.job_type,
            "task_definition_id": task.id,
            "status": "PENDING",
            "config": config,
            "retry_count": 0,
            "timeout_seconds": task.timeout_seconds,
            "created_at": now,
        }
        self.jobs[job_id] = job
        return dict(job)

    async def list_retryable_scheduler_jobs(
        self,
        *,
        now: datetime,
        retry_backoff_seconds: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        jobs: list[dict[str, Any]] = []
        for job in self.jobs.values():
            task = self.tasks.get(str(job.get("task_definition_id")))
            if not task or job.get("status") not in {"FAILED", "TIMED_OUT"}:
                continue
            if _job_scheduler_metadata(job).get("source") != SCHEDULER_SOURCE:
                continue
            retry_count = int(job.get("retry_count") or 0)
            if retry_count >= task.max_retries:
                continue
            if not _retry_backoff_elapsed(job, now, retry_backoff_seconds):
                continue
            jobs.append(dict(job))
        jobs.sort(key=lambda item: str(item.get("completed_at") or item.get("created_at") or ""))
        return jobs[:limit]

    async def list_abandonable_scheduler_jobs(self, *, limit: int) -> list[dict[str, Any]]:
        jobs: list[dict[str, Any]] = []
        for job in self.jobs.values():
            task = self.tasks.get(str(job.get("task_definition_id")))
            if not task or job.get("status") not in {"FAILED", "TIMED_OUT"}:
                continue
            if _job_scheduler_metadata(job).get("source") != SCHEDULER_SOURCE:
                continue
            if int(job.get("retry_count") or 0) >= task.max_retries:
                jobs.append(dict(job))
        return jobs[:limit]

    async def get_task_definition(self, task_definition_id: str) -> Optional[CronTaskDefinition]:
        return self.tasks.get(task_definition_id)

    async def start_job(self, job_id: str, now: datetime) -> None:
        self.jobs[job_id].update({"status": "RUNNING", "started_at": now, "error_message": None})

    async def complete_job(self, job_id: str, result: dict[str, Any], now: datetime) -> None:
        self.jobs[job_id].update({"status": "SUCCESS", "result_summary": result, "completed_at": now})

    async def fail_job(self, job_id: str, error: str, result: dict[str, Any], now: datetime) -> None:
        job = self.jobs[job_id]
        job.update(
            {
                "status": "FAILED",
                "error_message": error,
                "result_summary": result,
                "retry_count": int(job.get("retry_count") or 0) + 1,
                "completed_at": now,
            }
        )

    async def abandon_job(self, job_id: str, reason: str, now: datetime) -> None:
        self.jobs[job_id].update({"status": "ABANDONED", "error_message": reason, "completed_at": now})


class PostgresCronSchedulerRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    async def list_enabled_task_definitions(self) -> list[CronTaskDefinition]:
        from psycopg import connect
        from psycopg.rows import dict_row

        def _query() -> list[CronTaskDefinition]:
            with connect(self._database_url, row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT *
                        FROM public.task_definitions
                        WHERE is_enabled = TRUE
                        ORDER BY name ASC
                        """
                    )
                    return [_task_from_row(dict(row)) for row in cur.fetchall()]

        return await asyncio.to_thread(_query)

    async def find_job_by_dedupe_key(self, dedupe_key: str) -> Optional[dict[str, Any]]:
        from psycopg import connect
        from psycopg.rows import dict_row

        def _query() -> Optional[dict[str, Any]]:
            with connect(self._database_url, row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT *
                        FROM public.job_runs
                        WHERE config->'scheduler'->>'dedupe_key' = %s
                        LIMIT 1
                        """,
                        [dedupe_key],
                    )
                    row = cur.fetchone()
                    return dict(row) if row else None

        return await asyncio.to_thread(_query)

    async def create_scheduled_job(
        self,
        task: CronTaskDefinition,
        *,
        scheduled_for: datetime,
        scheduled_for_local: datetime,
        dedupe_key: str,
        now: datetime,
    ) -> dict[str, Any]:
        from psycopg import connect
        from psycopg.rows import dict_row
        from psycopg.types.json import Jsonb

        config = _scheduled_job_config(task, scheduled_for, scheduled_for_local, dedupe_key)

        def _insert() -> dict[str, Any]:
            with connect(self._database_url, row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO public.job_runs (
                          job_type,
                          task_definition_id,
                          status,
                          config,
                          timeout_seconds,
                          retry_count,
                          created_at
                        )
                        VALUES (%s, %s, 'PENDING', %s, %s, 0, %s)
                        ON CONFLICT DO NOTHING
                        RETURNING *
                        """,
                        [task.job_type, task.id, Jsonb(config), task.timeout_seconds, now],
                    )
                    row = cur.fetchone()
                    if row:
                        return dict(row)
                    cur.execute(
                        """
                        SELECT *
                        FROM public.job_runs
                        WHERE config->'scheduler'->>'dedupe_key' = %s
                        LIMIT 1
                        """,
                        [dedupe_key],
                    )
                    existing = cur.fetchone()
                    if not existing:
                        raise RuntimeError(f"failed to create scheduled job for {dedupe_key}")
                    return dict(existing)

        return await asyncio.to_thread(_insert)

    async def list_retryable_scheduler_jobs(
        self,
        *,
        now: datetime,
        retry_backoff_seconds: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        rows = await self._list_failed_scheduler_jobs(limit=limit, retryable=True)
        return [
            row
            for row in rows
            if _retry_backoff_elapsed(row, now, retry_backoff_seconds)
        ]

    async def list_abandonable_scheduler_jobs(self, *, limit: int) -> list[dict[str, Any]]:
        return await self._list_failed_scheduler_jobs(limit=limit, retryable=False)

    async def get_task_definition(self, task_definition_id: str) -> Optional[CronTaskDefinition]:
        from psycopg import connect
        from psycopg.rows import dict_row

        def _query() -> Optional[CronTaskDefinition]:
            with connect(self._database_url, row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT * FROM public.task_definitions WHERE id = %s LIMIT 1", [task_definition_id])
                    row = cur.fetchone()
                    return _task_from_row(dict(row)) if row else None

        return await asyncio.to_thread(_query)

    async def start_job(self, job_id: str, now: datetime) -> None:
        await self._update_job(
            job_id,
            """
            status = 'RUNNING',
            started_at = %s,
            error_message = NULL
            """,
            [now],
        )

    async def complete_job(self, job_id: str, result: dict[str, Any], now: datetime) -> None:
        from psycopg.types.json import Jsonb

        await self._update_job(
            job_id,
            """
            status = 'SUCCESS',
            result_summary = %s,
            completed_at = %s
            """,
            [Jsonb(result), now],
        )

    async def fail_job(self, job_id: str, error: str, result: dict[str, Any], now: datetime) -> None:
        from psycopg.types.json import Jsonb

        await self._update_job(
            job_id,
            """
            status = 'FAILED',
            error_message = %s,
            result_summary = %s,
            retry_count = COALESCE(retry_count, 0) + 1,
            completed_at = %s
            """,
            [error, Jsonb(result), now],
        )

    async def abandon_job(self, job_id: str, reason: str, now: datetime) -> None:
        await self._update_job(
            job_id,
            """
            status = 'ABANDONED',
            error_message = %s,
            completed_at = %s
            """,
            [reason, now],
        )

    async def _list_failed_scheduler_jobs(self, *, limit: int, retryable: bool) -> list[dict[str, Any]]:
        from psycopg import connect
        from psycopg.rows import dict_row

        operator = "<" if retryable else ">="

        def _query() -> list[dict[str, Any]]:
            with connect(self._database_url, row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        SELECT j.*
                        FROM public.job_runs j
                        JOIN public.task_definitions td ON td.id = j.task_definition_id
                        WHERE j.status IN ('FAILED', 'TIMED_OUT')
                          AND j.config->'scheduler'->>'source' = %s
                          AND COALESCE(j.retry_count, 0) {operator} COALESCE(td.max_retries, 3)
                        ORDER BY j.completed_at ASC NULLS FIRST, j.created_at ASC
                        LIMIT %s
                        """,
                        [SCHEDULER_SOURCE, limit],
                    )
                    return [dict(row) for row in cur.fetchall()]

        return await asyncio.to_thread(_query)

    async def _update_job(self, job_id: str, assignments_sql: str, values: list[Any]) -> None:
        from psycopg import connect

        def _update() -> None:
            with connect(self._database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"UPDATE public.job_runs SET {assignments_sql} WHERE id = %s",
                        [*values, job_id],
                    )

        await asyncio.to_thread(_update)


class CronSchedulerWorker:
    def __init__(
        self,
        repository: CronSchedulerRepository,
        executor: CronTaskExecutor,
        *,
        timezone_name: str = "Asia/Shanghai",
        lookback_minutes: int = 2,
        retry_backoff_seconds: int = 60,
        batch_limit: int = 50,
    ) -> None:
        self._repository = repository
        self._executor = executor
        self._timezone = ZoneInfo(timezone_name)
        self._lookback_minutes = max(0, lookback_minutes)
        self._retry_backoff_seconds = max(0, retry_backoff_seconds)
        self._batch_limit = max(1, batch_limit)

    async def process_once(self, *, now: Optional[datetime] = None) -> CronSchedulerStats:
        now = _ensure_aware(now or datetime.now(timezone.utc))
        stats = CronSchedulerStats()
        tasks = await self._repository.list_enabled_task_definitions()
        stats.scanned_tasks = len(tasks)
        tasks = [task for task in tasks if is_scheduler_enabled(task)]
        stats.scheduler_enabled_tasks = len(tasks)

        created_jobs: list[dict[str, Any]] = []
        for scheduled_for_local in self._candidate_minutes(now):
            for task in tasks:
                if not cron_matches(task.cron_expression, scheduled_for_local):
                    continue
                stats.due += 1
                dedupe_key = scheduler_dedupe_key(task, scheduled_for_local)
                existing = await self._repository.find_job_by_dedupe_key(dedupe_key)
                if existing:
                    stats.skipped_existing += 1
                    continue
                job = await self._repository.create_scheduled_job(
                    task,
                    scheduled_for=scheduled_for_local.astimezone(timezone.utc),
                    scheduled_for_local=scheduled_for_local,
                    dedupe_key=dedupe_key,
                    now=now,
                )
                created_jobs.append(job)
                stats.created += 1

        abandonable = await self._repository.list_abandonable_scheduler_jobs(limit=self._batch_limit)
        for job in abandonable:
            await self._repository.abandon_job(
                str(job["id"]),
                "Job abandoned after max retries",
                now,
            )
            stats.abandoned += 1

        retry_jobs = await self._repository.list_retryable_scheduler_jobs(
            now=now,
            retry_backoff_seconds=self._retry_backoff_seconds,
            limit=self._batch_limit,
        )
        stats.retried = len(retry_jobs)
        await self._dispatch_jobs(_unique_jobs([*created_jobs, *retry_jobs]), stats, now)
        return stats

    def _candidate_minutes(self, now: datetime) -> list[datetime]:
        local_now = now.astimezone(self._timezone).replace(second=0, microsecond=0)
        start = local_now - timedelta(minutes=self._lookback_minutes)
        return [start + timedelta(minutes=offset) for offset in range(self._lookback_minutes + 1)]

    async def _dispatch_jobs(
        self,
        jobs: list[dict[str, Any]],
        stats: CronSchedulerStats,
        now: datetime,
    ) -> None:
        for job in jobs[: self._batch_limit]:
            task = await self._repository.get_task_definition(str(job.get("task_definition_id")))
            if task is None:
                await self._repository.fail_job(
                    str(job["id"]),
                    "task definition not found",
                    {"scheduler": {"error": "task_definition_not_found"}},
                    now,
                )
                stats.failed += 1
                continue

            await self._repository.start_job(str(job["id"]), now)
            stats.dispatched += 1
            result = await self._executor.dispatch(job, task)
            summary = _result_summary(task, job, result)
            if result.ok:
                await self._repository.complete_job(str(job["id"]), summary, now)
                stats.succeeded += 1
            else:
                await self._repository.fail_job(
                    str(job["id"]),
                    result.error_message or "scheduled task dispatch failed",
                    summary,
                    now,
                )
                stats.failed += 1


def create_scheduler_worker_from_env() -> CronSchedulerWorker:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for the cron scheduler worker")
    repository = PostgresCronSchedulerRepository(database_url)
    executor = CronHttpExecutor(
        base_url=os.getenv("OPENCLAW_SCHEDULER_BASE_URL", "http://127.0.0.1:8080"),
        cron_secret=os.getenv("OPENCLAW_CRON_SECRET") or None,
        timeout_seconds=float(os.getenv("OPENCLAW_SCHEDULER_HTTP_TIMEOUT_SECONDS", "30")),
    )
    return CronSchedulerWorker(
        repository,
        executor,
        timezone_name=os.getenv("OPENCLAW_SCHEDULER_TIMEZONE", "Asia/Shanghai"),
        lookback_minutes=int(os.getenv("OPENCLAW_SCHEDULER_LOOKBACK_MINUTES", "2")),
        retry_backoff_seconds=int(os.getenv("OPENCLAW_SCHEDULER_RETRY_BACKOFF_SECONDS", "60")),
        batch_limit=int(os.getenv("OPENCLAW_SCHEDULER_BATCH_LIMIT", "50")),
    )


async def run_worker_loop(
    worker: CronSchedulerWorker,
    *,
    tick_interval_seconds: float,
    once: bool,
) -> None:
    while True:
        stats = await worker.process_once()
        logger.info("cron scheduler tick stats=%s", stats)
        if once:
            return
        await asyncio.sleep(tick_interval_seconds)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OpenClaw cron scheduler worker")
    parser.add_argument("--once", action="store_true", help="run one scheduler tick and exit")
    parser.add_argument(
        "--tick-interval",
        type=float,
        default=float(os.getenv("OPENCLAW_SCHEDULER_TICK_INTERVAL_SECONDS", "30")),
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    args = parse_args()
    asyncio.run(
        run_worker_loop(
            create_scheduler_worker_from_env(),
            tick_interval_seconds=args.tick_interval,
            once=args.once,
        )
    )


def _scheduled_job_config(
    task: CronTaskDefinition,
    scheduled_for: datetime,
    scheduled_for_local: datetime,
    dedupe_key: str,
) -> dict[str, Any]:
    config = dict(task.config or {})
    scheduler = dict(config.get("scheduler") or {})
    scheduler.update(
        {
            "source": SCHEDULER_SOURCE,
            "task_name": task.name,
            "scheduled_for": scheduled_for.isoformat(),
            "scheduled_for_local": scheduled_for_local.isoformat(),
            "dedupe_key": dedupe_key,
        }
    )
    config["scheduler"] = scheduler
    config.setdefault("trigger_type", "cron")
    return config


def _result_summary(
    task: CronTaskDefinition,
    job: dict[str, Any],
    result: CronHttpDispatchResult,
) -> dict[str, Any]:
    metadata = _job_scheduler_metadata(job)
    return {
        "scheduler": {
            "source": SCHEDULER_SOURCE,
            "task_name": task.name,
            "dedupe_key": metadata.get("dedupe_key"),
            "scheduled_for": metadata.get("scheduled_for"),
            "endpoint_path": scheduler_config(task).get("endpoint_path"),
            "http_status": result.status_code,
        },
        "response": result.response,
        "error": result.error_message,
    }


def _response_error_message(body: Any, status_code: int) -> str:
    if isinstance(body, dict):
        detail = body.get("message") or body.get("error") or body.get("detail")
        if detail:
            return str(detail)
    return f"scheduled task endpoint returned HTTP {status_code}"


def _job_scheduler_metadata(job: dict[str, Any]) -> dict[str, Any]:
    config = job.get("config")
    if not isinstance(config, dict):
        return {}
    scheduler = config.get("scheduler")
    return scheduler if isinstance(scheduler, dict) else {}


def _retry_backoff_elapsed(job: dict[str, Any], now: datetime, retry_backoff_seconds: int) -> bool:
    if retry_backoff_seconds <= 0:
        return True
    completed_at = _parse_datetime(job.get("completed_at")) or _parse_datetime(job.get("created_at"))
    if completed_at is None:
        return True
    retry_count = max(1, int(job.get("retry_count") or 1))
    return (now - completed_at).total_seconds() >= retry_backoff_seconds * retry_count


def _parse_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return _ensure_aware(value)
    if isinstance(value, str) and value:
        try:
            return _ensure_aware(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _unique_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for job in jobs:
        job_id = str(job.get("id"))
        if job_id in seen:
            continue
        seen.add(job_id)
        result.append(job)
    return result


def _task_from_row(row: dict[str, Any]) -> CronTaskDefinition:
    config = row.get("config") if isinstance(row.get("config"), dict) else {}
    return CronTaskDefinition(
        id=str(row["id"]),
        name=str(row["name"]),
        job_type=str(row["job_type"]),
        cron_expression=str(row["cron_expression"]),
        skill_name=str(row["skill_name"]),
        config=config,
        timeout_seconds=int(row.get("timeout_seconds") or 120),
        max_retries=int(row.get("max_retries") or 3),
        is_enabled=bool(row.get("is_enabled", True)),
    )


if __name__ == "__main__":
    main()
