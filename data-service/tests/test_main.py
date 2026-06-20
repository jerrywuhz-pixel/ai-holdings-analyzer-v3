import asyncio

from fastapi.testclient import TestClient

from routers import hermes
from main import app

client = TestClient(app)


class FakeDomainTools:
    def __init__(self):
        self.calls = []

    async def invoke(self, tool_name, arguments):
        self.calls.append((tool_name, arguments))
        if tool_name == "market.quote":
            return {
                "tool": "market.quote",
                "ok": True,
                "status": "ok",
                "data": {
                    "symbol": arguments["symbol"],
                    "name": "NVIDIA",
                    "price": 123.45,
                    "currency": "USD",
                    "source": "test",
                },
                "source_refs": [{"source": "hermes-data-service", "ref": "/api/quote/NVDA"}],
            }
        if tool_name == "broker.positions_read":
            return {
                "tool": "broker.positions_read",
                "ok": True,
                "status": "ok",
                "data": {
                    "equity_positions": [{"symbol": "NVDA"}, {"symbol": "TSLA"}],
                    "option_positions": [{"symbol": "NVDA260619P100"}],
                    "source_quality": "user_confirmed",
                },
                "source_refs": [{"source": "hermes-data-service", "ref": "/api/v3/portfolio/positions"}],
            }
        if tool_name == "portfolio.overview":
            return {
                "tool": "portfolio.overview",
                "ok": True,
                "status": "ok",
                "data": {
                    "base_total_value": 250000,
                    "base_gross_market_value": 210000,
                    "base_cash": 40000,
                    "base_buying_power": 80000,
                    "base_cash_secured_requirement": 12000,
                    "base_currency": "USD",
                    "positions_count": 3,
                    "equity_count": 2,
                    "option_count": 1,
                    "source_quality": "user_confirmed",
                    "freshness": {
                        "status": "partial",
                        "as_of": "2026-06-17T05:00:00+00:00",
                        "as_of_age_seconds": 600,
                        "received_age_seconds": 120,
                        "missing_fields": ["cash_balances"],
                    },
                },
                "source_refs": [{"source": "hermes-data-service", "ref": "/api/v3/portfolio/overview"}],
            }
        if tool_name == "stock.analysis":
            return {
                "tool": "stock.analysis",
                "ok": True,
                "status": "ok",
                "data": {
                    "schema_version": "stock_analysis_p1",
                    "symbol": arguments["symbol"],
                    "name": "NVIDIA",
                    "market": "US",
                    "action": "review_position",
                    "action_label": "复核持仓",
                    "actionability_cap": "analysis_only",
                    "score": 60,
                    "short_reply": "NVIDIA（NVDA）当前结论：复核持仓。\n数据质量：只能观察 / 数据新鲜 / 无持仓上下文 / 来源 test。\n行动等级：analysis_only / 复核持仓。\n下一步：观察价格是否有效突破或跌破 123.45 附近",
                    "quality_display": {
                        "schema_version": "quality_display_v1",
                        "source": "test",
                        "as_of": "2026-06-17T05:00:00+00:00",
                        "freshness": "fresh",
                        "freshness_label": "数据新鲜",
                        "actionability": "analysis_only",
                        "actionability_label": "只能观察",
                        "degrade_reason": "no_position_context",
                        "degrade_reason_label": "无持仓上下文",
                        "summary": "只能观察 / 数据新鲜 / 无持仓上下文 / 来源 test",
                    },
                    "data_quality": {"quote_source": "test", "portfolio_context": "not_held_or_unavailable"},
                    "report": {
                        "conclusion": "NVIDIA（NVDA）当前结论：复核持仓。",
                        "position": "当前匹配到持仓：数量 10，成本 100 USD，浮盈亏 20%。",
                        "market": "最新价 123.45 USD，数据源 test。",
                        "risk": "持仓浮盈超过 20%，需要复核止盈计划",
                        "discipline": "本报告只生成分析和观察条件，不写入持仓事实，不下券商订单。",
                        "next_steps": "观察价格是否有效突破或跌破 123.45 附近",
                    },
                    "report_constraints": {"conclusion_first": True, "module_max_chars": 200},
                    "persistence": {"status": "skipped", "reason": "tenant_id_is_not_uuid"},
                },
                "source_refs": [{"source": "hermes-data-service", "ref": "/api/quote/NVDA"}],
            }
        if tool_name == "reference.web.read":
            return {
                "tool": "reference.web.read",
                "ok": True,
                "status": "ok",
                "data": {
                    "schema_version": "web_reference_tool_result_v1",
                    "reference_only": True,
                    "summary": {
                        "schema_version": "web_reference_summary_v1",
                        "reference_only": True,
                        "title": "NVDA supply chain note",
                        "url": arguments["url"],
                        "content_hash": "hash-1",
                        "status": "ok",
                        "fetched_at": "2026-06-17T06:00:00+00:00",
                        "summary": "NVIDIA demand remains strong, but the article says this is a reference-only market note.",
                        "source_refs": [{"source": "web", "ref": arguments["url"]}],
                    },
                    "persistence": {"status": "saved", "backend": "test", "artifact_id": "artifact-web-1"},
                    "audit": {"entry_surface": arguments.get("entry_surface"), "prompt": arguments.get("prompt")},
                },
                "source_refs": [{"source": "web", "ref": arguments["url"]}],
            }
        if tool_name == "reference.web.search":
            return {
                "tool": "reference.web.search",
                "ok": True,
                "status": "ok",
                "data": {
                    "schema_version": "web_reference_search_result_v1",
                    "reference_only": True,
                    "query": arguments["query"],
                    "provider": "searxng",
                    "items": [
                        {
                            "title": "NVDA latest news",
                            "url": "https://example.com/nvda-news",
                            "snippet": "NVIDIA data center demand remains a key market focus.",
                            "source": "test-search",
                            "reference_only": True,
                        }
                    ],
                    "read_result": {
                        "tool": "reference.web.read",
                        "ok": True,
                        "status": "ok",
                        "data": {
                            "schema_version": "web_reference_tool_result_v1",
                            "reference_only": True,
                            "summary": {
                                "schema_version": "web_reference_summary_v1",
                                "reference_only": True,
                                "title": "NVDA latest news",
                                "url": "https://example.com/nvda-news",
                                "content_hash": "hash-search-1",
                                "status": "ok",
                                "fetched_at": "2026-06-18T06:00:00+00:00",
                                "summary": "NVIDIA data center demand remains strong according to this reference-only public page.",
                                "source_refs": [{"source": "web", "ref": "https://example.com/nvda-news"}],
                            },
                            "persistence": {"status": "saved", "backend": "test", "artifact_id": "artifact-web-search-1"},
                        },
                        "source_refs": [{"source": "web", "ref": "https://example.com/nvda-news"}],
                    },
                    "audit": {"entry_surface": arguments.get("entry_surface"), "prompt": arguments.get("prompt")},
                },
                "source_refs": [
                    {"source": "reference-search", "ref": "searxng"},
                    {"source": "web", "ref": "https://example.com/nvda-news"},
                ],
            }
        if tool_name == "sentiment.social.snapshot":
            return {
                "tool": "sentiment.social.snapshot",
                "ok": True,
                "status": "available",
                "data": {
                    "schema_version": "social_sentiment_tool_result_v1",
                    "reference_only": True,
                    "social_context": {
                        "schema_version": "social_sentiment_snapshot_v1",
                        "status": "available",
                        "symbol": arguments["symbol"],
                        "window": "72h",
                        "sentiment": {"label": "bullish", "score": 0.5, "confidence": "medium"},
                        "summary": "Watched social accounts lean bullish.",
                        "items": [
                            {
                                "platform": "xueqiu",
                                "account_id": "long-ai",
                                "text": "NVDA demand remains strong among watched accounts.",
                                "sentiment": "bullish",
                            }
                        ],
                        "accounts": [{"platform": "xueqiu", "handle": "long-ai"}],
                        "themes": [{"label": "demand", "stance": "bullish", "evidence_count": 1}],
                        "risk_flags": [],
                    },
                    "audit": {"scope": "finite_accounts_only", "global_search_enabled": False},
                },
                "source_refs": [{"source": "xueqiu", "ref": "long-ai"}],
            }
        return {"tool": tool_name, "ok": False, "status": "error", "error": "unexpected tool", "source_refs": []}


class FakeFailingReferenceTools(FakeDomainTools):
    async def invoke(self, tool_name, arguments):
        self.calls.append((tool_name, arguments))
        if tool_name == "reference.web.read":
            return {
                "tool": "reference.web.read",
                "ok": False,
                "status": "empty_content",
                "data": {
                    "schema_version": "web_reference_tool_result_v1",
                    "reference_only": True,
                    "summary": {
                        "schema_version": "web_reference_summary_v1",
                        "reference_only": True,
                        "title": None,
                        "url": arguments["url"],
                        "content_hash": "failed123",
                        "status": "empty_content",
                        "summary": "",
                        "failed": {
                            "reason": "empty_content",
                            "message": "Reference capture returned no readable content.",
                        },
                        "source_refs": [{"source": "web", "ref": arguments["url"]}],
                    },
                    "persistence": {
                        "status": "saved",
                        "backend": "postgres",
                        "artifact_id": "artifact-failed",
                        "artifact_status": "failed",
                    },
                    "audit": {
                        "entry_surface": arguments.get("entry_surface"),
                        "prompt": arguments.get("prompt"),
                        "failed": {
                            "reason": "empty_content",
                            "message": "Reference capture returned no readable content.",
                        },
                    },
                },
                "failed": {
                    "reason": "empty_content",
                    "message": "Reference capture returned no readable content.",
                },
                "source_refs": [{"source": "web", "ref": arguments["url"]}],
            }
        return await super().invoke(tool_name, arguments)


class FakeSlowReferenceTools(FakeDomainTools):
    async def invoke(self, tool_name, arguments):
        self.calls.append((tool_name, arguments))
        if tool_name == "reference.web.read":
            await asyncio.sleep(0.2)
            return await FakeDomainTools().invoke(tool_name, arguments)
        return await super().invoke(tool_name, arguments)


class FakeImaArchiveService:
    calls = []

    @classmethod
    def from_env(cls):
        return cls()

    async def archive(self, **kwargs):
        self.calls.append(kwargs)
        return {"status": "saved", "path": "/tmp/test.md"}


class FakeStockPersistence:
    calls = []

    @classmethod
    def from_env(cls):
        return cls()

    async def save(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "status": "saved",
            "backend": "test",
            "agent_run_id": "run-1",
            "artifact_id": "artifact-1",
            "decision_signal_id": "signal-1",
        }


class FakeWatchlistService:
    calls = []

    @classmethod
    def from_env(cls):
        return cls()

    async def add_watch(self, **kwargs):
        self.calls.append(("add_watch", kwargs))
        return {
            "status": "saved",
            "follow_view_item_id": "follow-1",
            "alert_rule_ids": ["alert-1"],
            "symbol": kwargs["symbol"],
        }

    async def list_watch(self, **kwargs):
        self.calls.append(("list_watch", kwargs))
        return {
            "status": "ok",
            "items": [
                {
                    "symbol": "INTC",
                    "thesis": "关注 INTC，跌破 31 提醒我",
                    "next_review_at": "2026-06-17T00:00:00+00:00",
                }
            ],
        }

    async def archive_watch(self, **kwargs):
        self.calls.append(("archive_watch", kwargs))
        return {"status": "archived", "symbol": kwargs["symbol"]}


def test_health_returns_ok_and_version():
    """GET /health 返回增强版响应，包含 status、version、gateway 和 data_sources。"""
    response = client.get("/health")
    assert response.status_code == 200, "Health endpoint should return 200"
    data = response.json()
    assert data["status"] == "ok"
    assert data["version"] == "3.0.0-p0"
    assert data["runtime"] == "hermes"
    # Phase 8 增强字段
    assert "gateway" in data
    assert "data_sources" in data


def test_hermes_domain_tools_manifest_is_served_by_data_service(monkeypatch):
    monkeypatch.delenv("HERMES_DOMAIN_TOOLS_KEY", raising=False)
    monkeypatch.delenv("HERMES_INTERNAL_TOKEN", raising=False)
    response = client.get("/api/hermes/domain-tools")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["runtime"] == "hermes"
    assert any(tool["name"] == "market.quote" for tool in data["tools"])
    assert any(tool["name"] == "sector.context" for tool in data["tools"])
    assert any(tool["name"] == "market.regime" for tool in data["tools"])
    assert any(tool["name"] == "portfolio.overview" for tool in data["tools"])
    assert any(tool["name"] == "stock.analysis" for tool in data["tools"])
    assert any(tool["name"] == "reference.web.read" for tool in data["tools"])
    assert any(tool["name"] == "reference.web.search" for tool in data["tools"])
    assert any(tool["name"] == "reference.social.watchlist" for tool in data["tools"])
    assert any(tool["name"] == "reference.social.timeline" for tool in data["tools"])
    assert any(tool["name"] == "sentiment.social.snapshot" for tool in data["tools"])


def test_hermes_wechat_ingress_default_reply_is_hermes_runtime(monkeypatch):
    monkeypatch.delenv("HERMES_DOMAIN_TOOLS_KEY", raising=False)
    monkeypatch.delenv("HERMES_INTERNAL_TOKEN", raising=False)
    response = client.post(
        "/api/hermes/wechat/messages",
        json={
            "routing": {
                "tenant_id": "tenant-test",
                "channel": "hermes_wechat",
                "channel_account_id": "wechat-test",
            },
            "message": {
                "type": "text",
                "text": "你好",
            },
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["runtime"] == "hermes"
    assert data["result_type"] == "hermes_reply"
    assert "Hermes" in data["reply_text"]


def test_hermes_wechat_ingress_requires_internal_key_when_configured(monkeypatch):
    monkeypatch.setenv("HERMES_INTERNAL_TOKEN", "test-secret")

    response = client.post(
        "/api/hermes/wechat/messages",
        json={
            "routing": {"tenant_id": "tenant-test", "channel": "hermes_wechat"},
            "message": {"type": "text", "text": "你好"},
        },
    )

    assert response.status_code == 401


def test_hermes_wechat_quote_intent_uses_domain_tool(monkeypatch):
    fake_tools = FakeDomainTools()
    monkeypatch.setenv("HERMES_INTERNAL_TOKEN", "test-secret")
    monkeypatch.setattr(hermes, "_domain_tools_facade", fake_tools)

    response = client.post(
        "/api/hermes/wechat/messages",
        headers={"X-Hermes-Internal-Token": "test-secret"},
        json={
            "routing": {
                "tenant_id": "tenant-test",
                "channel": "hermes_wechat",
                "channel_account_id": "wechat-test",
            },
            "message": {"type": "text", "text": "NVDA 行情"},
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["result_type"] == "market_quote"
    assert data["intent"] == {"name": "market_quote", "symbol": "NVDA"}
    assert "NVIDIA" in data["reply_text"]
    assert data["tool_calls"][0]["tool"] == "market.quote"
    assert fake_tools.calls == [("market.quote", {"symbol": "NVDA", "tenant_id": "tenant-test"})]


def test_hermes_wechat_reply_schedules_ima_archive(monkeypatch):
    fake_tools = FakeDomainTools()
    FakeImaArchiveService.calls = []
    monkeypatch.setenv("HERMES_INTERNAL_TOKEN", "test-secret")
    monkeypatch.setattr(hermes, "_domain_tools_facade", fake_tools)
    monkeypatch.setattr(hermes, "HermesImaArchiveService", FakeImaArchiveService)

    response = client.post(
        "/api/hermes/wechat/messages",
        headers={"X-Hermes-Internal-Token": "test-secret"},
        json={
            "routing": {"tenant_id": "tenant-test", "channel": "hermes_wechat"},
            "message": {"id": "msg-archive", "type": "text", "text": "NVDA 行情"},
        },
    )

    assert response.status_code == 200
    assert FakeImaArchiveService.calls
    call = FakeImaArchiveService.calls[0]
    assert call["source"] == "wechat_user_reply"
    assert call["prompt"] == "NVDA 行情"
    assert call["result_type"] == "market_quote"
    assert "NVIDIA" in call["content_markdown"]
    assert call["metadata"]["message_id"] == "msg-archive"


def test_hermes_wechat_positions_intent_uses_domain_tool(monkeypatch):
    fake_tools = FakeDomainTools()
    monkeypatch.setenv("HERMES_INTERNAL_TOKEN", "test-secret")
    monkeypatch.setattr(hermes, "_domain_tools_facade", fake_tools)

    response = client.post(
        "/api/hermes/wechat/messages",
        headers={"X-Hermes-Domain-Tools-Key": "test-secret"},
        json={
            "routing": {"tenant_id": "tenant-test", "channel": "hermes_wechat"},
            "message": {"type": "text", "text": "我的持仓怎么样"},
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["result_type"] == "portfolio_analysis"
    assert data["portfolio_analysis"]["total"] == 3
    assert data["portfolio_analysis"]["equities"] == 2
    assert data["portfolio_analysis"]["options"] == 1
    assert data["portfolio_analysis"]["freshness"]["status"] == "partial"
    assert data["portfolio_analysis"]["overview"]["base_total_value"] == 250000
    assert "总资产 250,000.00 USD" in data["reply_text"]
    assert "现金 40,000.00 USD" in data["reply_text"]
    assert "NVDA" in data["reply_text"]
    assert fake_tools.calls == [
        ("portfolio.overview", {"tenant_id": "tenant-test"}),
        ("broker.positions_read", {"tenant_id": "tenant-test", "source": "portfolio_read_model"})
    ]


def test_hermes_wechat_trace_endpoint_returns_structured_trace(monkeypatch):
    monkeypatch.setenv("HERMES_INTERNAL_TOKEN", "test-secret")
    monkeypatch.setattr(
        hermes,
        "_build_wechat_trace",
        lambda payload: {
            "trace_status": "BOUND_NO_RECEIPT",
            "db_available": True,
            "input": {"tenant_id": payload.tenant_id},
            "stages": [
                {"name": "binding", "status": "pass", "detail": "1 matching row", "rows": []},
                {"name": "bridge_receipt", "status": "gap", "detail": "0 rows", "rows": []},
            ],
        },
    )

    response = client.post(
        "/api/hermes/wechat/trace",
        headers={"X-Hermes-Internal-Token": "test-secret"},
        json={"tenant_id": "tenant-test", "window_minutes": 60},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["result_type"] == "wechat_trace"
    assert data["trace_status"] == "BOUND_NO_RECEIPT"
    assert data["stages"][0]["name"] == "binding"


def test_hermes_wechat_stock_analysis_intent_uses_domain_tool(monkeypatch):
    fake_tools = FakeDomainTools()
    monkeypatch.setenv("HERMES_INTERNAL_TOKEN", "test-secret")
    monkeypatch.setattr(hermes, "_domain_tools_facade", fake_tools)

    response = client.post(
        "/api/hermes/wechat/messages",
        headers={"X-Hermes-Internal-Token": "test-secret"},
        json={
            "routing": {"tenant_id": "tenant-test", "channel": "hermes_wechat"},
            "message": {"type": "text", "text": "NVDA 怎么看"},
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["result_type"] == "stock_analysis"
    assert data["intent"] == {"name": "stock_analysis", "symbol": "NVDA"}
    assert data["analysis"]["report_constraints"] == {"conclusion_first": True, "module_max_chars": 200}
    assert "复核持仓" in data["reply_text"]
    assert "数据质量：" in data["reply_text"]
    assert data["analysis"]["quality_display"]["source"] == "test"
    assert data["analysis"]["quality_display"]["degrade_reason"] == "no_position_context"
    assert fake_tools.calls == [
        (
            "stock.analysis",
            {
                "symbol": "NVDA",
                "tenant_id": "tenant-test",
                "prompt": "NVDA 怎么看",
                "entry_surface": "wechat",
            },
        )
    ]


def test_hermes_wechat_url_intent_reads_reference_only(monkeypatch):
    fake_tools = FakeDomainTools()
    monkeypatch.setenv("HERMES_INTERNAL_TOKEN", "test-secret")
    monkeypatch.setattr(hermes, "_domain_tools_facade", fake_tools)

    response = client.post(
        "/api/hermes/wechat/messages",
        headers={"X-Hermes-Internal-Token": "test-secret"},
        json={
            "routing": {"tenant_id": "tenant-test", "channel": "hermes_wechat"},
            "message": {"type": "text", "text": "总结一下 https://example.com/nvda-note"},
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["result_type"] == "web_reference"
    assert data["intent"] == {"name": "web_reference_read", "url": "https://example.com/nvda-note"}
    assert data["reference_summary"]["reference_only"] is True
    assert data["persistence"]["status"] == "saved"
    assert "参考资料" in data["reply_text"]
    assert "reference_only" not in data["reply_text"]
    assert fake_tools.calls == [
        (
            "reference.web.read",
            {
                "url": "https://example.com/nvda-note",
                "tenant_id": "tenant-test",
                "prompt": "总结一下 https://example.com/nvda-note",
                "entry_surface": "wechat",
            },
        )
    ]


def test_hermes_wechat_reference_timeout_queues_async_delivery(monkeypatch):
    fake_tools = FakeSlowReferenceTools()
    queued = []
    monkeypatch.setenv("HERMES_INTERNAL_TOKEN", "test-secret")
    monkeypatch.setenv("HERMES_REFERENCE_ASYNC_ENABLED", "true")
    monkeypatch.setenv("HERMES_REFERENCE_ASYNC_THRESHOLD_SECONDS", "0.1")
    monkeypatch.delenv("HERMES_REFERENCE_ASYNC_DELIVER_IMMEDIATELY", raising=False)
    monkeypatch.setattr(hermes, "_domain_tools_facade", fake_tools)
    monkeypatch.setattr(
        hermes,
        "_queue_reference_delivery_sync",
        lambda routing, prompt, content_type, result: queued.append(
            {
                "routing": routing,
                "prompt": prompt,
                "content_type": content_type,
                "result": result,
            }
        )
        or {"status": "queued", "delivery_id": "delivery-1"},
    )

    response = client.post(
        "/api/hermes/wechat/messages",
        headers={"X-Hermes-Internal-Token": "test-secret"},
        json={
            "routing": {
                "tenant_id": "tenant-test",
                "channel": "hermes_wechat",
                "channel_binding_id": "binding-test",
            },
            "message": {"type": "text", "text": "总结一下 https://example.com/slow-note"},
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["result_type"] == "web_reference_reading"
    assert "正在读取" in data["reply_text"]
    assert data["async_delivery"]["content_type"] == "web_reference_result"
    assert queued[0]["content_type"] == "web_reference_result"
    assert queued[0]["routing"]["channel_binding_id"] == "binding-test"
    assert queued[0]["result"]["result_type"] == "web_reference"
    assert len(fake_tools.calls) == 2


def test_hermes_wechat_url_failure_preserves_failed_snapshot(monkeypatch):
    fake_tools = FakeFailingReferenceTools()
    monkeypatch.setenv("HERMES_INTERNAL_TOKEN", "test-secret")
    monkeypatch.setattr(hermes, "_domain_tools_facade", fake_tools)

    response = client.post(
        "/api/hermes/wechat/messages",
        headers={"X-Hermes-Internal-Token": "test-secret"},
        json={
            "routing": {"tenant_id": "tenant-test", "channel": "hermes_wechat"},
            "message": {"type": "text", "text": "读一下 https://example.com/blocked"},
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["result_type"] == "web_reference_error"
    assert data["intent"] == {"name": "web_reference_read", "url": "https://example.com/blocked"}
    assert "这个链接暂时读不到" in data["reply_text"]
    assert "Reference capture returned no readable content" not in data["reply_text"]
    assert data["reference_summary"]["failed"]["reason"] == "empty_content"
    assert data["internal_failure"]["reason"] == "empty_content"
    assert data["persistence"]["artifact_status"] == "failed"
    assert data["safety"] == {"mode": "reference_only", "writes_fact_store": True, "places_orders": False}
    assert fake_tools.calls[0][0] == "reference.web.read"


def test_hermes_wechat_url_stock_analysis_injects_news_context(monkeypatch):
    fake_tools = FakeDomainTools()
    monkeypatch.setenv("HERMES_INTERNAL_TOKEN", "test-secret")
    monkeypatch.setattr(hermes, "_domain_tools_facade", fake_tools)

    response = client.post(
        "/api/hermes/wechat/messages",
        headers={"X-Hermes-Internal-Token": "test-secret"},
        json={
            "routing": {"tenant_id": "tenant-test", "channel": "hermes_wechat"},
            "message": {"type": "text", "text": "结合这篇文章分析 NVDA 怎么看 https://example.com/nvda-note"},
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["result_type"] == "stock_analysis"
    assert "参考资料" in data["reply_text"]
    assert "reference_only" not in data["reply_text"]
    assert fake_tools.calls[0] == (
        "reference.web.read",
        {
            "url": "https://example.com/nvda-note",
            "tenant_id": "tenant-test",
            "prompt": "结合这篇文章分析 NVDA 怎么看 https://example.com/nvda-note",
            "entry_surface": "wechat",
        },
    )
    tool_name, arguments = fake_tools.calls[1]
    assert tool_name == "stock.analysis"
    assert arguments["symbol"] == "NVDA"
    assert arguments["news_context"]["schema_version"] == "web_reference_news_context_v1"
    assert arguments["news_context"]["items"][0]["url"] == "https://example.com/nvda-note"
    assert arguments["news_context"]["items"][0]["summary"].startswith("NVIDIA demand")


def test_hermes_wechat_search_intent_reads_top_reference(monkeypatch):
    fake_tools = FakeDomainTools()
    monkeypatch.setenv("HERMES_INTERNAL_TOKEN", "test-secret")
    monkeypatch.setattr(hermes, "_domain_tools_facade", fake_tools)

    response = client.post(
        "/api/hermes/wechat/messages",
        headers={"X-Hermes-Internal-Token": "test-secret"},
        json={
            "routing": {"tenant_id": "tenant-test", "channel": "hermes_wechat"},
            "message": {"type": "text", "text": "搜索一下 NVDA 最新新闻"},
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["result_type"] == "web_reference_search"
    assert data["intent"] == {"name": "web_reference_search", "query": "NVDA 最新新闻"}
    assert data["search_results"][0]["url"] == "https://example.com/nvda-news"
    assert data["reference_summary"]["reference_only"] is True
    assert "参考资料" in data["reply_text"]
    assert "reference_only" not in data["reply_text"]
    assert fake_tools.calls == [
        (
            "reference.web.search",
            {
                "query": "NVDA 最新新闻",
                "tenant_id": "tenant-test",
                "prompt": "搜索一下 NVDA 最新新闻",
                "entry_surface": "wechat",
                "limit": 5,
                "read_top": True,
            },
        )
    ]


def test_hermes_wechat_search_stock_analysis_injects_news_context(monkeypatch):
    fake_tools = FakeDomainTools()
    monkeypatch.setenv("HERMES_INTERNAL_TOKEN", "test-secret")
    monkeypatch.setattr(hermes, "_domain_tools_facade", fake_tools)

    response = client.post(
        "/api/hermes/wechat/messages",
        headers={"X-Hermes-Internal-Token": "test-secret"},
        json={
            "routing": {"tenant_id": "tenant-test", "channel": "hermes_wechat"},
            "message": {"type": "text", "text": "搜索 NVDA 最新新闻并分析"},
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["result_type"] == "stock_analysis"
    assert "搜索到的公开网页资料" in data["reply_text"]
    assert fake_tools.calls[0][0] == "reference.web.search"
    assert fake_tools.calls[0][1]["query"] == "NVDA 最新新闻"
    tool_name, arguments = fake_tools.calls[1]
    assert tool_name == "stock.analysis"
    assert arguments["symbol"] == "NVDA"
    assert arguments["news_context"]["schema_version"] == "web_reference_search_news_context_v1"
    assert arguments["news_context"]["items"][0]["url"] == "https://example.com/nvda-news"
    assert arguments["news_context"]["items"][0]["summary"].startswith("NVIDIA data center")


def test_hermes_wechat_social_stock_analysis_injects_social_context(monkeypatch):
    fake_tools = FakeDomainTools()
    monkeypatch.setenv("HERMES_INTERNAL_TOKEN", "test-secret")
    monkeypatch.setattr(hermes, "_domain_tools_facade", fake_tools)

    response = client.post(
        "/api/hermes/wechat/messages",
        headers={"X-Hermes-Internal-Token": "test-secret"},
        json={
            "routing": {"tenant_id": "tenant-test", "channel": "hermes_wechat"},
            "message": {"type": "text", "text": "社区里大家怎么看 NVDA，帮我分析"},
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["result_type"] == "stock_analysis"
    assert "有限账号清单" in data["reply_text"]
    assert fake_tools.calls[0][0] == "sentiment.social.snapshot"
    assert fake_tools.calls[0][1]["symbol"] == "NVDA"
    tool_name, arguments = fake_tools.calls[1]
    assert tool_name == "stock.analysis"
    assert arguments["symbol"] == "NVDA"
    assert arguments["social_context"]["schema_version"] == "social_sentiment_snapshot_v1"
    assert arguments["social_context"]["items"][0]["account_id"] == "long-ai"


def test_hermes_reply_sanitizes_internal_runtime_status():
    data = hermes._reply(
        "runtime_status",
        "Compacting context — summarizing earlier conversation so I can continue...\nPreflight compression: 139677 tokens",
    )

    assert data["reply_text"] == "系统处理暂时受阻，请稍后重试。当前没有改动持仓，也不会下单。"


def test_hermes_tool_error_reply_hides_raw_exception():
    data = hermes._tool_error_reply(
        "market_quote_error",
        "NVDA 行情暂时不可用",
        {
            "tool": "market.quote",
            "ok": False,
            "status": "upstream_error",
            "error": "HTTPStatusError: 503 Service Unavailable for url https://internal/provider",
            "source_refs": [],
        },
        intent={"name": "market_quote", "symbol": "NVDA"},
    )

    assert "NVDA 行情暂时不可用，请稍后重试" in data["reply_text"]
    assert "HTTPStatusError" not in data["reply_text"]
    assert "provider" not in data["reply_text"]
    assert data["internal_failure"]["status"] == "upstream_error"


def test_hermes_wechat_search_analysis_query_prefers_company_topic(monkeypatch):
    fake_tools = FakeDomainTools()
    monkeypatch.setenv("HERMES_INTERNAL_TOKEN", "test-secret")
    monkeypatch.setattr(hermes, "_domain_tools_facade", fake_tools)

    response = client.post(
        "/api/hermes/wechat/messages",
        headers={"X-Hermes-Internal-Token": "test-secret"},
        json={
            "routing": {"tenant_id": "tenant-test", "channel": "hermes_wechat"},
            "message": {"type": "text", "text": "分析 NVDA 搜索一下 NVIDIA latest news"},
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["result_type"] == "stock_analysis"
    assert fake_tools.calls[0][0] == "reference.web.search"
    assert fake_tools.calls[0][1]["query"] == "NVIDIA latest news"


def test_hermes_wechat_xiaohongshu_share_link_strips_copy_suffix(monkeypatch):
    fake_tools = FakeDomainTools()
    monkeypatch.setenv("HERMES_INTERNAL_TOKEN", "test-secret")
    monkeypatch.setattr(hermes, "_domain_tools_facade", fake_tools)

    response = client.post(
        "/api/hermes/wechat/messages",
        headers={"X-Hermes-Internal-Token": "test-secret"},
        json={
            "routing": {"tenant_id": "tenant-test", "channel": "hermes_wechat"},
            "message": {
                "type": "text",
                "text": "52 NVIDIA芯片观察 https://xhslink.com/a/abc123，复制本条信息打开小红书",
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["result_type"] == "web_reference"
    assert data["intent"] == {"name": "web_reference_read", "url": "https://xhslink.com/a/abc123"}
    assert fake_tools.calls[0] == (
        "reference.web.read",
        {
            "url": "https://xhslink.com/a/abc123",
            "tenant_id": "tenant-test",
            "prompt": "52 NVIDIA芯片观察 https://xhslink.com/a/abc123，复制本条信息打开小红书",
            "entry_surface": "wechat",
        },
    )


def test_hermes_wechat_analysis_artifact_persists_external_result(monkeypatch):
    FakeStockPersistence.calls = []
    monkeypatch.setenv("HERMES_INTERNAL_TOKEN", "test-secret")
    monkeypatch.setattr(hermes, "StockAnalysisPersistence", FakeStockPersistence)

    response = client.post(
        "/api/hermes/wechat/analysis-artifacts",
        headers={"X-Hermes-Internal-Token": "test-secret"},
        json={
            "routing": {"tenant_id": "00000000-0000-0000-0000-000000000000", "channel": "hermes_wechat"},
            "message": {"id": "msg-1", "type": "text", "text": "分析一下 circle"},
            "reply_text": "行动等级：analysis_only\n你说的 Circle，我按 CRCL.US / Circle Internet Group 分析。\n数据源：Longbridge",
            "hermes_result": {"ok": True, "runtime": "hermes"},
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "CRCL"
    assert data["persistence"]["status"] == "saved"
    assert len(FakeStockPersistence.calls) == 1
    call = FakeStockPersistence.calls[0]
    assert call["symbol"] == "CRCL"
    assert call["entry_surface"] == "wechat"
    assert call["analysis"]["symbol"] == "CRCL"
    assert call["analysis"]["actionability_cap"] == "analysis_only"
    assert call["analysis"]["quality_display"]["schema_version"] == "quality_display_v1"
    assert call["analysis"]["quality_display"]["source"] == "hermes_wechat_result"
    assert call["analysis"]["quality_display"]["actionability_label"] == "只能观察"
    assert call["analysis"]["report"]["market"] == "数据源：Longbridge"


def test_hermes_wechat_watch_command_updates_watchlist(monkeypatch):
    FakeWatchlistService.calls = []
    monkeypatch.setenv("HERMES_INTERNAL_TOKEN", "test-secret")
    monkeypatch.setattr(hermes, "HermesWatchlistService", FakeWatchlistService)

    response = client.post(
        "/api/hermes/wechat/messages",
        headers={"X-Hermes-Internal-Token": "test-secret"},
        json={
            "routing": {"tenant_id": "00000000-0000-0000-0000-000000000000", "channel": "hermes_wechat"},
            "message": {"type": "text", "text": "关注 INTC，跌破 31 提醒我"},
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["result_type"] == "watchlist_updated"
    assert "不会改动持仓" in data["reply_text"]
    method, call = FakeWatchlistService.calls[0]
    assert method == "add_watch"
    assert call["symbol"] == "INTC"
    assert call["alert_price"] == 31
    assert call["alert_direction"] == "below"


def test_hermes_wechat_watchlist_query(monkeypatch):
    FakeWatchlistService.calls = []
    monkeypatch.setenv("HERMES_INTERNAL_TOKEN", "test-secret")
    monkeypatch.setattr(hermes, "HermesWatchlistService", FakeWatchlistService)

    response = client.post(
        "/api/hermes/wechat/messages",
        headers={"X-Hermes-Internal-Token": "test-secret"},
        json={
            "routing": {"tenant_id": "00000000-0000-0000-0000-000000000000", "channel": "hermes_wechat"},
            "message": {"type": "text", "text": "看我的观察清单"},
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["result_type"] == "watchlist"
    assert "INTC" in data["reply_text"]


def test_hermes_wechat_trade_input_stays_read_only(monkeypatch):
    monkeypatch.setenv("HERMES_INTERNAL_TOKEN", "test-secret")

    response = client.post(
        "/api/hermes/wechat/messages",
        headers={"X-Hermes-Internal-Token": "test-secret"},
        json={
            "routing": {"tenant_id": "tenant-test", "channel": "hermes_wechat"},
            "message": {"type": "text", "text": "帮我买入 NVDA"},
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["result_type"] == "readonly_acknowledgement"
    assert data["safety"]["places_orders"] is False
    assert "不会" in data["reply_text"]


def test_root_returns_service_metadata():
    """GET / 返回包含 service name 和 version 的 JSON."""
    response = client.get("/")
    assert response.status_code == 200, "Root endpoint should return 200"
    data = response.json()
    assert data["service"] == "AI Holdings Data Service"
    assert data["version"] == "3.0.0-p0"
    assert "docs" in data
    assert "health" in data
