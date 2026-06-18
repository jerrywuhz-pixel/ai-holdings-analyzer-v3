from __future__ import annotations

import asyncio
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

JsonDict = dict[str, Any]
AsyncQuoteReader = Callable[[str, str], Awaitable[JsonDict]]


@dataclass(frozen=True)
class AlertEvaluationStats:
    scanned: int = 0
    triggered: int = 0
    skipped: int = 0
    queued: int = 0
    failed: int = 0

    def model_dump(self) -> JsonDict:
        return {
            "scanned": self.scanned,
            "triggered": self.triggered,
            "skipped": self.skipped,
            "queued": self.queued,
            "failed": self.failed,
        }


class HermesAlertEvaluator:
    def __init__(self, *, database_url: str = "", quote_reader: AsyncQuoteReader | None = None) -> None:
        self._database_url = database_url or os.getenv("DATABASE_URL", "").strip()
        self._quote_reader = quote_reader

    @classmethod
    def from_env(cls, *, quote_reader: AsyncQuoteReader | None = None) -> "HermesAlertEvaluator":
        return cls(database_url=os.getenv("DATABASE_URL", "").strip(), quote_reader=quote_reader)

    async def evaluate(self, *, limit: int = 50, dry_run: bool = False) -> JsonDict:
        if not self._database_url:
            return {"ok": False, "status": "skipped", "reason": "database_url_not_configured"}
        rules = await asyncio.to_thread(_load_enabled_rules, self._database_url, limit)
        stats = AlertEvaluationStats(scanned=len(rules))
        details: list[JsonDict] = []

        for rule in rules:
            try:
                quote = await self._read_quote(str(rule.get("target_symbol") or ""), str(rule.get("tenant_id") or ""))
                hit = evaluate_rule_hit(rule, quote, datetime.now(timezone.utc))
                if not hit.get("triggered"):
                    stats = _stats(stats, skipped=1)
                    continue
                details.append({"rule_id": str(rule.get("id")), "symbol": rule.get("target_symbol"), "reason": hit.get("reason")})
                stats = _stats(stats, triggered=1)
                if dry_run:
                    continue
                queued = await asyncio.to_thread(_persist_trigger_and_outbox, self._database_url, rule, quote, hit)
                if queued:
                    stats = _stats(stats, queued=1)
            except Exception as exc:
                details.append({"rule_id": str(rule.get("id")), "error": str(exc)})
                stats = _stats(stats, failed=1)

        return {"ok": True, "status": "ok", **stats.model_dump(), "details": details[:20]}

    async def _read_quote(self, symbol: str, tenant_id: str) -> JsonDict:
        if self._quote_reader is None:
            return {}
        result = await self._quote_reader(symbol, tenant_id)
        return _payload_data(result)


class HermesAlertCenter:
    def __init__(self, *, database_url: str = "") -> None:
        self._database_url = database_url or os.getenv("DATABASE_URL", "").strip()

    @classmethod
    def from_env(cls) -> "HermesAlertCenter":
        return cls(database_url=os.getenv("DATABASE_URL", "").strip())

    async def run_premarket(self, *, limit: int = 50, dry_run: bool = False) -> JsonDict:
        return await self._run_cycle("premarket", limit=limit, dry_run=dry_run)

    async def run_intraday(self, *, limit: int = 50, dry_run: bool = False) -> JsonDict:
        evaluator = HermesAlertEvaluator(database_url=self._database_url)
        return await evaluator.evaluate(limit=limit, dry_run=dry_run)

    async def run_postmarket(self, *, limit: int = 50, dry_run: bool = False) -> JsonDict:
        return await self._run_cycle("postmarket", limit=limit, dry_run=dry_run)

    async def _run_cycle(self, cycle: str, *, limit: int, dry_run: bool) -> JsonDict:
        if not self._database_url:
            return {"ok": False, "status": "skipped", "reason": "database_url_not_configured"}
        return await asyncio.to_thread(_run_summary_cycle, self._database_url, cycle, limit, dry_run)


def evaluate_rule_hit(rule: JsonDict, quote: JsonDict, now: datetime) -> JsonDict:
    parameters = rule.get("parameters") if isinstance(rule.get("parameters"), dict) else {}
    alert_type = str(rule.get("alert_type") or "")
    current_price = _first_number(quote, "price", "last_price", "current_price", "close")
    reference_price = _first_number(parameters, "reference_price")
    threshold_pct = _first_number(parameters, "move_threshold_pct") or 5.0

    if alert_type == "price_cross":
        threshold = _first_number(parameters, "threshold", "price")
        direction = str(parameters.get("direction") or "").lower()
        if current_price is None or threshold is None:
            return {"triggered": False, "reason": "price_or_threshold_missing"}
        if direction in {"below", "down", "lte"} and current_price <= threshold:
            return _hit("price_cross_below", current_price=current_price, threshold=threshold)
        if direction in {"above", "up", "gte"} and current_price >= threshold:
            return _hit("price_cross_above", current_price=current_price, threshold=threshold)
        return {"triggered": False, "reason": "price_cross_not_met", "current_price": current_price, "threshold": threshold}

    if alert_type in {"price_change_pct", "price_change_percent"}:
        change_pct = _first_number(quote, "change_rate", "change_percent", "change_pct")
        threshold = _first_number(parameters, "threshold_pct", "change_threshold_pct") or threshold_pct
        if change_pct is None:
            return {"triggered": False, "reason": "price_change_missing"}
        if abs(change_pct) >= threshold:
            return _hit("price_change_pct", current_price=current_price, change_pct=change_pct, threshold_pct=threshold)
        return {"triggered": False, "reason": "price_change_not_met", "change_pct": change_pct, "threshold_pct": threshold}

    if alert_type == "volume_spike":
        volume_ratio = _first_number(quote, "volume_ratio", "relative_volume")
        threshold = _first_number(parameters, "volume_ratio_threshold", "threshold") or 2.0
        if volume_ratio is not None and volume_ratio >= threshold:
            return _hit("volume_spike", current_price=current_price, volume_ratio=volume_ratio, threshold=threshold)
        return {"triggered": False, "reason": "volume_spike_not_met", "volume_ratio": volume_ratio, "threshold": threshold}

    if alert_type == "position_concentration":
        concentration = _first_number(parameters, "current_concentration_pct", "concentration_pct")
        threshold = _first_number(parameters, "threshold_pct") or 20.0
        if concentration is not None and concentration >= threshold:
            return _hit("position_concentration", concentration_pct=concentration, threshold_pct=threshold)
        return {"triggered": False, "reason": "position_concentration_not_met", "concentration_pct": concentration, "threshold_pct": threshold}

    if alert_type == "sell_put_dte_delta":
        dte = _first_number(parameters, "dte")
        delta = _first_number(parameters, "delta")
        max_delta = _first_number(parameters, "max_delta") or 0.25
        min_dte = _first_number(parameters, "min_dte") or 21
        if (dte is not None and dte <= min_dte) or (delta is not None and abs(delta) >= max_delta):
            return _hit("sell_put_dte_delta", dte=dte, delta=delta, min_dte=min_dte, max_delta=max_delta)
        return {"triggered": False, "reason": "sell_put_dte_delta_not_met", "dte": dte, "delta": delta}

    if alert_type == "earnings_window":
        event_at = _parse_datetime(parameters.get("event_at") or parameters.get("earnings_at"))
        window_days = _first_number(parameters, "window_days") or 3
        if event_at and abs((event_at - now).total_seconds()) <= window_days * 86400:
            return _hit("earnings_window", event_at=event_at.isoformat(), window_days=window_days)
        return {"triggered": False, "reason": "earnings_window_not_met", "event_at": event_at.isoformat() if event_at else None}

    if alert_type == "discipline_violation":
        actionability = _discipline_actionability(parameters)
        if actionability in {"blocked", "analysis_only"}:
            return _hit(
                "discipline_violation",
                actionability_cap=actionability,
                violations=parameters.get("violations") or [],
            )
        return {"triggered": False, "reason": "discipline_violation_not_met"}

    if current_price is not None and reference_price and reference_price > 0:
        move_pct = ((current_price - reference_price) / reference_price) * 100
        if abs(move_pct) >= threshold_pct:
            return _hit(
                "price_move_from_analysis_reference",
                current_price=current_price,
                reference_price=reference_price,
                move_pct=round(move_pct, 2),
                threshold_pct=threshold_pct,
            )

    review_due_at = _parse_datetime(parameters.get("review_due_at"))
    if review_due_at and review_due_at <= now:
        return _hit("review_due", current_price=current_price, review_due_at=review_due_at.isoformat())

    return {
        "triggered": False,
        "reason": "condition_not_met",
        "current_price": current_price,
        "reference_price": reference_price,
        "threshold_pct": threshold_pct,
    }


def _load_enabled_rules(database_url: str, limit: int) -> list[JsonDict]:
    import psycopg
    from psycopg.rows import dict_row

    now = datetime.now(timezone.utc)
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(
            """
            SELECT
              ar.*,
              ds.source_run_id,
              ds.source_artifact_id,
              ds.action_label,
              ds.reason AS signal_reason,
              ds.risk_summary AS signal_risk_summary,
              cb.id AS channel_binding_id,
              cb.openclaw_account_id,
              cb.channel_user_ref,
              cb.binding_metadata,
              cd.cooldown_until
            FROM public.alert_rules ar
            JOIN LATERAL (
              SELECT *
              FROM public.channel_bindings cb
              WHERE cb.tenant_id = ar.tenant_id
                AND cb.channel IN ('hermes_wechat', 'openclaw_wechat')
                AND cb.binding_status = 'active'
              ORDER BY cb.is_primary DESC, cb.last_seen_at DESC NULLS LAST, cb.updated_at DESC
              LIMIT 1
            ) cb ON true
            LEFT JOIN public.decision_signals ds ON ds.id = ar.decision_signal_id
            LEFT JOIN public.alert_cooldowns cd ON cd.rule_id = ar.id AND cd.target_symbol = ar.target_symbol
            WHERE ar.enabled = true
              AND (ar.expires_at IS NULL OR ar.expires_at >= %(now)s)
              AND (cd.cooldown_until IS NULL OR cd.cooldown_until <= %(now)s)
            ORDER BY ar.updated_at ASC
            LIMIT %(limit)s
            """,
            {"now": now, "limit": limit},
        ).fetchall()
        return [dict(row) for row in rows]


def _persist_trigger_and_outbox(database_url: str, rule: JsonDict, quote: JsonDict, hit: JsonDict) -> bool:
    import psycopg
    from psycopg.rows import dict_row
    from psycopg.types.json import Jsonb

    now = datetime.now(timezone.utc)
    rule_id = str(rule["id"])
    tenant_id = str(rule["tenant_id"])
    symbol = str(rule["target_symbol"])
    cooldown_hours = _cooldown_hours(rule.get("cooldown_policy"))
    cooldown_until = now + timedelta(hours=cooldown_hours)
    content = _alert_message_content(rule, quote, hit)
    dedupe_key = _alert_dedupe_key(rule, now, hit)
    content_hash = _sha256_json(content)
    binding_metadata = rule.get("binding_metadata") if isinstance(rule.get("binding_metadata"), dict) else {}

    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            trigger = cur.execute(
                """
                INSERT INTO public.alert_triggers (
                  tenant_id, rule_id, target_symbol, observed_value, threshold,
                  reason, data_source, data_timestamp, status, diagnostics, triggered_at
                )
                VALUES (
                  %(tenant_id)s, %(rule_id)s, %(target_symbol)s, %(observed_value)s, %(threshold)s,
                  %(reason)s, %(data_source)s, %(data_timestamp)s, 'triggered', %(diagnostics)s, %(triggered_at)s
                )
                RETURNING id
                """,
                {
                    "tenant_id": tenant_id,
                    "rule_id": rule_id,
                    "target_symbol": symbol,
                    "observed_value": Jsonb({"quote": quote, "hit": hit}),
                    "threshold": Jsonb(rule.get("parameters") or {}),
                    "reason": str(hit.get("reason") or "alert_triggered"),
                    "data_source": str(quote.get("source") or "unknown"),
                    "data_timestamp": now,
                    "diagnostics": Jsonb({"rule_name": rule.get("name"), "alert_type": rule.get("alert_type")}),
                    "triggered_at": now,
                },
            ).fetchone()
            trigger_id = trigger.get("id") if trigger else None

            cur.execute(
                """
                INSERT INTO public.alert_cooldowns (
                  tenant_id, rule_id, target_symbol, severity, last_triggered_at,
                  cooldown_until, reason, state, updated_at
                )
                VALUES (
                  %(tenant_id)s, %(rule_id)s, %(target_symbol)s, %(severity)s, %(last_triggered_at)s,
                  %(cooldown_until)s, %(reason)s, 'active', %(updated_at)s
                )
                ON CONFLICT (rule_id, target_symbol) DO UPDATE
                SET last_triggered_at = EXCLUDED.last_triggered_at,
                    cooldown_until = EXCLUDED.cooldown_until,
                    reason = EXCLUDED.reason,
                    state = 'active',
                    updated_at = EXCLUDED.updated_at
                """,
                {
                    "tenant_id": tenant_id,
                    "rule_id": rule_id,
                    "target_symbol": symbol,
                    "severity": rule.get("severity") or "warning",
                    "last_triggered_at": now,
                    "cooldown_until": cooldown_until,
                    "reason": str(hit.get("reason") or "alert_triggered"),
                    "updated_at": now,
                },
            )

            delivery = cur.execute(
                """
                INSERT INTO public.delivery_outbox (
                  tenant_id, channel_binding_id, source_run_id, artifact_id, openclaw_account_id,
                  content_type, content, content_snapshot_hash, content_summary, priority,
                  dedupe_key, status, attempt_count, next_retry_at, target_conversation,
                  context_token, data_snapshot_refs, expires_at
                )
                VALUES (
                  %(tenant_id)s, %(channel_binding_id)s, %(source_run_id)s, %(artifact_id)s, %(openclaw_account_id)s,
                  'alert_notification', %(content)s, %(content_snapshot_hash)s, %(content_summary)s, %(priority)s,
                  %(dedupe_key)s, 'pending', 0, %(next_retry_at)s, %(target_conversation)s,
                  %(context_token)s, %(data_snapshot_refs)s, %(expires_at)s
                )
                ON CONFLICT (tenant_id, dedupe_key) DO NOTHING
                RETURNING id
                """,
                {
                    "tenant_id": tenant_id,
                    "channel_binding_id": rule.get("channel_binding_id"),
                    "source_run_id": rule.get("source_run_id"),
                    "artifact_id": rule.get("source_artifact_id"),
                    "openclaw_account_id": rule.get("openclaw_account_id"),
                    "content": Jsonb(content),
                    "content_snapshot_hash": content_hash,
                    "content_summary": Jsonb({"title": content["title"], "symbol": symbol, "reason": hit.get("reason")}),
                    "priority": "high" if rule.get("severity") == "critical" else "normal",
                    "dedupe_key": dedupe_key,
                    "next_retry_at": now,
                    "target_conversation": rule.get("channel_user_ref"),
                    "context_token": binding_metadata.get("context_token"),
                    "data_snapshot_refs": Jsonb([{"source": "alert_rules", "ref": rule_id}]),
                    "expires_at": now + timedelta(hours=12),
                },
            ).fetchone()

            cur.execute(
                """
                INSERT INTO public.alert_notifications (
                  tenant_id, trigger_id, channel, attempt, success, retryable, diagnostics
                )
                VALUES (
                  %(tenant_id)s, %(trigger_id)s, 'wechat', 1, false, true, %(diagnostics)s
                )
                """,
                {
                    "tenant_id": tenant_id,
                    "trigger_id": trigger_id,
                    "diagnostics": Jsonb(
                        {
                            "queued_delivery_id": str(delivery.get("id")) if delivery else None,
                            "dedupe_key": dedupe_key,
                        }
                    ),
                },
            )
        conn.commit()

    return delivery is not None


def _run_summary_cycle(database_url: str, cycle: str, limit: int, dry_run: bool) -> JsonDict:
    import psycopg
    from psycopg.rows import dict_row

    now = datetime.now(timezone.utc)
    if cycle not in {"premarket", "postmarket"}:
        return {"ok": False, "status": "skipped", "reason": "unsupported_summary_cycle", "cycle": cycle}

    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        tenants = conn.execute(
            """
            SELECT DISTINCT cb.tenant_id
            FROM public.channel_bindings cb
            WHERE cb.channel IN ('hermes_wechat', 'openclaw_wechat')
              AND cb.binding_status = 'active'
            ORDER BY cb.tenant_id
            LIMIT %(limit)s
            """,
            {"limit": limit},
        ).fetchall()

        stats = {"tenants": len(tenants), "artifacts": 0, "reviews": 0, "queued": 0, "skipped": 0}
        details: list[JsonDict] = []
        for tenant_row in tenants:
            tenant_id = str(tenant_row["tenant_id"])
            payload = _cycle_payload(conn, cycle, tenant_id, now)
            if _should_skip_cycle_message(cycle, payload):
                stats["skipped"] += 1
                details.append({"tenant_id": tenant_id, "status": "skipped", "reason": "no_relevant_commitments"})
                continue
            if dry_run:
                stats["artifacts"] += 1
                if cycle == "postmarket":
                    stats["reviews"] += len(payload["signals"])
                stats["queued"] += 1
                details.append({"tenant_id": tenant_id, "status": "dry_run", "cycle": cycle, "payload": payload})
                continue

            artifact_id = _insert_cycle_artifact(conn, tenant_id, cycle, payload, now)
            review_count = _insert_signal_reviews(conn, tenant_id, artifact_id, payload, now) if cycle == "postmarket" else 0
            queued = _queue_cycle_outbox(conn, tenant_id, artifact_id, cycle, payload, now)
            stats["artifacts"] += 1
            stats["reviews"] += review_count
            stats["queued"] += 1 if queued else 0
            details.append(
                {
                    "tenant_id": tenant_id,
                    "status": "queued" if queued else "deduped",
                    "cycle": cycle,
                    "artifact_id": str(artifact_id) if artifact_id else None,
                    "reviews": review_count,
                }
            )
        if not dry_run:
            conn.commit()

    return {"ok": True, "status": "ok", "cycle": cycle, **stats, "details": details[:20]}


def _cycle_payload(conn: Any, cycle: str, tenant_id: str, now: datetime) -> JsonDict:
    signals = conn.execute(
        """
        SELECT *
        FROM public.decision_signals
        WHERE tenant_id = %(tenant_id)s
          AND status = 'active'
          AND (expires_at IS NULL OR expires_at >= %(now)s)
        ORDER BY created_at DESC
        LIMIT 20
        """,
        {"tenant_id": tenant_id, "now": now},
    ).fetchall()
    rules = conn.execute(
        """
        SELECT *
        FROM public.alert_rules
        WHERE tenant_id = %(tenant_id)s
          AND enabled = true
          AND (expires_at IS NULL OR expires_at >= %(now)s)
        ORDER BY severity DESC, updated_at DESC
        LIMIT 50
        """,
        {"tenant_id": tenant_id, "now": now},
    ).fetchall()
    triggers = conn.execute(
        """
        SELECT at.*, ar.name AS rule_name, ar.alert_type
        FROM public.alert_triggers at
        LEFT JOIN public.alert_rules ar ON ar.id = at.rule_id
        WHERE at.tenant_id = %(tenant_id)s
          AND at.triggered_at >= %(since)s
        ORDER BY at.triggered_at DESC
        LIMIT 20
        """,
        {"tenant_id": tenant_id, "since": now - timedelta(hours=24)},
    ).fetchall()

    compact_signals = [_compact_signal(dict(row)) for row in signals]
    compact_rules = [_compact_rule(dict(row)) for row in rules]
    compact_triggers = [_compact_trigger(dict(row)) for row in triggers]
    checklist = _premarket_checklist(compact_signals, compact_rules) if cycle == "premarket" else _postmarket_checklist(compact_signals, compact_triggers)
    return {
        "schema_version": "hermes_alert_center_v1",
        "cycle": cycle,
        "tenant_id": tenant_id,
        "generated_at": now.isoformat(),
        "signals": compact_signals,
        "rules": compact_rules,
        "triggers": compact_triggers,
        "checklist": checklist,
    }


def _premarket_checklist(signals: list[JsonDict], rules: list[JsonDict]) -> list[str]:
    earnings = [rule["symbol"] for rule in rules if rule.get("alert_type") == "earnings_window"]
    expiries = [rule["symbol"] for rule in rules if rule.get("alert_type") == "sell_put_dte_delta"]
    discipline = [rule["symbol"] for rule in rules if rule.get("alert_type") == "discipline_violation"]
    items = [
        f"今日活跃承诺 {len(signals)} 条，优先检查止盈/止损/观察条件。",
        f"事件/财报窗口：{', '.join(sorted(set(earnings))) if earnings else '暂无已登记窗口'}。",
        f"期权到期/Delta：{', '.join(sorted(set(expiries))) if expiries else '暂无已登记风险'}。",
        f"纪律前置：{', '.join(sorted(set(discipline))) if discipline else '无新增阻断规则'}。",
    ]
    return items


def _postmarket_checklist(signals: list[JsonDict], triggers: list[JsonDict]) -> list[str]:
    symbols = ", ".join(sorted({str(signal.get("symbol")) for signal in signals if signal.get("symbol")}))
    triggered = ", ".join(sorted({str(trigger.get("symbol")) for trigger in triggers if trigger.get("symbol")}))
    return [
        f"复盘承诺 {len(signals)} 条：{symbols or '暂无活跃承诺'}。",
        f"过去 24 小时触发：{triggered or '暂无触发'}。",
        "请确认：是否执行、是否违反纪律、原因是什么。",
    ]


def _insert_cycle_artifact(conn: Any, tenant_id: str, cycle: str, payload: JsonDict, now: datetime) -> str | None:
    from psycopg.types.json import Jsonb

    date_key = now.strftime("%Y%m%d")
    artifact_key = f"alert-center:{cycle}:{tenant_id}:{date_key}"
    content_hash = _sha256_json(payload)
    row = conn.execute(
        """
        INSERT INTO public.artifact_registry (
          tenant_id, artifact_key, artifact_type, artifact_status, visibility,
          storage_backend, storage_path, mime_type, content_hash,
          source_lineage, artifact_metadata, retention_until
        )
        VALUES (
          %(tenant_id)s, %(artifact_key)s, %(artifact_type)s, 'ready', 'tenant',
          'postgres_json', %(storage_path)s, 'application/json', %(content_hash)s,
          %(source_lineage)s, %(artifact_metadata)s, %(retention_until)s
        )
        ON CONFLICT (tenant_id, artifact_key) DO UPDATE
        SET artifact_status = 'ready',
            content_hash = EXCLUDED.content_hash,
            artifact_metadata = EXCLUDED.artifact_metadata,
            updated_at = now()
        RETURNING id
        """,
        {
            "tenant_id": tenant_id,
            "artifact_key": artifact_key,
            "artifact_type": f"alert_center_{cycle}",
            "storage_path": f"alert-center/{tenant_id}/{date_key}/{cycle}.json",
            "content_hash": content_hash,
            "source_lineage": Jsonb([{"source": "hermes_alert_center", "cycle": cycle}]),
            "artifact_metadata": Jsonb(payload),
            "retention_until": now + timedelta(days=90),
        },
    ).fetchone()
    return row.get("id") if row else None


def _insert_signal_reviews(conn: Any, tenant_id: str, artifact_id: str | None, payload: JsonDict, now: datetime) -> int:
    from psycopg.types.json import Jsonb

    count = 0
    for signal in payload.get("signals") or []:
        signal_id = signal.get("id")
        if not signal_id:
            continue
        row = conn.execute(
            """
            INSERT INTO public.decision_signal_reviews (
              tenant_id, decision_signal_id, source_artifact_id, review_date,
              review_type, commitment_snapshot, trigger_snapshot, checklist,
              execution_status, violation_status, reason
            )
            VALUES (
              %(tenant_id)s, %(decision_signal_id)s, %(source_artifact_id)s, %(review_date)s,
              'postmarket', %(commitment_snapshot)s, %(trigger_snapshot)s, %(checklist)s,
              'pending_user_review', 'needs_reason', %(reason)s
            )
            ON CONFLICT DO NOTHING
            RETURNING id
            """,
            {
                "tenant_id": tenant_id,
                "decision_signal_id": signal_id,
                "source_artifact_id": artifact_id,
                "review_date": now.date(),
                "commitment_snapshot": Jsonb(signal),
                "trigger_snapshot": Jsonb(payload.get("triggers") or []),
                "checklist": Jsonb(payload.get("checklist") or []),
                "reason": "awaiting_user_postmarket_review",
            },
        ).fetchone()
        if row:
            count += 1
    return count


def _queue_cycle_outbox(conn: Any, tenant_id: str, artifact_id: str | None, cycle: str, payload: JsonDict, now: datetime) -> bool:
    from psycopg.types.json import Jsonb

    binding = conn.execute(
        """
        SELECT id, openclaw_account_id, channel_user_ref, binding_metadata
        FROM public.channel_bindings
        WHERE tenant_id = %(tenant_id)s
          AND channel IN ('hermes_wechat', 'openclaw_wechat')
          AND binding_status = 'active'
        ORDER BY is_primary DESC, last_seen_at DESC NULLS LAST, updated_at DESC
        LIMIT 1
        """,
        {"tenant_id": tenant_id},
    ).fetchone()
    if not binding:
        return False

    content = _cycle_message_content(cycle, payload)
    content_hash = _sha256_json(content)
    dedupe_key = f"alert-center:{cycle}:{tenant_id}:{now.strftime('%Y%m%d')}"
    binding_metadata = binding.get("binding_metadata") if isinstance(binding.get("binding_metadata"), dict) else {}
    row = conn.execute(
        """
        INSERT INTO public.delivery_outbox (
          tenant_id, channel_binding_id, artifact_id, openclaw_account_id,
          content_type, content, content_snapshot_hash, content_summary, priority,
          dedupe_key, status, attempt_count, next_retry_at, target_conversation,
          context_token, data_snapshot_refs, expires_at
        )
        VALUES (
          %(tenant_id)s, %(channel_binding_id)s, %(artifact_id)s, %(openclaw_account_id)s,
          %(content_type)s, %(content)s, %(content_snapshot_hash)s, %(content_summary)s, %(priority)s,
          %(dedupe_key)s, 'pending', 0, %(next_retry_at)s, %(target_conversation)s,
          %(context_token)s, %(data_snapshot_refs)s, %(expires_at)s
        )
        ON CONFLICT (tenant_id, dedupe_key) DO NOTHING
        RETURNING id
        """,
        {
            "tenant_id": tenant_id,
            "channel_binding_id": binding.get("id"),
            "artifact_id": artifact_id,
            "openclaw_account_id": binding.get("openclaw_account_id"),
            "content_type": f"alert_center_{cycle}",
            "content": Jsonb(content),
            "content_snapshot_hash": content_hash,
            "content_summary": Jsonb({"title": content["title"], "cycle": cycle, "items": len(payload.get("checklist") or [])}),
            "priority": "high" if cycle == "postmarket" else "normal",
            "dedupe_key": dedupe_key,
            "next_retry_at": now,
            "target_conversation": binding.get("channel_user_ref"),
            "context_token": binding_metadata.get("context_token"),
            "data_snapshot_refs": Jsonb([{"source": "artifact_registry", "ref": str(artifact_id)}] if artifact_id else []),
            "expires_at": now + timedelta(hours=18),
        },
    ).fetchone()
    return row is not None


def _should_skip_cycle_message(cycle: str, payload: JsonDict) -> bool:
    if cycle == "premarket":
        return not payload.get("signals") and not payload.get("rules")
    if cycle == "postmarket":
        return not payload.get("signals") and not payload.get("triggers")
    return False


def _cycle_message_content(cycle: str, payload: JsonDict) -> JsonDict:
    title = "盘前计划" if cycle == "premarket" else "盘后复盘"
    return {
        "title": f"Hermes {title}",
        "body": _checklist_text(payload.get("checklist") or []),
        "command_hint": "复盘今日执行" if cycle == "postmarket" else "查看今日计划",
        "cycle": cycle,
        "summary": {
            "signals": len(payload.get("signals") or []),
            "rules": len(payload.get("rules") or []),
            "triggers": len(payload.get("triggers") or []),
        },
    }


def _compact_signal(row: JsonDict) -> JsonDict:
    return {
        "id": str(row.get("id")),
        "symbol": row.get("symbol"),
        "action": row.get("action"),
        "action_label": row.get("action_label"),
        "actionability_cap": row.get("actionability_cap"),
        "stop_loss": _json_number(row.get("stop_loss")),
        "take_profit": _json_number(row.get("take_profit")),
        "watch_conditions": row.get("watch_conditions") if isinstance(row.get("watch_conditions"), list) else [],
        "risk_summary": row.get("risk_summary") if isinstance(row.get("risk_summary"), dict) else {},
        "expires_at": row.get("expires_at").isoformat() if hasattr(row.get("expires_at"), "isoformat") else row.get("expires_at"),
    }


def _compact_rule(row: JsonDict) -> JsonDict:
    return {
        "id": str(row.get("id")),
        "symbol": row.get("target_symbol"),
        "alert_type": row.get("alert_type"),
        "severity": row.get("severity"),
        "parameters": row.get("parameters") if isinstance(row.get("parameters"), dict) else {},
        "cooldown_policy": row.get("cooldown_policy") if isinstance(row.get("cooldown_policy"), dict) else {},
        "expires_at": row.get("expires_at").isoformat() if hasattr(row.get("expires_at"), "isoformat") else row.get("expires_at"),
    }


def _compact_trigger(row: JsonDict) -> JsonDict:
    return {
        "id": str(row.get("id")),
        "symbol": row.get("target_symbol"),
        "alert_type": row.get("alert_type"),
        "reason": row.get("reason"),
        "triggered_at": row.get("triggered_at").isoformat() if hasattr(row.get("triggered_at"), "isoformat") else row.get("triggered_at"),
    }


def _discipline_actionability(parameters: JsonDict) -> str:
    explicit = str(parameters.get("actionability_cap") or parameters.get("action_cap") or "").lower()
    if explicit in {"blocked", "analysis_only"}:
        return explicit
    violations = parameters.get("violations")
    if isinstance(violations, list) and violations:
        severities = {str(item.get("severity") or "").lower() for item in violations if isinstance(item, dict)}
        if "critical" in severities or "blocked" in severities:
            return "blocked"
        return "analysis_only"
    if parameters.get("blocked") is True:
        return "blocked"
    if parameters.get("analysis_only") is True:
        return "analysis_only"
    return "actionable"


def _checklist_text(items: list[Any]) -> str:
    if not items:
        return "暂无需要处理的提醒。"
    return "\n".join(f"{idx}. {str(item)}" for idx, item in enumerate(items, start=1))


def _json_number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _alert_message_content(rule: JsonDict, quote: JsonDict, hit: JsonDict) -> JsonDict:
    symbol = str(rule.get("target_symbol") or "")
    condition = (rule.get("parameters") or {}).get("condition") if isinstance(rule.get("parameters"), dict) else None
    price = hit.get("current_price") or _first_number(quote, "price", "last_price", "current_price", "close")
    reason = str(hit.get("reason") or "alert_triggered")
    title = f"{symbol} 观察提醒"
    body_parts = [
        f"触发原因：{_reason_label(reason)}。",
        f"当前价格：{price}。" if price is not None else None,
        f"观察条件：{condition}" if condition else None,
        "这只是观察提醒，不是交易指令。",
    ]
    return {
        "title": title,
        "body": "\n".join(part for part in body_parts if part),
        "command_hint": f"复核 {symbol}",
        "symbol": symbol,
        "reason": reason,
    }


def _alert_dedupe_key(rule: JsonDict, now: datetime, hit: JsonDict) -> str:
    date_key = now.strftime("%Y%m%d")
    return f"alert:{rule.get('id')}:{date_key}:{hit.get('reason') or 'triggered'}"


def _stats(stats: AlertEvaluationStats, **delta: int) -> AlertEvaluationStats:
    values = stats.model_dump()
    for key, amount in delta.items():
        values[key] += amount
    return AlertEvaluationStats(**values)


def _hit(reason: str, **extra: Any) -> JsonDict:
    return {"triggered": True, "reason": reason, **extra}


def _payload_data(payload: JsonDict) -> JsonDict:
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    if isinstance(data, dict):
        nested = data.get("data")
        if isinstance(nested, dict):
            return nested
        return data
    return payload if payload.get("ok") is not False else {}


def _first_number(payload: JsonDict, *keys: str) -> float | None:
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _cooldown_hours(policy: Any) -> int:
    if not isinstance(policy, dict):
        return 18
    try:
        return max(1, min(168, int(policy.get("cooldown_hours") or 18)))
    except (TypeError, ValueError):
        return 18


def _reason_label(reason: str) -> str:
    labels = {
        "price_move_from_analysis_reference": "价格较分析参考价发生明显变化",
        "review_due": "到了复核时间",
        "price_cross_above": "价格上穿观察线",
        "price_cross_below": "价格下破观察线",
    }
    return labels.get(reason, reason)


def _sha256_json(payload: JsonDict) -> str:
    raw = json.dumps(payload, ensure_ascii=True, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
