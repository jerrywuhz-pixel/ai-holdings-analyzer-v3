import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from openclaw.gateway.confirmation_center import (
    ConfirmationCenterService,
    InMemoryConfirmationRepository,
)
from openclaw.gateway.confirmation_center import RoutingContext
from openclaw.gateway.conversation_memory import (
    ConversationMemoryService,
    InMemoryConversationMemoryRepository,
)
from openclaw.gateway.image_vision import ImageTextExtraction
from openclaw.gateway.model_dialogue import ModelDialogueResult, _build_invocation, generate_openclaw_reply
from openclaw.gateway.outbox import DeliveryOutboxService, InMemoryOutboxRepository
import openclaw.gateway.routers.openclaw_gateway as openclaw_gateway
from openclaw.gateway.routers.openclaw_gateway import router


def build_test_client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.state.confirmation_service = ConfirmationCenterService(
        InMemoryConfirmationRepository(),
        webapp_base_url="https://app.example.com",
    )
    app.state.outbox_service = DeliveryOutboxService(InMemoryOutboxRepository())
    return TestClient(app)


def build_test_client_with_conversation_memory() -> tuple[
    TestClient,
    InMemoryConversationMemoryRepository,
]:
    app = FastAPI()
    app.include_router(router)
    app.state.confirmation_service = ConfirmationCenterService(
        InMemoryConfirmationRepository(),
        webapp_base_url="https://app.example.com",
    )
    app.state.outbox_service = DeliveryOutboxService(InMemoryOutboxRepository())
    repository = InMemoryConversationMemoryRepository()
    app.state.conversation_memory_service = ConversationMemoryService(repository)
    return TestClient(app), repository


def build_test_client_with_repository() -> tuple[
    TestClient,
    InMemoryConfirmationRepository,
    InMemoryOutboxRepository,
]:
    app = FastAPI()
    app.include_router(router)
    repository = InMemoryConfirmationRepository()
    outbox_repository = InMemoryOutboxRepository()
    app.state.confirmation_service = ConfirmationCenterService(
        repository,
        webapp_base_url="https://app.example.com",
    )
    app.state.outbox_service = DeliveryOutboxService(outbox_repository)
    return TestClient(app), repository, outbox_repository


class FailingConfirmationRepository(InMemoryConfirmationRepository):
    async def create_pending_action(self, payload):
        raise RuntimeError("database unavailable")


def build_test_client_with_failing_confirmation_repository() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.state.confirmation_service = ConfirmationCenterService(
        FailingConfirmationRepository(),
        webapp_base_url="https://app.example.com",
    )
    app.state.outbox_service = DeliveryOutboxService(InMemoryOutboxRepository())
    return TestClient(app)


def test_text_trade_input_returns_readonly_ack() -> None:
    client = build_test_client()
    response = client.post(
        "/api/openclaw/wechat/messages",
        json={
            "routing": {
                "tenant_id": "tenant-1",
                "channel_binding_id": "binding-1",
                "openclaw_account_id": "bot-1",
            },
            "message": {
                "type": "text",
                "text": "买入 AAPL 10 股 180",
            },
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["result_type"] == "readonly_ack"
    assert "只读模式" in data["reply_text"]
    assert "不会改动持仓" in data["reply_text"]
    assert "不会下单" in data["reply_text"]


def test_confirmation_write_failure_returns_friendly_message(monkeypatch) -> None:
    monkeypatch.setenv("OPENCLAW_WECHAT_SKIP_CONFIRMATION_CENTER", "false")
    client = build_test_client_with_failing_confirmation_repository()
    response = client.post(
        "/api/openclaw/wechat/messages",
        json={
            "routing": {
                "tenant_id": "tenant-db-down",
                "channel_binding_id": "binding-db-down",
                "openclaw_account_id": "bot-db-down",
            },
            "message": {
                "type": "text",
                "text": "买入 AAPL 10 股 180",
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["result_type"] == "confirmation_unavailable"
    assert "确认中心暂时没有保存成功" in data["reply_text"]
    assert "没有记录持仓" in data["reply_text"]
    assert "没有下单" in data["reply_text"]


def test_plain_text_routes_to_light_model(monkeypatch) -> None:
    async def fake_portfolio_market_response(context, text):
        return None

    async def fake_generate_openclaw_reply(text, *, context, route=None, conversation_context=None):
        assert text == "今天的行情分析一下"
        assert context.tenant_id == "tenant-model"
        assert route == "light"
        return ModelDialogueResult(
            route="light",
            provider="minimax",
            model="MiniMax-M2.7",
            reply_text="MiniMax light reply",
            response_id="model-response-1",
        )

    monkeypatch.setattr(openclaw_gateway, "_portfolio_market_response", fake_portfolio_market_response)
    monkeypatch.setattr(openclaw_gateway, "generate_openclaw_reply", fake_generate_openclaw_reply)
    client = build_test_client()
    response = client.post(
        "/api/openclaw/wechat/messages",
        json={
            "routing": {
                "tenant_id": "tenant-model",
                "channel_binding_id": "binding-model",
                "openclaw_account_id": "bot-model",
            },
            "message": {
                "type": "text",
                "text": "今天的行情分析一下",
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["result_type"] == "model_reply"
    assert data["model_route"] == "light"
    assert data["model_provider"] == "minimax"
    assert data["model"] == "MiniMax-M2.7"
    assert data["model_response_id"] == "model-response-1"
    assert data["reply_text"] == "MiniMax light reply"


def test_realtime_search_uses_search_tool_before_model(monkeypatch) -> None:
    model_called = False

    async def fake_portfolio_market_response(context, text):
        return None

    async def fake_fetch_realtime_search(query):
        assert query == "中芯国际"
        return {
            "ok": True,
            "data": {
                "results": [
                    {
                        "title": "中芯国际最新动态",
                        "snippet": "公司发布近期经营相关消息。",
                        "url": "https://example.com/smic",
                    }
                ]
            },
        }

    async def fake_generate_openclaw_reply(*args, **kwargs):
        nonlocal model_called
        model_called = True
        return ModelDialogueResult(
            route="light",
            provider="minimax",
            model="MiniMax-M2.7",
            reply_text="generic model reply",
        )

    monkeypatch.setattr(openclaw_gateway, "_portfolio_market_response", fake_portfolio_market_response)
    monkeypatch.setattr(openclaw_gateway, "_fetch_realtime_search", fake_fetch_realtime_search)
    monkeypatch.setattr(openclaw_gateway, "generate_openclaw_reply", fake_generate_openclaw_reply)
    client = build_test_client()
    response = client.post(
        "/api/openclaw/wechat/messages",
        json={
            "routing": {
                "tenant_id": "tenant-search",
                "channel_binding_id": "binding-search",
                "openclaw_account_id": "bot-search",
            },
            "message": {
                "type": "text",
                "text": "搜一下中芯国际最新消息",
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["result_type"] == "realtime_search"
    assert data["query"] == "中芯国际"
    assert data["results_count"] == 1
    assert "中芯国际最新动态" in data["reply_text"]
    assert "https://example.com/smic" in data["reply_text"]
    assert model_called is False


def test_realtime_search_unavailable_does_not_claim_channel_is_unsupported(monkeypatch) -> None:
    async def fake_portfolio_market_response(context, text):
        return None

    async def fake_fetch_realtime_search(query):
        return {"ok": False, "message": "mmx CLI not found"}

    monkeypatch.setattr(openclaw_gateway, "_portfolio_market_response", fake_portfolio_market_response)
    monkeypatch.setattr(openclaw_gateway, "_fetch_realtime_search", fake_fetch_realtime_search)
    client = build_test_client()
    response = client.post(
        "/api/openclaw/wechat/messages",
        json={
            "routing": {
                "tenant_id": "tenant-search-down",
                "channel_binding_id": "binding-search-down",
                "openclaw_account_id": "bot-search-down",
            },
            "message": {
                "type": "text",
                "text": "实时搜索一下英伟达相关新闻",
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["result_type"] == "realtime_search_unavailable"
    assert "MiniMax 搜索工具暂时不可用" in data["reply_text"]
    assert "不支持实时搜索" not in data["reply_text"]


def test_realtime_search_falls_back_to_ftshare_when_mmx_fails(monkeypatch) -> None:
    async def fake_run_mmx_search(query):
        assert query == "中芯国际"
        return {"ok": False, "message": "API error: HTTP 404"}

    async def fake_run_ftshare_news_search(query):
        assert query == "中芯国际"
        return {
            "ok": True,
            "source": "ftshare",
            "data": {
                "data": [
                    {
                        "title": "中芯国际相关新闻",
                        "summary": "FTShare 返回的实时新闻摘要。",
                        "article_url": "https://example.com/news/smic",
                        "source_site": "ft.tech",
                        "publish_time": "2026-06-02T15:00:00+08:00",
                    }
                ]
            },
        }

    monkeypatch.setattr(openclaw_gateway, "_run_mmx_search", fake_run_mmx_search)
    monkeypatch.setattr(openclaw_gateway, "_run_ftshare_news_search", fake_run_ftshare_news_search)

    payload = asyncio.run(openclaw_gateway._fetch_realtime_search("中芯国际"))
    results = openclaw_gateway._normalize_search_results(payload)

    assert payload["ok"] is True
    assert payload["source"] == "ftshare"
    assert results == [
        {
            "title": "中芯国际相关新闻",
            "snippet": "FTShare 返回的实时新闻摘要。",
            "url": "https://example.com/news/smic",
            "source": "ft.tech",
            "published_at": "2026-06-02T15:00:00+08:00",
        }
    ]


def test_portfolio_market_question_reads_positions_and_quotes(monkeypatch) -> None:
    model_called = False

    async def fake_generate_openclaw_reply(*args, **kwargs):
        nonlocal model_called
        model_called = True
        return ModelDialogueResult(
            route="light",
            provider="minimax",
            model="MiniMax-M2.7",
            reply_text="generic model reply",
        )

    async def fake_fetch_portfolio_positions(tenant_id):
        assert tenant_id == "tenant-portfolio"
        return {
            "ok": True,
            "data": {
                "equity_positions": [
                    {
                        "symbol": "SH600519",
                        "name": "贵州茅台",
                        "quantity": 100,
                        "base_market_value": 130722.0,
                    },
                    {
                        "symbol": "AAPL",
                        "name": "Apple",
                        "quantity": 10,
                        "base_market_value": 3063.1,
                    },
                ],
                "freshness": {"as_of": "2026-06-02T09:30:00+08:00", "age_seconds": 42},
            },
        }

    async def fake_fetch_batch_quotes(symbols):
        assert symbols == ["SH600519", "AAPL"]
        return {
            "ok": True,
            "data": {
                "SH600519": {
                    "symbol": "SH600519",
                    "price": 1307.22,
                    "change_rate": -0.18,
                    "currency": "CNY",
                    "quote_actionability": "analysis_only",
                    "freshness_status": "fresh",
                    "source": "tushare",
                },
                "AAPL": {
                    "symbol": "AAPL",
                    "price": 306.31,
                    "change_rate": -1.07,
                    "currency": "USD",
                    "quote_actionability": "blocked",
                    "freshness_status": "expired",
                    "source": "stooq",
                },
            },
            "failed": [],
        }

    monkeypatch.setattr(openclaw_gateway, "generate_openclaw_reply", fake_generate_openclaw_reply)
    monkeypatch.setattr(openclaw_gateway, "_fetch_portfolio_positions", fake_fetch_portfolio_positions)
    monkeypatch.setattr(openclaw_gateway, "_fetch_batch_quotes", fake_fetch_batch_quotes)
    client = build_test_client()
    response = client.post(
        "/api/openclaw/wechat/messages",
        json={
            "routing": {
                "tenant_id": "tenant-portfolio",
                "channel_binding_id": "binding-portfolio",
                "openclaw_account_id": "bot-portfolio",
            },
            "message": {
                "type": "text",
                "text": "分析一下我的持仓和今天行情",
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["result_type"] == "portfolio_market_context"
    assert data["portfolio_positions_count"] == 2
    assert data["quoted_symbols"] == ["SH600519", "AAPL"]
    assert "可用于分析的行情" in data["reply_text"]
    assert "SH600519" in data["reply_text"]
    assert "暂不可用/过期的行情：AAPL" in data["reply_text"]
    assert model_called is False


def test_realtime_quote_uses_analysis_quote_without_require_fresh(monkeypatch) -> None:
    async def fake_fetch_realtime_quote(symbol):
        assert symbol == "SH600519"
        return {
            "ok": True,
            "data": {
                "symbol": "SH600519",
                "price": 1307.22,
                "change": -2.38,
                "change_rate": -0.18,
                "currency": "CNY",
                "source": "tushare",
                "freshness_seconds": 0,
                "freshness_status": "fresh",
                "quote_actionability": "analysis_only",
            },
        }

    monkeypatch.setattr(openclaw_gateway, "_fetch_realtime_quote", fake_fetch_realtime_quote)
    client = build_test_client()
    response = client.post(
        "/api/openclaw/wechat/messages",
        json={
            "routing": {
                "tenant_id": "tenant-quote",
                "channel_binding_id": "binding-quote",
                "openclaw_account_id": "bot-quote",
            },
            "message": {
                "type": "text",
                "text": "600519 实时行情",
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["result_type"] == "market_quote"
    assert data["symbol"] == "SH600519"
    assert "1307.22" in data["reply_text"]
    assert "只用于分析" in data["reply_text"]


def test_model_unavailable_reply_is_user_friendly(monkeypatch) -> None:
    monkeypatch.setenv("GBRAIN_LIVE_MODELS_ENABLED", "false")
    result = asyncio.run(
        generate_openclaw_reply(
            "帮我分析一下 TSLA 的 Sell Put",
            context=RoutingContext(
                tenant_id="tenant-friendly",
                channel_binding_id="binding-friendly",
                openclaw_account_id="bot-friendly",
            ),
        )
    )

    assert result.stub is True
    assert "Sell Put" in result.reply_text
    assert "模型路由" not in result.reply_text
    assert "minimax" not in result.reply_text.lower()
    assert "provider" not in result.reply_text.lower()
    assert "不会改动持仓，也不会下单" in result.reply_text


def test_stub_model_response_keeps_user_visible_type_friendly(monkeypatch) -> None:
    async def fake_generate_openclaw_reply(text, *, context, route=None, conversation_context=None):
        return ModelDialogueResult(
            route="light",
            provider="minimax",
            model="MiniMax-M2.7",
            reply_text="收到，我会按普通投资问题继续处理。当前不会改动持仓，也不会下单。",
            stub=True,
            error="missing_minimax_auth",
        )

    monkeypatch.setattr(openclaw_gateway, "generate_openclaw_reply", fake_generate_openclaw_reply)
    client = build_test_client()
    response = client.post(
        "/api/openclaw/wechat/messages",
        json={
            "routing": {
                "tenant_id": "tenant-stub",
                "channel_binding_id": "binding-stub",
                "openclaw_account_id": "bot-stub",
            },
            "message": {
                "type": "text",
                "text": "今天市场怎么看",
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["result_type"] == "query_routed"
    assert data["model_stub"] is True
    assert "模型路由" not in data["reply_text"]


def test_sell_put_analysis_routes_to_dialogue_not_confirmation(monkeypatch) -> None:
    async def fake_generate_openclaw_reply(text, *, context, route=None, conversation_context=None):
        assert "Sell Put" in text
        return ModelDialogueResult(
            route="light",
            provider="minimax",
            model="MiniMax-M2.7",
            reply_text="收到，我先按 Sell Put 机会来拆。",
        )

    monkeypatch.setattr(openclaw_gateway, "generate_openclaw_reply", fake_generate_openclaw_reply)
    client = build_test_client()
    response = client.post(
        "/api/openclaw/wechat/messages",
        json={
            "routing": {
                "tenant_id": "tenant-sellput-analysis",
                "channel_binding_id": "binding-sellput-analysis",
                "openclaw_account_id": "bot-sellput-analysis",
            },
            "message": {
                "type": "text",
                "text": "帮我分析一下 TSLA 的 Sell Put 候选排序",
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["result_type"] == "model_reply"
    assert "确认中心" not in data["reply_text"]


def test_deep_research_text_routes_to_deep_model(monkeypatch) -> None:
    async def fake_generate_openclaw_reply(text, *, context, route=None, conversation_context=None):
        assert "深度研究" in text
        assert route == "deep"
        return ModelDialogueResult(
            route="deep",
            provider="openai-codex",
            model="gpt-5.5",
            reply_text="Hermes deep reply",
            response_id="deep-response-1",
        )

    monkeypatch.setattr(openclaw_gateway, "generate_openclaw_reply", fake_generate_openclaw_reply)
    client = build_test_client()
    response = client.post(
        "/api/openclaw/wechat/messages",
        json={
            "routing": {
                "tenant_id": "tenant-deep",
                "channel_binding_id": "binding-deep",
                "openclaw_account_id": "bot-deep",
            },
            "message": {
                "type": "text",
                "text": "帮我做一个 NVDA 深度研究报告",
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["result_type"] == "model_reply"
    assert data["model_route"] == "deep"
    assert data["model_provider"] == "openai-codex"
    assert data["reply_text"] == "Hermes deep reply"


def test_light_and_deep_routes_share_wechat_conversation_memory(monkeypatch) -> None:
    observed_contexts: list[str | None] = []

    async def fake_generate_openclaw_reply(text, *, context, route=None, conversation_context=None):
        observed_contexts.append(conversation_context)
        if route == "deep":
            return ModelDialogueResult(
                route="deep",
                provider="openai-codex",
                model="gpt-5.5",
                reply_text="Hermes deep reply: NVDA 的核心风险是估值和出口管制。",
                response_id="deep-memory-response",
            )
        assert route == "light"
        assert "NVDA 深度研究报告" in (conversation_context or "")
        assert "Hermes deep reply" in (conversation_context or "")
        return ModelDialogueResult(
            route="light",
            provider="minimax",
            model="MiniMax-M2.7",
            reply_text="我接着刚才的深研结论说，先看仓位暴露和估值回撤空间。",
            response_id="light-memory-response",
        )

    monkeypatch.setattr(openclaw_gateway, "generate_openclaw_reply", fake_generate_openclaw_reply)
    client, repository = build_test_client_with_conversation_memory()
    routing = {
        "tenant_id": "tenant-memory",
        "channel_binding_id": "binding-memory",
        "openclaw_account_id": "bot-memory",
        "target_conversation": "wechat-thread-memory",
    }

    first = client.post(
        "/api/openclaw/wechat/messages",
        json={
            "routing": routing,
            "message": {
                "id": "msg-deep",
                "type": "text",
                "text": "帮我做一个 NVDA 深度研究报告",
            },
        },
    )
    second = client.post(
        "/api/openclaw/wechat/messages",
        json={
            "routing": routing,
            "message": {
                "id": "msg-light",
                "type": "text",
                "text": "那它对我的仓位有什么影响",
            },
        },
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert observed_contexts[0] is None
    assert "Hermes deep reply" in (observed_contexts[1] or "")

    thread = next(iter(repository.threads_by_key.values()))
    turns = repository.turns_by_thread[thread["id"]]
    assert [turn["role"] for turn in turns] == ["user", "assistant", "user", "assistant"]
    assert turns[1]["route"] == "deep"
    assert turns[3]["route"] == "light"
    assert "NVDA 的核心风险" in thread["summary"]


def test_light_model_prompt_discourages_customer_service_template() -> None:
    invocation = _build_invocation(
        "今天的行情分析一下",
        context=RoutingContext(
            tenant_id="tenant-prompt",
            channel_binding_id="binding-prompt",
            openclaw_account_id="bot-prompt",
            timezone_name="Asia/Shanghai",
        ),
        route="light",
    )

    assert "不要像客服模板" in invocation["system"]
    assert "不要用“您好”“感谢咨询”“抱歉我无法提供”开头" in invocation["system"]
    assert "只用一句短句说明限制，然后继续给出有用的分析框架" in invocation["system"]
    assert "今天的行情分析一下" in invocation["prompt"]


def test_model_prompt_includes_shared_conversation_context() -> None:
    invocation = _build_invocation(
        "那它对我的仓位有什么影响",
        context=RoutingContext(
            tenant_id="tenant-prompt-memory",
            channel_binding_id="binding-prompt-memory",
            openclaw_account_id="bot-prompt-memory",
            timezone_name="Asia/Shanghai",
        ),
        route="light",
        conversation_context="会话摘要：用户刚做过 NVDA 深研，Hermes 结论是估值和出口管制风险。",
    )

    assert "同一微信会话的共享上下文如下" in invocation["prompt"]
    assert "OpenClaw 日常沟通和 Hermes 深研后的对话记忆" in invocation["prompt"]
    assert "不要把它当成已经确认写入持仓的业务事实" in invocation["prompt"]
    assert "Hermes 结论是估值和出口管制风险" in invocation["prompt"]


def test_voice_confirm_command_consumes_latest_session(monkeypatch) -> None:
    monkeypatch.setenv("OPENCLAW_WECHAT_SKIP_CONFIRMATION_CENTER", "false")
    client = build_test_client()
    first = client.post(
        "/api/openclaw/wechat/messages",
        json={
            "routing": {
                "tenant_id": "tenant-1",
                "channel_binding_id": "binding-1",
                "openclaw_account_id": "bot-1",
            },
            "message": {
                "type": "text",
                "text": "买入 NVDA 5 股 900",
            },
        },
    )
    session_token = first.json()["session_token"]

    second = client.post(
        "/api/openclaw/wechat/messages",
        json={
            "routing": {
                "tenant_id": "tenant-1",
                "channel_binding_id": "binding-1",
                "openclaw_account_id": "bot-1",
            },
            "message": {
                "type": "voice",
                "transcript": f"确认 {session_token}",
                "transcript_confidence": 0.99,
            },
        },
    )
    assert second.status_code == 200
    data = second.json()
    assert data["result_type"] == "decision_received"
    assert data["decision"] == "confirmed"


def test_wechat_duplicate_confirm_is_idempotent(monkeypatch) -> None:
    monkeypatch.setenv("OPENCLAW_WECHAT_SKIP_CONFIRMATION_CENTER", "false")
    client, repository, _ = build_test_client_with_repository()
    first = client.post(
        "/api/openclaw/wechat/messages",
        json={
            "routing": {
                "tenant_id": "tenant-duplicate",
                "channel_binding_id": "binding-duplicate",
                "openclaw_account_id": "bot-duplicate",
            },
            "message": {
                "type": "text",
                "text": "买入 AMD 2 股 130",
            },
        },
    )
    session_token = first.json()["session_token"]

    confirmed = client.post(
        "/api/openclaw/wechat/messages",
        json={
            "routing": {
                "tenant_id": "tenant-duplicate",
                "channel_binding_id": "binding-duplicate",
                "openclaw_account_id": "bot-duplicate",
            },
            "message": {
                "type": "text",
                "text": f"确认 {session_token}",
            },
        },
    )
    duplicate = client.post(
        "/api/openclaw/wechat/messages",
        json={
            "routing": {
                "tenant_id": "tenant-duplicate",
                "channel_binding_id": "binding-duplicate",
                "openclaw_account_id": "bot-duplicate",
            },
            "message": {
                "type": "text",
                "text": f"确认 {session_token}",
            },
        },
    )

    assert confirmed.status_code == 200
    assert duplicate.status_code == 200
    assert confirmed.json()["decision"] == "confirmed"
    assert duplicate.json()["decision"] == "already_confirmed"
    assert "不会重复" in duplicate.json()["reply_text"]
    assert repository.events[-1]["event_type"] == "duplicate_ignored"


def test_low_confidence_voice_does_not_enter_confirmation_center_by_default() -> None:
    client = build_test_client()
    response = client.post(
        "/api/openclaw/wechat/messages",
        json={
            "routing": {
                "tenant_id": "tenant-voice",
                "channel_binding_id": "binding-voice",
                "openclaw_account_id": "bot-voice",
            },
            "message": {
                "type": "voice",
                "transcript": "以后不要提醒我中概股",
                "transcript_confidence": 0.41,
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["result_type"] == "readonly_ack"
    assert "只读模式" in data["reply_text"]
    assert "不会改动持仓，也不会下单" in data["reply_text"]


def test_image_ocr_candidate_returns_readonly_ack_in_default_mode() -> None:
    client = build_test_client()
    response = client.post(
        "/api/openclaw/wechat/messages",
        json={
            "routing": {
                "tenant_id": "tenant-image",
                "channel_binding_id": "binding-image",
                "openclaw_account_id": "bot-image",
            },
            "message": {
                "type": "image",
                "image_text": "买入 BABA 5 股 88",
                "ocr_confidence": 0.87,
                "media_id": "wx-media-1",
                "metadata": {"source": "album"},
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["result_type"] == "readonly_ack"
    assert "不会改动持仓，也不会下单" in data["reply_text"]


def test_low_confidence_image_ocr_does_not_enter_confirmation_center_in_default_mode() -> None:
    client = build_test_client()
    response = client.post(
        "/api/openclaw/wechat/messages",
        json={
            "routing": {
                "tenant_id": "tenant-image-low-confidence",
                "channel_binding_id": "binding-image-low-confidence",
                "openclaw_account_id": "bot-image-low-confidence",
                "target_conversation": "conversation-image-low-confidence",
            },
            "message": {
                "type": "image",
                "ocr_text": "买入 AAPL 10 股 180",
                "ocr_confidence": 0.33,
                "media_id": "wx-media-low-confidence",
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["result_type"] == "readonly_ack"
    assert "不会改动持仓，也不会下单" in data["reply_text"]


def test_low_confidence_image_ocr_does_not_enter_confirmation_review_center_in_default_mode() -> None:
    client = build_test_client()
    response = client.post(
        "/api/openclaw/wechat/messages",
        json={
            "routing": {
                "tenant_id": "tenant-image-low-confidence",
                "channel_binding_id": "binding-image-low-confidence",
                "openclaw_account_id": "bot-image-low-confidence",
                "target_conversation": "conversation-image-low-confidence",
            },
            "message": {
                "type": "image",
                "ocr_text": "买入 AAPL 10 股 180",
                "ocr_confidence": 0.33,
                "media_id": "wx-media-low-confidence",
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["result_type"] == "readonly_ack"
    assert "不会改动持仓，也不会下单" in data["reply_text"]


def test_position_screenshot_image_readonly_ack_in_default_mode() -> None:
    client = build_test_client()
    response = client.post(
        "/api/openclaw/wechat/messages",
        json={
            "routing": {
                "tenant_id": "tenant-position-image",
                "channel_binding_id": "binding-position-image",
                "openclaw_account_id": "bot-position-image",
                "target_conversation": "conversation-position-image",
            },
            "message": {
                "type": "image",
                "ocr_text": "持仓 数量 成本\nAAPL 苹果 10 180.25\nNVDA 英伟达 2 900",
                "ocr_confidence": 0.91,
                "media_id": "wx-position-media",
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["result_type"] == "readonly_ack"
    assert "不会改动持仓，也不会下单" in data["reply_text"]


def test_image_without_ocr_uses_vision_positions_without_confirmation_center(monkeypatch) -> None:
    async def fake_extract_image_text_from_metadata(metadata):
        assert metadata["image_data_url"].startswith("data:image/jpeg;base64,")
        return ImageTextExtraction(
            ocr_text="持仓截图",
            positions=[
                {
                    "stock_name": "盛新锂能",
                    "market": "CN",
                    "exchange": "UNKNOWN",
                    "quantity": 10000,
                    "available_quantity": 10000,
                    "average_cost": 53.858,
                    "current_price": 48.510,
                    "market_value": 485100.00,
                    "unrealized_pnl": -53475.75,
                    "pnl_ratio": -0.0993,
                },
            ],
            confidence=0.93,
            provider="openai",
            model="gpt-4.1-mini",
            response_id="vision-response-1",
        )

    monkeypatch.setattr(openclaw_gateway, "extract_image_text_from_metadata", fake_extract_image_text_from_metadata)
    client = build_test_client()
    response = client.post(
        "/api/openclaw/wechat/messages",
        json={
            "routing": {
                "tenant_id": "tenant-position-vision",
                "channel_binding_id": "binding-position-vision",
                "openclaw_account_id": "bot-position-vision",
            },
            "message": {
                "type": "image",
                "media_id": "wx-position-media-vision",
                "metadata": {
                    "image_data_url": "data:image/jpeg;base64,abc",
                },
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["result_type"] == "readonly_ack"
    assert "不会改动持仓，也不会下单" in data["reply_text"]


def test_image_without_downloadable_reference_returns_diagnostic_reply() -> None:
    client, repository, _ = build_test_client_with_repository()
    response = client.post(
        "/api/openclaw/wechat/messages",
        json={
            "routing": {
                "tenant_id": "tenant-image-media-id-only",
                "channel_binding_id": "binding-image-media-id-only",
                "openclaw_account_id": "bot-image-media-id-only",
            },
            "message": {
                "type": "image",
                "media_id": "wx-long-media-token",
                "metadata": {
                    "media_id": "wx-long-media-token",
                    "media_download": {
                        "status": "missing_media_reference",
                        "source": "clawbot_getupdates",
                        "media_id_present": True,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["result_type"] == "image_unrecognized"
    assert "没有拿到可下载的图片内容" in data["reply_text"]
    assert repository.pending_actions == {}


def test_image_vision_failure_returns_diagnostic_reply(monkeypatch) -> None:
    async def fake_extract_image_text_from_metadata(metadata):
        return ImageTextExtraction(
            ocr_text="",
            positions=[],
            confidence=None,
            provider="minimax",
            model="MiniMax-M2.7",
            response_id=None,
            error="HTTPStatusError:401 Unauthorized",
        )

    monkeypatch.setattr(openclaw_gateway, "extract_image_text_from_metadata", fake_extract_image_text_from_metadata)
    client, repository, _ = build_test_client_with_repository()
    response = client.post(
        "/api/openclaw/wechat/messages",
        json={
            "routing": {
                "tenant_id": "tenant-image-vision-failed",
                "channel_binding_id": "binding-image-vision-failed",
                "openclaw_account_id": "bot-image-vision-failed",
            },
            "message": {
                "type": "image",
                "media_id": "wx-position-media-vision-failed",
                "metadata": {
                    "image_data_url": "data:image/jpeg;base64,abc",
                },
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["result_type"] == "image_unrecognized"
    assert "图片识别服务调用失败" in data["reply_text"]
    assert repository.pending_actions == {}
