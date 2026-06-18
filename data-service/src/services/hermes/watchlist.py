from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from typing import Any

JsonDict = dict[str, Any]


class HermesWatchlistService:
    def __init__(self, *, database_url: str = "") -> None:
        self._database_url = database_url or os.getenv("DATABASE_URL", "").strip()

    @classmethod
    def from_env(cls) -> "HermesWatchlistService":
        return cls(database_url=os.getenv("DATABASE_URL", "").strip())

    async def add_watch(
        self,
        *,
        tenant_id: str,
        symbol: str,
        market: str = "US",
        thesis: str = "",
        alert_price: float | None = None,
        alert_direction: str | None = None,
        review_days: int | None = None,
    ) -> JsonDict:
        if not self._database_url:
            return {"status": "skipped", "reason": "database_url_not_configured"}
        return await asyncio.to_thread(
            _add_watch_sync,
            self._database_url,
            tenant_id,
            symbol,
            market,
            thesis,
            alert_price,
            alert_direction,
            review_days,
        )

    async def list_watch(self, *, tenant_id: str, limit: int = 10) -> JsonDict:
        if not self._database_url:
            return {"status": "skipped", "reason": "database_url_not_configured", "items": []}
        return await asyncio.to_thread(_list_watch_sync, self._database_url, tenant_id, limit)

    async def archive_watch(self, *, tenant_id: str, symbol: str, market: str = "US") -> JsonDict:
        if not self._database_url:
            return {"status": "skipped", "reason": "database_url_not_configured"}
        return await asyncio.to_thread(_archive_watch_sync, self._database_url, tenant_id, symbol, market)


def _add_watch_sync(
    database_url: str,
    tenant_id: str,
    symbol: str,
    market: str,
    thesis: str,
    alert_price: float | None,
    alert_direction: str | None,
    review_days: int | None,
) -> JsonDict:
    import psycopg
    from psycopg.rows import dict_row
    from psycopg.types.json import Jsonb

    normalized_symbol = symbol.upper().strip()
    review_due_at = datetime.now(timezone.utc) + timedelta(days=review_days or 3)
    trigger_rules: list[JsonDict] = []
    alert_ids: list[str] = []
    if alert_price is not None and alert_direction:
        trigger_rules.append(
            {
                "source": "wechat_command",
                "condition": "price_cross",
                "direction": alert_direction,
                "threshold": alert_price,
            }
        )
    if review_days is not None:
        trigger_rules.append(
            {
                "source": "wechat_command",
                "condition": "review_due",
                "review_due_at": review_due_at.isoformat(),
            }
        )

    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            follow_view_id = _ensure_default_follow_view(cur, tenant_id)
            item = cur.execute(
                """
                INSERT INTO public.follow_view_items (
                  tenant_id, follow_view_id, symbol, name, market, target_action,
                  thesis, trigger_rules, risk_flags, next_review_at, data_lineage
                )
                VALUES (
                  %(tenant_id)s, %(follow_view_id)s, %(symbol)s, %(name)s, %(market)s, 'watch',
                  %(thesis)s, %(trigger_rules)s, '{}'::text[], %(next_review_at)s, %(data_lineage)s
                )
                ON CONFLICT (follow_view_id, symbol, market) DO UPDATE
                SET target_action = 'watch',
                    thesis = COALESCE(NULLIF(EXCLUDED.thesis, ''), public.follow_view_items.thesis),
                    trigger_rules = public.follow_view_items.trigger_rules || EXCLUDED.trigger_rules,
                    next_review_at = CASE
                      WHEN public.follow_view_items.next_review_at IS NULL THEN EXCLUDED.next_review_at
                      WHEN EXCLUDED.next_review_at IS NULL THEN public.follow_view_items.next_review_at
                      ELSE LEAST(public.follow_view_items.next_review_at, EXCLUDED.next_review_at)
                    END,
                    data_lineage = public.follow_view_items.data_lineage || EXCLUDED.data_lineage,
                    updated_at = now()
                RETURNING id
                """,
                {
                    "tenant_id": tenant_id,
                    "follow_view_id": follow_view_id,
                    "symbol": normalized_symbol,
                    "name": normalized_symbol,
                    "market": market,
                    "thesis": thesis or f"{normalized_symbol} 微信关注项",
                    "trigger_rules": Jsonb(trigger_rules),
                    "next_review_at": review_due_at,
                    "data_lineage": Jsonb([{"source": "wechat_command", "created_at": datetime.now(timezone.utc).isoformat()}]),
                },
            ).fetchone()

            if alert_price is not None and alert_direction:
                alert = cur.execute(
                    """
                    INSERT INTO public.alert_rules (
                      tenant_id, name, target_scope, target_symbol, market, alert_type,
                      parameters, severity, enabled, cooldown_policy, notification_policy, source
                    )
                    VALUES (
                      %(tenant_id)s, %(name)s, 'single_symbol', %(target_symbol)s, %(market)s, 'price_cross',
                      %(parameters)s, 'warning', true, %(cooldown_policy)s, %(notification_policy)s, 'wechat_command'
                    )
                    RETURNING id
                    """,
                    {
                        "tenant_id": tenant_id,
                        "name": f"{normalized_symbol} 价格提醒",
                        "target_symbol": normalized_symbol,
                        "market": market,
                        "parameters": Jsonb({"direction": alert_direction, "threshold": alert_price}),
                        "cooldown_policy": Jsonb({"cooldown_hours": 18, "same_trading_day": True}),
                        "notification_policy": Jsonb({"channels": ["wechat"], "command_hint": f"复核 {normalized_symbol}"}),
                    },
                ).fetchone()
                if alert and alert.get("id"):
                    alert_ids.append(str(alert["id"]))

            if review_days is not None:
                alert = cur.execute(
                    """
                    INSERT INTO public.alert_rules (
                      tenant_id, name, target_scope, target_symbol, market, alert_type,
                      parameters, severity, enabled, cooldown_policy, notification_policy, source, expires_at
                    )
                    VALUES (
                      %(tenant_id)s, %(name)s, 'single_symbol', %(target_symbol)s, %(market)s, 'decision_watch_condition',
                      %(parameters)s, 'info', true, %(cooldown_policy)s, %(notification_policy)s, 'wechat_command', %(expires_at)s
                    )
                    RETURNING id
                    """,
                    {
                        "tenant_id": tenant_id,
                        "name": f"{normalized_symbol} 复核提醒",
                        "target_symbol": normalized_symbol,
                        "market": market,
                        "parameters": Jsonb({"condition": "wechat_review_due", "review_due_at": review_due_at.isoformat()}),
                        "cooldown_policy": Jsonb({"cooldown_hours": 18, "same_trading_day": True}),
                        "notification_policy": Jsonb({"channels": ["wechat"], "command_hint": f"复核 {normalized_symbol}"}),
                        "expires_at": review_due_at + timedelta(days=1),
                    },
                ).fetchone()
                if alert and alert.get("id"):
                    alert_ids.append(str(alert["id"]))
        conn.commit()

    return {
        "status": "saved",
        "follow_view_item_id": str(item.get("id")) if item and item.get("id") else None,
        "alert_rule_ids": alert_ids,
        "symbol": normalized_symbol,
    }


def _list_watch_sync(database_url: str, tenant_id: str, limit: int) -> JsonDict:
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(
            """
            SELECT symbol, name, market, target_action, thesis, trigger_rules, risk_flags, next_review_at, updated_at
            FROM public.follow_view_items
            WHERE tenant_id = %(tenant_id)s
              AND target_action <> 'archived'
            ORDER BY updated_at DESC
            LIMIT %(limit)s
            """,
            {"tenant_id": tenant_id, "limit": limit},
        ).fetchall()
    return {"status": "ok", "items": [dict(row) for row in rows]}


def _archive_watch_sync(database_url: str, tenant_id: str, symbol: str, market: str) -> JsonDict:
    import psycopg
    from psycopg.rows import dict_row

    normalized_symbol = symbol.upper().strip()
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            item = cur.execute(
                """
                UPDATE public.follow_view_items
                SET target_action = 'archived',
                    next_review_at = NULL,
                    updated_at = now()
                WHERE tenant_id = %(tenant_id)s
                  AND symbol = %(symbol)s
                  AND market = %(market)s
                RETURNING id
                """,
                {"tenant_id": tenant_id, "symbol": normalized_symbol, "market": market},
            ).fetchone()
            cur.execute(
                """
                UPDATE public.alert_rules
                SET enabled = false, updated_at = now()
                WHERE tenant_id = %(tenant_id)s
                  AND target_symbol = %(symbol)s
                  AND market = %(market)s
                  AND source IN ('wechat_command', 'decision_signal')
                """,
                {"tenant_id": tenant_id, "symbol": normalized_symbol, "market": market},
            )
        conn.commit()
    return {"status": "archived" if item else "not_found", "symbol": normalized_symbol}


def _ensure_default_follow_view(cur: Any, tenant_id: str) -> str:
    from psycopg.types.json import Jsonb

    row = cur.execute(
        """
        WITH existing AS (
          SELECT id
          FROM public.follow_views
          WHERE tenant_id = %(tenant_id)s
          ORDER BY is_default DESC, created_at ASC
          LIMIT 1
        ), inserted AS (
          INSERT INTO public.follow_views (
            tenant_id, name, slug, strategy_focus, base_currency, is_default, settings
          )
          SELECT %(tenant_id)s, '关注清单', 'default-follow', 'watchlist', 'USD', true, %(settings)s
          WHERE NOT EXISTS (SELECT 1 FROM existing)
          ON CONFLICT (tenant_id, slug) DO UPDATE
          SET name = EXCLUDED.name,
              strategy_focus = EXCLUDED.strategy_focus,
              settings = public.follow_views.settings || EXCLUDED.settings
          RETURNING id
        )
        SELECT id FROM inserted
        UNION ALL
        SELECT id FROM existing
        LIMIT 1
        """,
        {"tenant_id": tenant_id, "settings": Jsonb({"source": "wechat_command"})},
    ).fetchone()
    if not row or not row.get("id"):
        raise RuntimeError("failed_to_ensure_follow_view")
    return str(row["id"])
