import pytest

from services.hermes.reference_capture import WebReferencePersistence
from services.hermes.domain_tools import DomainToolsFacade


class FakeResponse:
    def __init__(self, payload, *, text=""):
        self._payload = payload
        self.text = text

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeClient:
    calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, url, *, json=None, timeout=None, params=None):
        self.calls.append({"url": url, "json": json, "timeout": timeout, "params": params})
        return FakeResponse(
            {
                "ok": True,
                "status": "ok",
                "schema_version": "web_reference_snapshot_v1",
                "reference_only": True,
                "url": json["url"],
                "canonical_url": "https://example.com/article",
                "title": "Example Article",
                "content_text": "This article discusses NVDA and demand signals.",
                "content_markdown": "# Example Article\n\nThis article discusses NVDA and demand signals.",
                "content_hash": "abc123",
                "status_code": 200,
                "mode_used": "get",
                "attempted_modes": ["get"],
                "fetched_at": "2026-06-17T06:00:00+00:00",
                "source_refs": [{"source": "web", "ref": "https://example.com/article"}],
                "audit": {"sanitization": "visible_text_extraction"},
            }
        )

    async def get(self, url, *, params=None, timeout=None):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        return FakeResponse(
            {
                "results": [
                    {
                        "title": "Example Article",
                        "url": "https://example.com/article",
                        "content": "This public result is relevant to NVDA.",
                        "engine": "test-search",
                    }
                ]
            }
        )


class FakeBingClient(FakeClient):
    async def get(self, url, *, params=None, timeout=None):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        return FakeResponse(
            {},
            text="""
            <html>
              <body>
                <ol>
                  <li class="b_algo">
                    <h2><a href="https://www.bing.com/ck/a?!&amp;&amp;u=a1aHR0cHM6Ly9leGFtcGxlLmNvbS9hcnRpY2xl&amp;ntb=1">Example Article</a></h2>
                    <div class="b_caption"><p>This public result is relevant to NVDA.</p></div>
                  </li>
                </ol>
              </body>
            </html>
            """,
        )


class FakeFailingReferenceClient(FakeClient):
    async def post(self, url, *, json=None, timeout=None, params=None):
        self.calls.append({"url": url, "json": json, "timeout": timeout, "params": params})
        return FakeResponse(
            {
                "ok": False,
                "status": "empty_content",
                "schema_version": "web_reference_snapshot_v1",
                "reference_only": True,
                "url": json["url"],
                "canonical_url": json["url"],
                "title": None,
                "content_text": "",
                "content_markdown": "",
                "content_hash": "failed123",
                "status_code": 200,
                "mode_used": "get",
                "attempted_modes": ["get", "dynamic"],
                "fetched_at": "2026-06-18T06:00:00+00:00",
                "source_refs": [{"source": "web", "ref": json["url"]}],
                "failed": {
                    "reason": "empty_content",
                    "message": "Reference capture returned no readable content.",
                },
                "audit": {
                    "failure_reason": "empty_content",
                    "failure_message": "Reference capture returned no readable content.",
                },
            }
        )


class FakeNoopClient(FakeClient):
    calls = []

    async def get(self, url, *, params=None, timeout=None):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        return FakeResponse({"results": []})


@pytest.mark.asyncio
async def test_reference_web_read_calls_sidecar_and_returns_audited_result(monkeypatch):
    FakeClient.calls = []
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
    facade = DomainToolsFacade(
        reference_capture_url="http://reference-capture:8010",
        http_client_factory=FakeClient,
    )

    result = await facade.invoke(
        "reference.web.read",
        {
            "tenant_id": "tenant-test",
            "url": "https://example.com/article",
            "prompt": "总结一下",
            "entry_surface": "wechat",
        },
    )

    assert result["tool"] == "reference.web.read"
    assert result["ok"] is True
    assert result["data"]["reference_only"] is True
    assert result["data"]["summary"]["title"] == "Example Article"
    assert result["data"]["summary"]["summary"].startswith("This article")
    assert result["data"]["persistence"] == {"status": "skipped", "reason": "DATABASE_URL_missing"}
    assert result["source_refs"] == [{"source": "web", "ref": "https://example.com/article"}]
    assert FakeClient.calls == [
        {
            "url": "http://reference-capture:8010/read",
            "json": {
                "url": "https://example.com/article",
                "tenant_id": "tenant-test",
                "mode": "auto",
                "timeout_ms": 30000,
                "max_chars": 12000,
            },
            "timeout": 130,
            "params": None,
        }
    ]


@pytest.mark.asyncio
async def test_reference_web_read_uses_stealthy_and_proxy_only_for_allowed_host(monkeypatch):
    FakeClient.calls = []
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("HERMES_REFERENCE_STEALTHY_ENABLED", "true")
    monkeypatch.setenv("HERMES_REFERENCE_STEALTHY_HOSTS", "mp.weixin.qq.com")
    monkeypatch.setenv("HERMES_REFERENCE_PROXY_ENABLED", "true")
    monkeypatch.setenv("HERMES_REFERENCE_PROXY_HOSTS", "mp.weixin.qq.com")
    monkeypatch.setenv("HERMES_REFERENCE_PROXY_URL", "http://proxy.local:8080")
    facade = DomainToolsFacade(
        reference_capture_url="http://reference-capture:8010",
        http_client_factory=FakeClient,
    )

    result = await facade.invoke(
        "reference.web.read",
        {
            "tenant_id": "tenant-test",
            "url": "https://mp.weixin.qq.com/s/article",
            "mode": "stealthy",
            "allow_stealthy": True,
            "prompt": "读一下",
            "entry_surface": "wechat",
        },
    )

    assert result["ok"] is True
    assert FakeClient.calls[0]["json"]["mode"] == "stealthy"
    assert FakeClient.calls[0]["json"]["proxy_url"] == "http://proxy.local:8080"
    policy = result["data"]["audit"]["read_policy"]
    assert policy["stealthy_allowed"] is True
    assert policy["proxy_allowed"] is True
    assert "proxy_url" not in policy


@pytest.mark.asyncio
async def test_reference_web_read_downgrades_stealthy_when_host_not_allowed(monkeypatch):
    FakeClient.calls = []
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("HERMES_REFERENCE_STEALTHY_ENABLED", "true")
    monkeypatch.setenv("HERMES_REFERENCE_STEALTHY_HOSTS", "mp.weixin.qq.com")
    monkeypatch.setenv("HERMES_REFERENCE_PROXY_ENABLED", "true")
    monkeypatch.setenv("HERMES_REFERENCE_PROXY_HOSTS", "mp.weixin.qq.com")
    monkeypatch.setenv("HERMES_REFERENCE_PROXY_URL", "http://proxy.local:8080")
    facade = DomainToolsFacade(
        reference_capture_url="http://reference-capture:8010",
        http_client_factory=FakeClient,
    )

    result = await facade.invoke(
        "reference.web.read",
        {
            "tenant_id": "tenant-test",
            "url": "https://example.com/article",
            "mode": "stealthy",
            "allow_stealthy": True,
        },
    )

    assert result["ok"] is True
    assert FakeClient.calls[0]["json"]["mode"] == "auto"
    assert "proxy_url" not in FakeClient.calls[0]["json"]
    policy = result["data"]["audit"]["read_policy"]
    assert policy["stealthy_reason"] == "disabled_or_host_not_allowed"
    assert policy["proxy_allowed"] is False


@pytest.mark.asyncio
async def test_reference_web_read_persists_failed_snapshot(monkeypatch):
    FakeFailingReferenceClient.calls = []
    saved = []

    class FakePersistence:
        async def save(self, **kwargs):
            saved.append(kwargs)
            return {
                "status": "saved",
                "backend": "postgres",
                "artifact_id": "artifact-failed",
                "artifact_key": "web-reference:failed123",
                "artifact_status": "failed",
            }

    monkeypatch.setattr(
        "services.hermes.domain_tools.WebReferencePersistence.from_env",
        lambda: FakePersistence(),
    )
    facade = DomainToolsFacade(
        reference_capture_url="http://reference-capture:8010",
        http_client_factory=FakeFailingReferenceClient,
    )

    result = await facade.invoke(
        "reference.web.read",
        {
            "tenant_id": "00000000-0000-0000-0000-000000000000",
            "url": "https://example.com/blocked",
            "prompt": "读一下",
            "entry_surface": "wechat",
        },
    )

    assert result["tool"] == "reference.web.read"
    assert result["ok"] is False
    assert result["status"] == "empty_content"
    assert result["failed"]["reason"] == "empty_content"
    assert result["data"]["summary"]["failed"]["reason"] == "empty_content"
    assert result["data"]["audit"]["failed"]["reason"] == "empty_content"
    assert result["data"]["persistence"]["artifact_status"] == "failed"
    assert saved[0]["reference"]["ok"] is False
    assert saved[0]["reference"]["content_hash"] == "failed123"
    assert saved[0]["entry_surface"] == "wechat"


@pytest.mark.asyncio
async def test_reference_web_search_reads_top_result_when_configured(monkeypatch):
    FakeClient.calls = []
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
    monkeypatch.delenv("HERMES_REFERENCE_SEARCH_PROVIDER", raising=False)
    monkeypatch.setenv("HERMES_REFERENCE_SEARCH_URL", "http://search.local/search")
    facade = DomainToolsFacade(
        reference_capture_url="http://reference-capture:8010",
        http_client_factory=FakeClient,
    )

    result = await facade.invoke(
        "reference.web.search",
        {
            "tenant_id": "tenant-test",
            "query": "NVDA 最新新闻",
            "prompt": "搜索 NVDA 最新新闻",
            "entry_surface": "wechat",
            "read_top": True,
        },
    )

    assert result["tool"] == "reference.web.search"
    assert result["ok"] is True
    assert result["data"]["reference_only"] is True
    assert result["data"]["items"][0]["url"] == "https://example.com/article"
    assert result["data"]["read_result"]["data"]["summary"]["title"] == "Example Article"
    assert {"source": "web", "ref": "https://example.com/article"} in result["source_refs"]
    assert FakeClient.calls[0] == {
        "url": "http://search.local/search",
        "params": {"q": "NVDA 最新新闻", "format": "json", "language": "zh-CN"},
        "timeout": 30,
    }
    assert FakeClient.calls[1]["url"] == "http://reference-capture:8010/read"


@pytest.mark.asyncio
async def test_reference_web_search_provider_chain_prefers_ima(monkeypatch):
    FakeClient.calls = []
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("HERMES_REFERENCE_SEARCH_PROVIDERS", "ima,gbrain,searxng")
    facade = DomainToolsFacade(
        reference_capture_url="http://reference-capture:8010",
        http_client_factory=FakeClient,
    )

    async def fake_ima_search(arguments):
        return {
            "tool": "reference.ima.search",
            "ok": True,
            "status": "ok",
            "data": {
                "data": {
                    "items": [
                        {
                            "title": "IMA NVDA note",
                            "content": "IMA knowledge says NVDA demand remains strong.",
                            "note_id": "note-1",
                        }
                    ]
                }
            },
            "source_refs": [{"source": "ima", "ref": "knowledge"}],
        }

    monkeypatch.setattr(facade, "ima_search", fake_ima_search)

    result = await facade.invoke(
        "reference.web.search",
        {"tenant_id": "tenant-test", "query": "NVDA 最新新闻", "read_top": True},
    )

    assert result["ok"] is True
    assert result["data"]["provider"] == "ima"
    assert result["data"]["items"][0]["url"].startswith("ima://")
    assert result["data"]["read_result"] is None
    assert FakeClient.calls == []


@pytest.mark.asyncio
async def test_reference_web_search_uses_notes_scope_when_ima_kb_missing(monkeypatch):
    monkeypatch.delenv("IMA_REFERENCE_SEARCH_SCOPE", raising=False)
    monkeypatch.delenv("IMA_DEFAULT_KNOWLEDGE_BASE_ID", raising=False)
    monkeypatch.setenv("HERMES_REFERENCE_SEARCH_PROVIDERS", "ima")
    captured = {}
    facade = DomainToolsFacade(http_client_factory=FakeNoopClient)

    async def fake_ima_search(arguments):
        captured.update(arguments)
        return {
            "tool": "reference.ima.search",
            "ok": True,
            "status": "ok",
            "data": {"data": {"items": []}},
            "source_refs": [{"source": "ima", "ref": "notes"}],
        }

    monkeypatch.setattr(facade, "ima_search", fake_ima_search)

    result = await facade.invoke("reference.web.search", {"query": "NVDA", "limit": 3})

    assert result["ok"] is True
    assert result["data"]["provider"] == "ima"
    assert captured["scope"] == "notes"


@pytest.mark.asyncio
async def test_reference_web_search_falls_back_to_gbrain_and_skips_non_http_read(monkeypatch):
    FakeClient.calls = []
    monkeypatch.setenv("HERMES_REFERENCE_SEARCH_PROVIDERS", "ima,gbrain,searxng")
    facade = DomainToolsFacade(
        reference_capture_url="http://reference-capture:8010",
        http_client_factory=FakeClient,
    )

    async def fake_ima_search(arguments):
        return {"tool": "reference.ima.search", "ok": False, "status": "disabled", "source_refs": []}

    async def fake_gbrain_search(*, tenant_id, query, limit):
        return {
            "status": "ok",
            "results": [
                {
                    "title": "GBrain NVDA memo",
                    "url": "gbrain://stocks/NVDA",
                    "content": "Internal GBrain memo about NVDA catalysts.",
                    "source": "gbrain",
                }
            ],
        }

    monkeypatch.setattr(facade, "ima_search", fake_ima_search)
    monkeypatch.setattr(facade, "_gbrain_search", fake_gbrain_search)

    result = await facade.invoke(
        "reference.web.search",
        {"tenant_id": "tenant-test", "query": "NVDA catalysts", "read_top": True},
    )

    assert result["ok"] is True
    assert result["data"]["provider"] == "gbrain"
    assert result["data"]["items"][0]["url"] == "gbrain://stocks/NVDA"
    assert result["data"]["read_result"] is None
    assert result["data"]["providers_attempted"][0]["provider"] == "ima"
    assert result["data"]["providers_attempted"][1]["provider"] == "gbrain"
    assert FakeClient.calls == []


@pytest.mark.asyncio
async def test_reference_web_search_supports_bing_html_without_endpoint(monkeypatch):
    FakeBingClient.calls = []
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
    monkeypatch.delenv("HERMES_REFERENCE_SEARCH_URL", raising=False)
    monkeypatch.setenv("HERMES_REFERENCE_SEARCH_PROVIDER", "bing_html")
    facade = DomainToolsFacade(
        reference_capture_url="http://reference-capture:8010",
        http_client_factory=FakeBingClient,
    )

    result = await facade.invoke(
        "reference.web.search",
        {
            "tenant_id": "tenant-test",
            "query": "NVDA 最新新闻",
            "prompt": "搜索 NVDA 最新新闻",
            "entry_surface": "wechat",
            "read_top": True,
        },
    )

    assert result["tool"] == "reference.web.search"
    assert result["ok"] is True
    assert result["data"]["provider"] == "bing_html"
    assert result["data"]["items"][0]["url"] == "https://example.com/article"
    assert result["data"]["read_result"]["data"]["summary"]["title"] == "Example Article"
    assert FakeBingClient.calls[0] == {
        "url": "https://www.bing.com/search",
        "params": {"q": "NVDA 最新新闻"},
        "timeout": 30,
    }
    assert FakeBingClient.calls[1]["url"] == "http://reference-capture:8010/read"


@pytest.mark.asyncio
async def test_reference_web_search_reports_not_configured(monkeypatch):
    FakeClient.calls = []
    monkeypatch.delenv("HERMES_REFERENCE_SEARCH_URL", raising=False)
    monkeypatch.delenv("HERMES_REFERENCE_SEARCH_PROVIDER", raising=False)
    facade = DomainToolsFacade(http_client_factory=FakeClient)

    result = await facade.invoke("reference.web.search", {"query": "NVDA 最新新闻"})

    assert result["ok"] is False
    assert result["status"] == "search_source_not_configured"
    assert result["failed"]["reason"] == "search_source_not_configured"
    assert result["data"]["items"] == []
    assert FakeClient.calls == []


@pytest.mark.asyncio
async def test_reference_persistence_reports_postgres_error_without_raising(monkeypatch):
    pytest.importorskip("psycopg")

    class FakeConnection:
        def __enter__(self):
            raise RuntimeError("tenant missing")

        def __exit__(self, exc_type, exc, tb):
            return None

    import psycopg

    monkeypatch.setattr(psycopg, "connect", lambda *_args, **_kwargs: FakeConnection())

    result = await WebReferencePersistence(database_url="postgresql://example").save(
        tenant_id="00000000-0000-0000-0000-00000000a101",
        reference={
            "ok": True,
            "url": "https://example.com",
            "canonical_url": "https://example.com",
            "content_hash": "abc123",
            "content_text": "Example text",
            "source_refs": [{"source": "web", "ref": "https://example.com"}],
        },
        entry_surface="wechat",
        prompt="smoke",
    )

    assert result["status"] == "failed"
    assert result["reason"] == "postgres_error:RuntimeError"
    assert result["message"] == "tenant missing"
    assert result["artifact_status"] == "ready"
