"""
Gateway Data Access Middleware
==============================
强制 tenant_id 注入 + Skill 级 API Key 隔离 + 审计日志 + 套餐配额检查

所有 Skill 对数据库的读写均应通过本中间件，禁止绕过直接访问 Supabase。
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, TYPE_CHECKING

from openclaw.gateway.supabase_client import create_skill_client

if TYPE_CHECKING:
    from openclaw.gateway.memory.memory_middleware import MemoryMiddleware

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# 异常定义
# --------------------------------------------------------------------------- #


class QuotaExceededError(Exception):
    """用户套餐配额已耗尽，阻断当前操作。"""

    pass


class TenantIdMissingError(Exception):
    """``tenant_id`` 参数缺失或为空，无法执行数据操作。"""

    pass


# --------------------------------------------------------------------------- #
# 中间件主体
# --------------------------------------------------------------------------- #


class GatewayDataMiddleware:
    """
    Skill 统一数据访问中间件。

    核心职责：
    1. **强制 tenant_id 注入**：所有 ``write`` 自动覆盖 ``data`` 中的
       ``tenant_id`` 字段，Skill 代码无法通过传入 ``tenant_id=None``
       等方式绕过租户隔离。
    2. **Skill 级 API Key 隔离**：每个中间件实例绑定一个 Skill 名与
       独立 API Key，请求头注入 ``X-Skill-Name``。
    3. **审计日志自动记录**：每次写操作（INSERT / UPDATE / DELETE）
       结束后异步写入 ``audit_logs`` 表。
    4. **套餐配额检查**：根据 ``quota_status`` 视图校验当日用量，
       超限抛出 :class:`QuotaExceededError`。
    """

    def __init__(
        self,
        skill_name: str,
        api_key: str,
        supabase_url: str,
    ) -> None:
        """
        Args:
            skill_name: Skill 标识名。
            api_key: Skill 级 Supabase API Key（建议为自定义 service_role JWT）。
            supabase_url: Supabase Project URL。
        """
        self.skill_name = skill_name
        self.supabase_url = supabase_url

        # 业务操作客户端（带 X-Skill-Name 请求头）
        self._client = create_skill_client(skill_name, api_key, supabase_url)

        # 审计日志客户端：优先使用环境变量中的 service_role key，
        # 回退到传入的 api_key（假设该 key 已具备足够权限）。
        audit_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or api_key
        self._audit_client = create_skill_client(skill_name, audit_key, supabase_url)

        # 记忆中间件（可选，由外部注入）
        self._memory_middleware: MemoryMiddleware | None = None

    # ------------------------------------------------------------------ #
    # 记忆中间件绑定
    # ------------------------------------------------------------------ #

    def attach_memory_middleware(self, mm: MemoryMiddleware) -> None:
        """注入记忆中间件实例。"""
        self._memory_middleware = mm

    # ------------------------------------------------------------------ #
    # 公开 API
    # ------------------------------------------------------------------ #

    async def write(
        self,
        table: str,
        tenant_id: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """
        安全写入（INSERT）。

        执行流程：
        1. 校验 ``tenant_id`` 非空。
        2. **强制覆盖** ``data["tenant_id"]`` — 无论 Skill 代码传入什么值。
        3. 检查写入配额。
        4. 执行 ``insert``。
        5. 记录审计日志 ``audit_logs``。
        6. 原子递增 ``quota_tracking.daily_writes``。

        Args:
            table: 目标表名。
            tenant_id: 当前用户租户 ID（由上层 Session 提取传入）。
            data: 待写入的业务数据字典。

        Returns:
            插入后的完整记录（含数据库生成的 ``id``、``created_at`` 等）。

        Raises:
            TenantIdMissingError: ``tenant_id`` 为空。
            QuotaExceededError: 当日写入配额已耗尽。
            RuntimeError: Supabase 写入失败。
        """
        if not tenant_id:
            raise TenantIdMissingError(
                "tenant_id is required and cannot be empty for write operations."
            )

        # 1. 强制注入 tenant_id（覆盖任何已有值，包括 None / 空字符串）
        sanitized: dict[str, Any] = dict(data)
        sanitized["tenant_id"] = tenant_id

        # 2. 配额检查
        await self._check_quota(tenant_id, "write")

        # 3. 执行写入
        try:
            resp = await self._client.table(table).insert(sanitized).execute()
        except Exception as exc:
            raise RuntimeError(f"Insert failed on table '{table}': {exc}") from exc

        record = resp.data[0] if resp.data else sanitized
        record_id = record.get("id")

        # 4. 审计日志（失败不阻断主流程）
        try:
            await self._log_audit(
                table=table,
                tenant_id=tenant_id,
                action="INSERT",
                record_id=record_id,
                data_after=record,
            )
        except Exception as audit_exc:  # pragma: no cover
            logger.warning(
                "Audit log failed for %s.%s (tenant=%s): %s",
                table,
                record_id,
                tenant_id,
                audit_exc,
            )

        # 5. 更新配额计数
        await self._increment_quota(tenant_id, "write")

        # 6. 记忆同步钩子（fire-and-forget，不阻塞返回）
        if self._memory_middleware is not None:
            try:
                skill_output = {
                    "table": table,
                    "record": record,
                    "operation": "INSERT",
                }
                asyncio.create_task(
                    self._memory_middleware.on_skill_complete(
                        skill_name=self.skill_name,
                        tenant_id=tenant_id,
                        skill_output=skill_output,
                    )
                )
            except Exception as mem_exc:
                logger.warning(
                    "Memory sync hook failed for %s (tenant=%s): %s",
                    self.skill_name,
                    tenant_id,
                    mem_exc,
                )

        return record

    async def read_with_context(
        self,
        table: str,
        tenant_id: str,
        skill_name: str,
        query: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        安全查询 + 记忆上下文注入。

        先执行标准 read() 查询数据库，再调用记忆中间件获取
        与该 skill 相关的记忆上下文，合并返回。

        Returns:
            {"data": [...], "brain_context": {...} | None}
        """
        rows = await self.read(table, tenant_id, query)

        brain_context = None
        if self._memory_middleware is not None:
            try:
                brain_context = await self._memory_middleware.on_skill_invoke(
                    skill_name=skill_name,
                    tenant_id=tenant_id,
                )
            except Exception as mem_exc:
                logger.warning(
                    "Memory context retrieval failed for %s (tenant=%s): %s",
                    skill_name,
                    tenant_id,
                    mem_exc,
                )

        return {
            "data": rows,
            "brain_context": brain_context,
        }

    async def read(
        self,
        table: str,
        tenant_id: str,
        query: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        安全只读查询（SELECT）。

        自动注入 ``tenant_id = ...`` 过滤条件，Skill 代码无法构造跨租户查询。
        支持简单的等值过滤与操作符过滤。

        Args:
            table: 目标表名。
            tenant_id: 当前用户租户 ID。
            query: 额外过滤条件，格式示例::

                # 等值过滤
                {"symbol": "600519", "side": "BUY"}

                # 操作符过滤（支持 gt / gte / lt / lte / neq / like / ilike）
                {"trade_amount": {"op": "gt", "value": 10000}}

        Returns:
            记录列表；无结果时返回空列表 ``[]``。

        Raises:
            TenantIdMissingError: ``tenant_id`` 为空。
            RuntimeError: Supabase 查询失败。
        """
        if not tenant_id:
            raise TenantIdMissingError(
                "tenant_id is required and cannot be empty for read operations."
            )

        # 1. 读配额检查（非阻断性失败则放行）
        try:
            await self._check_quota(tenant_id, "read")
        except Exception:
            pass

        # 2. 构建查询 — 强制注入 tenant_id
        builder = self._client.table(table).select("*").eq("tenant_id", tenant_id)

        if query:
            for column, val in query.items():
                if column == "tenant_id":
                    continue  # 已强制注入，忽略外部传入
                if isinstance(val, dict) and "op" in val and "value" in val:
                    op: str = val["op"]
                    operand: Any = val["value"]
                    builder = getattr(builder, op)(column, operand)
                else:
                    builder = builder.eq(column, val)

        # 3. 执行查询
        try:
            resp = await builder.execute()
        except Exception as exc:
            raise RuntimeError(f"Select failed on table '{table}': {exc}") from exc

        # 4. 更新读配额（失败不影响返回结果）
        try:
            await self._increment_quota(tenant_id, "read")
        except Exception:  # pragma: no cover
            pass

        return resp.data or []

    async def update(
        self,
        table: str,
        tenant_id: str,
        record_id: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """
        安全更新（UPDATE）。

        仅允许更新属于当前租户的记录；更新前自动记录原值到审计日志。

        Args:
            table: 目标表名。
            tenant_id: 当前用户租户 ID。
            record_id: 待更新记录的主键 UUID。
            data: 待更新的字段字典。

        Returns:
            更新后的完整记录。

        Raises:
            TenantIdMissingError: ``tenant_id`` 为空。
            QuotaExceededError: 当日写入配额已耗尽。
            RuntimeError: 记录不存在或更新失败。
        """
        if not tenant_id:
            raise TenantIdMissingError(
                "tenant_id is required and cannot be empty for update operations."
            )

        # 强制注入 tenant_id，防止 Skill 篡改归属
        sanitized = dict(data)
        sanitized["tenant_id"] = tenant_id
        sanitized.pop("id", None)  # 禁止更新主键

        await self._check_quota(tenant_id, "write")

        # 读取原值用于审计
        try:
            old_resp = (
                await self._client.table(table)
                .select("*")
                .eq("id", record_id)
                .eq("tenant_id", tenant_id)
                .limit(1)
                .execute()
            )
            old_record = old_resp.data[0] if old_resp.data else None
        except Exception:
            old_record = None

        # 执行更新
        try:
            resp = (
                await self._client.table(table)
                .update(sanitized)
                .eq("id", record_id)
                .eq("tenant_id", tenant_id)
                .execute()
            )
        except Exception as exc:
            raise RuntimeError(f"Update failed on table '{table}': {exc}") from exc

        new_record = resp.data[0] if resp.data else sanitized

        # 审计日志
        try:
            await self._log_audit(
                table=table,
                tenant_id=tenant_id,
                action="UPDATE",
                record_id=record_id,
                data_before=old_record,
                data_after=new_record,
            )
        except Exception as audit_exc:  # pragma: no cover
            logger.warning(
                "Audit log failed for update %s.%s (tenant=%s): %s",
                table,
                record_id,
                tenant_id,
                audit_exc,
            )

        await self._increment_quota(tenant_id, "write")
        return new_record

    async def delete(
        self,
        table: str,
        tenant_id: str,
        record_id: str,
    ) -> dict[str, Any]:
        """
        安全删除（DELETE）。

        仅允许删除属于当前租户的记录；删除前记录原值到审计日志。

        Args:
            table: 目标表名。
            tenant_id: 当前用户租户 ID。
            record_id: 待删除记录的主键 UUID。

        Returns:
            被删除的完整记录。

        Raises:
            TenantIdMissingError: ``tenant_id`` 为空。
            QuotaExceededError: 当日写入配额已耗尽。
            RuntimeError: 记录不存在或删除失败。
        """
        if not tenant_id:
            raise TenantIdMissingError(
                "tenant_id is required and cannot be empty for delete operations."
            )

        await self._check_quota(tenant_id, "write")

        # 读取原值用于审计
        try:
            old_resp = (
                await self._client.table(table)
                .select("*")
                .eq("id", record_id)
                .eq("tenant_id", tenant_id)
                .limit(1)
                .execute()
            )
            old_record = old_resp.data[0] if old_resp.data else None
        except Exception:
            old_record = None

        # 执行删除
        try:
            resp = (
                await self._client.table(table)
                .delete()
                .eq("id", record_id)
                .eq("tenant_id", tenant_id)
                .execute()
            )
        except Exception as exc:
            raise RuntimeError(f"Delete failed on table '{table}': {exc}") from exc

        deleted = resp.data[0] if resp.data else old_record

        # 审计日志
        try:
            await self._log_audit(
                table=table,
                tenant_id=tenant_id,
                action="DELETE",
                record_id=record_id,
                data_before=deleted,
            )
        except Exception as audit_exc:  # pragma: no cover
            logger.warning(
                "Audit log failed for delete %s.%s (tenant=%s): %s",
                table,
                record_id,
                tenant_id,
                audit_exc,
            )

        await self._increment_quota(tenant_id, "write")
        return deleted

    # ------------------------------------------------------------------ #
    # 内部方法
    # ------------------------------------------------------------------ #

    async def _check_quota(self, tenant_id: str, operation: str) -> None:
        """
        检查用户套餐配额。

        通过 ``quota_status`` 视图读取当前用量与套餐上限。
        若 ``quota_reset_at`` 超过 24 小时，计数逻辑上已失效，
        实际重置由 :meth:`_increment_quota` 负责。

        Args:
            tenant_id: 租户 ID。
            operation: ``write`` | ``read`` | ``ai_call``。

        Raises:
            QuotaExceededError: 用量已达到或超过上限。
        """
        if operation not in ("write", "read", "ai_call"):
            return

        try:
            resp = (
                await self._client.table("quota_status")
                .select("*")
                .eq("tenant_id", tenant_id)
                .limit(1)
                .execute()
            )
        except Exception:
            # 视图不存在或网络故障时，降级放行，避免阻断业务
            return

        if not resp.data:
            return

        row = resp.data[0]

        usage_col = {
            "write": "daily_writes",
            "read": "daily_reads",
            "ai_call": "daily_ai_calls",
        }.get(operation)

        limit_col = {
            "write": "max_daily_writes",
            "read": "max_daily_reads",
            "ai_call": "max_daily_ai_calls",
        }.get(operation)

        if usage_col is None or limit_col is None:
            return

        usage = row.get(usage_col, 0) or 0
        limit_val = row.get(limit_col, 0) or 0

        if usage >= limit_val:
            raise QuotaExceededError(
                f"Quota exceeded for tenant '{tenant_id}' on operation '{operation}': "
                f"usage={usage}, limit={limit_val}, plan={row.get('plan', 'unknown')}"
            )

    async def _increment_quota(self, tenant_id: str, operation: str) -> None:
        """
        递增配额计数器；若超过 24 小时未重置，则归零后重新计数。

        当前实现基于客户端读取-更新逻辑，存在轻微竞态窗口。
        高并发场景建议后续迁移至 ``increment_quota`` Postgres RPC。
        """
        col = {
            "write": "daily_writes",
            "read": "daily_reads",
            "ai_call": "daily_ai_calls",
        }.get(operation)

        if col is None:
            return

        now = datetime.now(timezone.utc)

        # 查询现有记录
        try:
            resp = (
                await self._client.table("quota_tracking")
                .select("*")
                .eq("tenant_id", tenant_id)
                .limit(1)
                .execute()
            )
        except Exception:
            return

        row = resp.data[0] if resp.data else None

        if row is None:
            # 初始化租户配额记录
            payload = {
                "tenant_id": tenant_id,
                "daily_writes": 0,
                "daily_reads": 0,
                "daily_ai_calls": 0,
                col: 1,
                "quota_reset_at": now.isoformat(),
            }
            try:
                await self._client.table("quota_tracking").insert(payload).execute()
            except Exception:
                pass
            return

        # 判断是否需要重置（超过 24 小时）
        reset_at_raw = row.get("quota_reset_at")
        if reset_at_raw:
            try:
                reset_at = datetime.fromisoformat(str(reset_at_raw).replace("Z", "+00:00"))
                needs_reset = now - reset_at >= timedelta(hours=24)
            except ValueError:
                needs_reset = True
        else:
            needs_reset = True

        if needs_reset:
            update_payload = {
                "daily_writes": 1 if col == "daily_writes" else 0,
                "daily_reads": 1 if col == "daily_reads" else 0,
                "daily_ai_calls": 1 if col == "daily_ai_calls" else 0,
                "quota_reset_at": now.isoformat(),
            }
        else:
            current = row.get(col, 0) or 0
            update_payload = {col: current + 1}

        try:
            await (
                self._client.table("quota_tracking")
                .update(update_payload)
                .eq("tenant_id", tenant_id)
                .execute()
            )
        except Exception:
            pass

    async def _log_audit(
        self,
        table: str,
        tenant_id: str,
        action: str,
        record_id: str | None = None,
        data_before: dict[str, Any] | None = None,
        data_after: dict[str, Any] | None = None,
    ) -> None:
        """
        写入 ``audit_logs`` 表。

        要求审计客户端具备 ``service_role`` 权限或匹配的 RLS INSERT 策略。
        """
        payload: dict[str, Any] = {
            "tenant_id": tenant_id,
            "skill_name": self.skill_name,
            "table_name": table,
            "action": action,
        }
        if record_id is not None:
            payload["record_id"] = record_id
        if data_before is not None:
            payload["data_before"] = data_before
        if data_after is not None:
            payload["data_after"] = data_after

        try:
            await self._audit_client.table("audit_logs").insert(payload).execute()
        except Exception:
            # 审计写入失败不应阻断主业务流；由调用方或日志系统捕获
            raise
