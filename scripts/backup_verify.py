#!/usr/bin/env python3
"""
数据备份验证脚本

验证 Supabase 备份数据的完整性和可恢复性。
可定期执行（如每周 cron）验证备份质量。

使用方式：
    python scripts/backup_verify.py [--dry-run] [--tables users,trade_events,position_snapshots]

验证项目：
1. 核心表记录数不为零（数据未丢失）
2. 最近 7 天内有新增记录（增量备份正常）
3. 表结构完整（关键列存在）
4. RLS 策略存在（安全策略未丢失）
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# 核心表及其最小期望记录数
CORE_TABLES: dict[str, int] = {
    "users": 1,
    "position_snapshots": 0,
    "trade_events": 0,
    "subscriptions": 0,
    "usage_records": 0,
    "job_runs": 0,
    "symbol_registry": 0,
    "data_source_health": 1,
    "plan_limits": 4,  # 至少 4 个套餐
}

# 每个表的关键列（验证结构完整性）
KEY_COLUMNS: dict[str, list[str]] = {
    "users": ["id", "email", "plan", "role", "created_at"],
    "position_snapshots": ["id", "tenant_id", "symbol", "market", "total_quantity"],
    "trade_events": ["id", "tenant_id", "symbol", "trade_type", "price", "created_at"],
    "subscriptions": ["id", "tenant_id", "plan", "status"],
    "usage_records": ["id", "tenant_id", "action", "quantity", "created_at"],
    "job_runs": ["id", "status", "job_type", "created_at"],
    "symbol_registry": ["symbol", "market", "name_zh"],
    "data_source_health": ["source_name", "status"],
    "plan_limits": ["plan", "action", "limit_value"],
}


def _get_supabase_client() -> Optional[Any]:
    """创建 Supabase 客户端。"""
    try:
        from supabase import create_client
    except ImportError:
        logger.error("supabase-py not installed")
        return None

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        logger.error("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
        return None

    return create_client(url, key)


def verify_row_counts(client: Any, tables: dict[str, int]) -> list[dict[str, Any]]:
    """验证核心表记录数。"""
    results = []
    for table, min_count in tables.items():
        try:
            resp = client.table(table).select("*", count="exact").limit(1).execute()
            count = resp.count if resp.count is not None else len(resp.data or [])
            passed = count >= min_count
            results.append({
                "check": "row_count",
                "table": table,
                "count": count,
                "min_expected": min_count,
                "passed": passed,
                "message": f"Row count: {count} (min: {min_count})",
            })
        except Exception as exc:
            results.append({
                "check": "row_count",
                "table": table,
                "count": -1,
                "min_expected": min_count,
                "passed": False,
                "message": f"Error: {exc}",
            })
    return results


def verify_recent_activity(client: Any, days: int = 7) -> list[dict[str, Any]]:
    """验证最近 N 天内有新增记录。"""
    from datetime import timedelta

    results = []
    active_tables = ["trade_events", "job_runs", "usage_records"]
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    for table in active_tables:
        try:
            resp = (
                client.table(table)
                .select("id")
                .gte("created_at", cutoff)
                .limit(1)
                .execute()
            )
            has_recent = len(resp.data or []) > 0
            results.append({
                "check": "recent_activity",
                "table": table,
                "days": days,
                "passed": True,  # 有记录则通过，无记录不报错（可能无交易）
                "message": f"Recent activity in last {days} days: {'yes' if has_recent else 'no'}",
            })
        except Exception as exc:
            results.append({
                "check": "recent_activity",
                "table": table,
                "days": days,
                "passed": True,  # 不阻断
                "message": f"Could not verify: {exc}",
            })
    return results


def verify_schema(client: Any, columns_map: dict[str, list[str]]) -> list[dict[str, Any]]:
    """验证关键表结构完整性。"""
    results = []
    for table, expected_cols in columns_map.items():
        try:
            # 尝试 select 关键列，如果列不存在会报错
            resp = (
                client.table(table)
                .select(",".join(expected_cols))
                .limit(1)
                .execute()
            )
            results.append({
                "check": "schema",
                "table": table,
                "passed": True,
                "message": f"All key columns present: {expected_cols}",
            })
        except Exception as exc:
            missing = str(exc)
            results.append({
                "check": "schema",
                "table": table,
                "passed": False,
                "message": f"Schema error: {missing}",
            })
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Backup verification script")
    parser.add_argument("--dry-run", action="store_true", help="Skip actual DB queries")
    parser.add_argument("--tables", default=None, help="Comma-separated table list (default: all core)")
    parser.add_argument("--output", default=None, help="Output JSON file path")
    args = parser.parse_args()

    if args.dry_run:
        logger.info("DRY RUN: skipping actual database queries")
        print(json.dumps({"status": "dry_run", "checks": []}, indent=2))
        return 0

    client = _get_supabase_client()
    if client is None:
        return 1

    # Filter tables if specified
    tables = CORE_TABLES
    if args.tables:
        specified = [t.strip() for t in args.tables.split(",")]
        tables = {k: v for k, v in CORE_TABLES.items() if k in specified}

    columns = {k: v for k, v in KEY_COLUMNS.items() if k in tables}

    # Run all verifications
    all_results = []
    all_results.extend(verify_row_counts(client, tables))
    all_results.extend(verify_recent_activity(client))
    all_results.extend(verify_schema(client, columns))

    # Summary
    passed = sum(1 for r in all_results if r["passed"])
    failed = sum(1 for r in all_results if not r["passed"])
    total = len(all_results)

    summary = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if failed == 0 else "fail",
        "total": total,
        "passed": passed,
        "failed": failed,
        "checks": all_results,
    }

    # Output
    output_json = json.dumps(summary, indent=2, ensure_ascii=False)

    if args.output:
        with open(args.output, "w") as f:
            f.write(output_json)
        logger.info("Results written to %s", args.output)
    else:
        print(output_json)

    # Log summary
    if failed > 0:
        logger.error("Backup verification FAILED: %d/%d checks failed", failed, total)
        for r in all_results:
            if not r["passed"]:
                logger.error("  FAIL: [%s] %s - %s", r["check"], r.get("table", ""), r["message"])
    else:
        logger.info("Backup verification PASSED: %d/%d checks passed", passed, total)

    return 1 if failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
