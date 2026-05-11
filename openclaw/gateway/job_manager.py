"""
JobManager — 任务生命周期管理器

管理 job_runs 记录的完整生命周期：
  PENDING → RUNNING → SUCCESS / FAILED / PARTIAL_SUCCESS / TIMED_OUT / ABANDONED

所有 Supabase 操作均通过 ``asyncio.to_thread()`` 包装，确保在异步上下文中
安全调用同步 supabase-py 客户端。
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def _get_supabase_client() -> Any:
    """
    从环境变量创建同步 Supabase 客户端。

    环境变量:
        SUPABASE_URL:        Supabase Project URL
        SUPABASE_SERVICE_ROLE_KEY:  service_role JWT（可绕过 RLS）
    """
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY environment variables are required."
        )
    from supabase import create_client

    return create_client(url, key)


class JobManager:
    """
    管理 job_runs 表记录的完整生命周期。

    用法::

        mgr = JobManager()
        job_id = await mgr.create_job("daily-analysis", tenant_id="user-uuid")
        await mgr.start_job(job_id)
        # ... 执行任务 ...
        await mgr.complete_job(job_id, result={"trades_analyzed": 5})
    """

    def __init__(self, client: Any | None = None) -> None:
        """
        Args:
            client: 可选的同步 Supabase 客户端。若不传入，则从环境变量自动创建。
        """
        self._client = client or _get_supabase_client()

    # ------------------------------------------------------------------ #
    # 生命周期方法
    # ------------------------------------------------------------------ #

    async def create_job(
        self,
        task_name: str,
        tenant_id: str | None = None,
    ) -> str:
        """
        创建 job_runs 记录，状态为 PENDING。

        自动查找 task_definitions 表获取 job_type、timeout_seconds 等信息。

        Args:
            task_name: 任务定义名称（对应 task_definitions.name）。
            tenant_id: 租户 ID。系统级任务（如 heartbeat）可不传。

        Returns:
            新创建的 job_runs 记录 UUID。

        Raises:
            RuntimeError: 数据库写入失败或任务定义不存在。
        """
        # 查找 task_definition 以获取 job_type 与默认配置
        task_def = await self._find_task_definition(task_name)

        job_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        payload: dict[str, Any] = {
            "id": job_id,
            "status": "PENDING",
            "created_at": now,
        }

        if tenant_id:
            payload["tenant_id"] = tenant_id

        if task_def:
            payload["job_type"] = task_def["job_type"]
            payload["task_definition_id"] = task_def["id"]
            payload["timeout_seconds"] = task_def.get("timeout_seconds", 120)
            # 合并 task_definition 的 config 作为 job_runs.config
            payload["config"] = task_def.get("config", {})
        else:
            # 回退：使用 task_name 作为 job_type
            logger.warning(
                "Task definition '%s' not found, using name as job_type.",
                task_name,
            )
            payload["job_type"] = task_name
            payload["timeout_seconds"] = 120

        def _insert() -> dict:
            resp = (
                self._client.table("job_runs")
                .insert(payload)
                .execute()
            )
            return resp.data[0] if resp.data else payload

        try:
            record = await asyncio.to_thread(_insert)
            logger.info("Created job %s (task=%s, tenant=%s)", job_id, task_name, tenant_id)
            return str(record.get("id", job_id))
        except Exception as exc:
            raise RuntimeError(
                f"Failed to create job for task '{task_name}': {exc}"
            ) from exc

    async def start_job(self, job_id: str) -> None:
        """
        将 job 状态设置为 RUNNING，记录 started_at。

        Args:
            job_id: job_runs 记录 UUID。

        Raises:
            RuntimeError: 更新失败。
        """
        now = datetime.now(timezone.utc).isoformat()

        def _update() -> None:
            self._client.table("job_runs").update({
                "status": "RUNNING",
                "started_at": now,
            }).eq("id", job_id).execute()

        try:
            await asyncio.to_thread(_update)
            logger.info("Started job %s", job_id)
        except Exception as exc:
            raise RuntimeError(f"Failed to start job '{job_id}': {exc}") from exc

    async def complete_job(
        self,
        job_id: str,
        result: dict[str, Any] | None = None,
    ) -> None:
        """
        将 job 状态设置为 SUCCESS，记录 completed_at 与 result_summary。

        Args:
            job_id: job_runs 记录 UUID。
            result: 可选的结果摘要，将写入 result_summary 字段。

        Raises:
            RuntimeError: 更新失败。
        """
        now = datetime.now(timezone.utc).isoformat()

        payload: dict[str, Any] = {
            "status": "SUCCESS",
            "completed_at": now,
        }
        if result is not None:
            payload["result_summary"] = result

        def _update() -> None:
            self._client.table("job_runs").update(payload).eq("id", job_id).execute()

        try:
            await asyncio.to_thread(_update)
            logger.info("Completed job %s", job_id)
        except Exception as exc:
            raise RuntimeError(f"Failed to complete job '{job_id}': {exc}") from exc

    async def fail_job(self, job_id: str, error: str) -> None:
        """
        将 job 状态设置为 FAILED，记录 error_message 并递增 retry_count。

        Args:
            job_id: job_runs 记录 UUID。
            error: 错误信息。

        Raises:
            RuntimeError: 更新失败。
        """
        now = datetime.now(timezone.utc).isoformat()

        def _update() -> None:
            # 先读取当前 retry_count
            # TODO: 使用原子递增（如 Supabase RPC / 原始 SQL）消除读-改-写竞态条件
            resp = (
                self._client.table("job_runs")
                .select("retry_count")
                .eq("id", job_id)
                .limit(1)
                .execute()
            )
            current_retries = resp.data[0]["retry_count"] if resp.data else 0
            self._client.table("job_runs").update({
                "status": "FAILED",
                "error_message": error,
                "retry_count": current_retries + 1,
                "completed_at": now,
            }).eq("id", job_id).execute()

        try:
            await asyncio.to_thread(_update)
            logger.warning("Failed job %s: %s", job_id, error[:200])
        except Exception as exc:
            raise RuntimeError(f"Failed to update job '{job_id}' as FAILED: {exc}") from exc

    async def timeout_job(self, job_id: str) -> None:
        """
        将 job 状态设置为 TIMED_OUT，记录 completed_at。

        由 Heartbeat Skill 在检测到 RUNNING 超时后调用。

        Args:
            job_id: job_runs 记录 UUID。

        Raises:
            RuntimeError: 更新失败。
        """
        now = datetime.now(timezone.utc).isoformat()

        def _update() -> None:
            self._client.table("job_runs").update({
                "status": "TIMED_OUT",
                "completed_at": now,
                "error_message": "Job timed out (detected by heartbeat)",
            }).eq("id", job_id).execute()

        try:
            await asyncio.to_thread(_update)
            logger.warning("Timed out job %s", job_id)
        except Exception as exc:
            raise RuntimeError(f"Failed to timeout job '{job_id}': {exc}") from exc

    async def abandon_job(self, job_id: str) -> None:
        """
        将 job 状态设置为 ABANDONED，记录 completed_at。

        当 retry_count >= max_retries 时由 Heartbeat 调用。

        Args:
            job_id: job_runs 记录 UUID。

        Raises:
            RuntimeError: 更新失败。
        """
        now = datetime.now(timezone.utc).isoformat()

        def _update() -> None:
            self._client.table("job_runs").update({
                "status": "ABANDONED",
                "completed_at": now,
                "error_message": "Job abandoned after max retries",
            }).eq("id", job_id).execute()

        try:
            await asyncio.to_thread(_update)
            logger.warning("Abandoned job %s", job_id)
        except Exception as exc:
            raise RuntimeError(f"Failed to abandon job '{job_id}': {exc}") from exc

    # ------------------------------------------------------------------ #
    # 查询方法（供 Heartbeat 等使用）
    # ------------------------------------------------------------------ #

    async def find_stale_pending_jobs(
        self,
        stale_threshold_minutes: int = 5,
    ) -> list[dict[str, Any]]:
        """
        查找 PENDING 状态超过指定时间的 job（可能丢失启动信号）。

        Args:
            stale_threshold_minutes: 超时阈值（分钟），默认 5。

        Returns:
            过期的 PENDING job 列表。
        """
        from datetime import timedelta

        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=stale_threshold_minutes)).isoformat()

        def _query() -> list:
            resp = (
                self._client.table("job_runs")
                .select("id, job_type, task_definition_id, created_at, timeout_seconds")
                .eq("status", "PENDING")
                .lt("created_at", cutoff)
                .execute()
            )
            return resp.data or []

        try:
            return await asyncio.to_thread(_query)
        except Exception as exc:
            logger.error("Failed to query stale pending jobs: %s", exc)
            return []

    async def find_timed_out_running_jobs(self) -> list[dict[str, Any]]:
        """
        查找 RUNNING 状态但已超过 timeout_seconds 的 job。

        使用 COALESCE(timeout_seconds, 120) 作为默认超时。

        Returns:
            超时的 RUNNING job 列表。
        """
        from datetime import timedelta

        # 查所有 RUNNING 的 job，在应用层判断超时
        def _query() -> list:
            resp = (
                self._client.table("job_runs")
                .select("id, job_type, started_at, timeout_seconds")
                .eq("status", "RUNNING")
                .execute()
            )
            return resp.data or []

        try:
            running_jobs = await asyncio.to_thread(_query)
        except Exception as exc:
            logger.error("Failed to query running jobs: %s", exc)
            return []

        # 在应用层过滤：started_at + timeout_seconds < now
        now = datetime.now(timezone.utc)
        timed_out: list[dict[str, Any]] = []
        for job in running_jobs:
            started_at_raw = job.get("started_at")
            if not started_at_raw:
                # 没有 started_at 但状态为 RUNNING，视为异常
                timed_out.append(job)
                continue
            try:
                started_at = datetime.fromisoformat(
                    str(started_at_raw).replace("Z", "+00:00")
                )
            except ValueError:
                timed_out.append(job)
                continue

            timeout_secs = job.get("timeout_seconds") or 120
            if (now - started_at).total_seconds() > timeout_secs:
                timed_out.append(job)

        return timed_out

    # ------------------------------------------------------------------ #
    # 内部方法
    # ------------------------------------------------------------------ #

    async def _find_task_definition(
        self, task_name: str
    ) -> dict[str, Any] | None:
        """
        根据 task_name 查找 task_definitions 记录。

        Args:
            task_name: 任务定义名称。

        Returns:
            任务定义记录，不存在则返回 None。
        """
        def _query() -> list:
            resp = (
                self._client.table("task_definitions")
                .select("*")
                .eq("name", task_name)
                .limit(1)
                .execute()
            )
            return resp.data or []

        try:
            records = await asyncio.to_thread(_query)
            return records[0] if records else None
        except Exception as exc:
            logger.warning(
                "Failed to query task_definition '%s': %s", task_name, exc
            )
            return None
