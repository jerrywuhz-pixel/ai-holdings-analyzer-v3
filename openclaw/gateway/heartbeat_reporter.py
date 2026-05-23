"""
Heartbeat Reporter — OpenClaw Gateway 心跳上报器

定期向 Supabase openclaw_heartbeat 表写入心跳记录，
用于监控 Gateway 运行状态和检测失联。

功能：
- 定期上报 gateway 状态（健康/降级/停止）
- 检测失联：超过 15 分钟未上报 → 自动标记为 down
- 上报活跃 Skill 列表
- 上报资源使用情况（内存、CPU）
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket
import time
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

try:
    from supabase import create_client
    _HAS_SUPABASE = True
except ImportError:
    _HAS_SUPABASE = False

try:
    import psycopg
    _HAS_PSYCOPG = True
except ImportError:
    psycopg = None
    _HAS_PSYCOPG = False


def _execute_sync(builder: Any) -> Any:
    return builder.execute()


class HeartbeatReporter:
    """
    OpenClaw Gateway 心跳上报器。

    用法：
        reporter = HeartbeatReporter()
        # 启动后台心跳循环
        reporter.start(interval_seconds=300)  # 每 5 分钟
        # 或手动上报
        await reporter.report()
    """

    STALE_THRESHOLD_SECONDS = 900  # 15 minutes

    def __init__(
        self,
        instance_id: Optional[str] = None,
        deployment_mode: Optional[str] = None,
        supabase_url: Optional[str] = None,
        supabase_key: Optional[str] = None,
        database_url: Optional[str] = None,
    ) -> None:
        self.instance_id = instance_id or os.getenv(
            "OPENCLAW_INSTANCE_ID", socket.gethostname()
        )
        self.deployment_mode = deployment_mode or os.getenv("OPENCLAW_DEPLOYMENT_MODE", "local")
        self._supabase_url = (
            os.getenv("SUPABASE_URL", "") if supabase_url is None else supabase_url
        )
        self._supabase_key = (
            os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
            if supabase_key is None
            else supabase_key
        )
        self._database_url = (
            database_url
            if database_url is not None
            else (
                os.getenv("HEALTH_DATABASE_URL")
                or os.getenv("DATABASE_URL")
                or os.getenv("GBRAIN_DATABASE_URL")
                or ""
            )
        )
        self._client: Optional[Any] = None
        self._active_skills: list[str] = []
        self._claw_plugin_status: str = "unknown"
        self._running = False
        self._task: Optional[asyncio.Task] = None

    def _get_client(self) -> Optional[Any]:
        if self._client is None and _HAS_SUPABASE and self._supabase_url and self._supabase_key:
            try:
                self._client = create_client(self._supabase_url, self._supabase_key)
            except Exception as exc:
                logger.error("Failed to create Supabase client for heartbeat: %s", exc)
        return self._client

    def register_skill(self, skill_name: str) -> None:
        """注册活跃 Skill。"""
        if skill_name not in self._active_skills:
            self._active_skills.append(skill_name)

    def unregister_skill(self, skill_name: str) -> None:
        """注销 Skill。"""
        self._active_skills = [s for s in self._active_skills if s != skill_name]

    def set_claw_plugin_status(self, status: str) -> None:
        """设置 Claw 插件连接状态。"""
        self._claw_plugin_status = status

    async def report(self, gateway_status: str = "healthy") -> bool:
        """
        上报一次心跳到本机 Postgres 或 Supabase。

        Args:
            gateway_status: 网关状态 "healthy" / "degraded" / "stopped"

        Returns:
            True 上报成功，False 失败。
        """
        now = datetime.now(timezone.utc).isoformat()

        payload = {
            "instance_id": self.instance_id,
            "deployment_mode": self.deployment_mode,
            "gateway_status": self._normalize_gateway_status(gateway_status),
            "last_cron_run_at": now,
            "active_skills": self._active_skills,
            "claw_plugin_status": self._claw_plugin_status,
            "reported_at": now,
        }

        if await self._report_postgres(payload):
            return True

        client = self._get_client()
        if client is None:
            logger.warning("No heartbeat store available, skipping heartbeat report")
            return False

        try:
            await asyncio.to_thread(
                _execute_sync,
                client.table("openclaw_heartbeat")
                .upsert(payload, on_conflict="instance_id")
            )
            logger.info(
                "Heartbeat reported: instance=%s, status=%s, skills=%s",
                self.instance_id, gateway_status, self._active_skills,
            )
            return True
        except Exception as exc:
            logger.error("Failed to report heartbeat: %s", exc)
            return False

    async def _report_postgres(self, payload: dict[str, Any]) -> bool:
        if not self._database_url or not _HAS_PSYCOPG:
            return False

        try:
            await asyncio.to_thread(self._report_postgres_sync, payload)
            logger.info(
                "Heartbeat reported to Postgres: instance=%s, status=%s, skills=%s",
                self.instance_id, payload["gateway_status"], self._active_skills,
            )
            return True
        except Exception as exc:
            logger.error("Failed to report heartbeat to Postgres: %s", exc)
            return False

    def _report_postgres_sync(self, payload: dict[str, Any]) -> None:
        assert psycopg is not None
        with psycopg.connect(self._database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO public.openclaw_heartbeat (
                      instance_id,
                      deployment_mode,
                      gateway_status,
                      last_cron_run_at,
                      active_skills,
                      claw_plugin_status,
                      reported_at
                    )
                    VALUES (
                      %(instance_id)s,
                      %(deployment_mode)s,
                      %(gateway_status)s,
                      %(last_cron_run_at)s,
                      %(active_skills)s,
                      %(claw_plugin_status)s,
                      %(reported_at)s
                    )
                    ON CONFLICT (instance_id) DO UPDATE SET
                      deployment_mode = EXCLUDED.deployment_mode,
                      gateway_status = EXCLUDED.gateway_status,
                      last_cron_run_at = EXCLUDED.last_cron_run_at,
                      active_skills = EXCLUDED.active_skills,
                      claw_plugin_status = EXCLUDED.claw_plugin_status,
                      reported_at = EXCLUDED.reported_at
                    """,
                    payload,
                )
            conn.commit()

    async def mark_stale_instances(self) -> int:
        """
        标记超过 15 分钟未上报心跳的实例为 down。

        Returns:
            被标记为 down 的实例数。
        """
        postgres_count = await self._mark_stale_instances_postgres()
        if postgres_count is not None:
            return postgres_count

        client = self._get_client()
        if client is None:
            return 0

        try:
            from datetime import timedelta
            cutoff = (datetime.now(timezone.utc) - timedelta(seconds=self.STALE_THRESHOLD_SECONDS)).isoformat()

            # 查找过期的健康实例
            resp = await asyncio.to_thread(
                _execute_sync,
                client.table("openclaw_heartbeat")
                .select("instance_id")
                .eq("gateway_status", "healthy")
                .lt("reported_at", cutoff)
            )

            stale_instances = resp.data or []
            if not stale_instances:
                return 0

            # 批量更新为 down
            instance_ids = [inst["instance_id"] for inst in stale_instances]
            count = 0
            for iid in instance_ids:
                try:
                    await asyncio.to_thread(
                        _execute_sync,
                        client.table("openclaw_heartbeat")
                        .update({"gateway_status": "down"})
                        .eq("instance_id", iid)
                    )
                    count += 1
                    logger.warning("Marked instance %s as DOWN (stale heartbeat)", iid)
                except Exception:
                    pass

            return count
        except Exception as exc:
            logger.error("Failed to mark stale instances: %s", exc)
            return 0

    async def _mark_stale_instances_postgres(self) -> Optional[int]:
        if not self._database_url or not _HAS_PSYCOPG:
            return None

        try:
            return await asyncio.to_thread(self._mark_stale_instances_postgres_sync)
        except Exception as exc:
            logger.error("Failed to mark stale heartbeat instances in Postgres: %s", exc)
            return None

    def _mark_stale_instances_postgres_sync(self) -> int:
        assert psycopg is not None
        with psycopg.connect(self._database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE public.openclaw_heartbeat
                    SET gateway_status = 'down'
                    WHERE gateway_status = 'healthy'
                      AND reported_at < now() - make_interval(secs => %(threshold)s)
                    RETURNING instance_id
                    """,
                    {"threshold": self.STALE_THRESHOLD_SECONDS},
                )
                rows = cur.fetchall()
            conn.commit()
        return len(rows)

    @staticmethod
    def _normalize_gateway_status(status: str) -> str:
        if status == "stopped":
            return "down"
        if status in {"healthy", "degraded", "down", "unknown"}:
            return status
        return "unknown"

    def start(self, interval_seconds: int = 300) -> None:
        """
        启动后台心跳循环。

        Args:
            interval_seconds: 上报间隔（秒），默认 300（5 分钟）。
        """
        if self._running:
            return

        self._running = True
        self._task = asyncio.ensure_future(self._loop(interval_seconds))
        logger.info("Heartbeat reporter started (interval=%ds)", interval_seconds)

    def stop(self) -> None:
        """停止后台心跳循环，并上报 stopped 状态。"""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        # 同步上报停止状态
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(self.report(gateway_status="stopped"))
        except Exception:
            pass
        logger.info("Heartbeat reporter stopped")

    async def _loop(self, interval_seconds: int) -> None:
        """心跳循环。"""
        while self._running:
            try:
                await self.report(gateway_status="healthy")
                # 同时检查是否有失联实例
                await self.mark_stale_instances()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Heartbeat loop error: %s", exc)

            try:
                await asyncio.sleep(interval_seconds)
            except asyncio.CancelledError:
                break
