import pytest
import httpx

from openclaw.gateway.image_vision import (
    _anthropic_image_source,
    _call_minimax_vision,
    _message_content,
    _prepare_image_reference_for_provider,
    _vision_provider_config,
)


def test_image_vision_provider_defaults_to_minimax_m27(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENCLAW_IMAGE_VISION_MODEL", raising=False)
    monkeypatch.setenv("MINIMAX_MODEL", "MiniMax-M2.7")
    monkeypatch.setenv("MINIMAX_API_KEY", "minimax-key")
    monkeypatch.setenv("MINIMAX_OPENAI_BASE_URL", "https://api.minimaxi.com/anthropic")

    provider, base_url, api_key, model = _vision_provider_config()

    assert provider == "minimax"
    assert base_url == "https://api.minimaxi.com/anthropic"
    assert api_key == "minimax-key"
    assert model == "MiniMax-M2.7"


def test_anthropic_image_source_requires_data_url() -> None:
    source = _anthropic_image_source("data:image/jpeg;base64,abc123")

    assert source == {
        "type": "base64",
        "media_type": "image/jpeg",
        "data": "abc123",
    }
    with pytest.raises(ValueError):
        _anthropic_image_source("https://example.com/image.jpg")


def test_message_content_supports_anthropic_and_openai_shapes() -> None:
    assert _message_content({"content": [{"type": "text", "text": "{\"ok\": true}"}]}) == '{"ok": true}'
    assert (
        _message_content({"choices": [{"message": {"content": "{\"ok\": true}"}}]})
        == '{"ok": true}'
    )


@pytest.mark.asyncio
async def test_anthropic_vision_downloads_http_image_as_data_url(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        headers = {"content-type": "image/png", "content-length": "4"}
        content = b"abcd"

        def raise_for_status(self) -> None:
            return None

    class FakeAsyncClient:
        def __init__(self, **_: object) -> None:
            return None

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def get(self, url: str) -> FakeResponse:
            assert url == "https://cdn.example.com/holding.png"
            return FakeResponse()

    monkeypatch.setenv("MINIMAX_OPENAI_BASE_URL", "https://api.minimaxi.com/anthropic")
    monkeypatch.setattr("openclaw.gateway.image_vision.httpx.AsyncClient", FakeAsyncClient)

    prepared = await _prepare_image_reference_for_provider("https://cdn.example.com/holding.png")

    assert prepared == "data:image/png;base64,YWJjZA=="


@pytest.mark.asyncio
async def test_minimax_vision_retries_transient_5xx(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    class FakeResponse:
        def __init__(self, status_code: int) -> None:
            self.status_code = status_code
            self.text = "temporary overload" if status_code >= 500 else "{\"ok\": true}"
            self.reason_phrase = "Service Unavailable"
            self.request = httpx.Request("POST", "https://api.minimaxi.com/anthropic/v1/messages")

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("boom", request=self.request, response=self)  # type: ignore[arg-type]

        def json(self) -> dict[str, object]:
            return {"id": "ok", "content": [{"type": "text", "text": "{\"positions\": []}"}]}

    class FakeAsyncClient:
        def __init__(self, **_: object) -> None:
            return None

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def post(self, *_: object, **__: object) -> FakeResponse:
            nonlocal calls
            calls += 1
            return FakeResponse(529 if calls == 1 else 200)

    monkeypatch.setenv("MINIMAX_API_FORMAT", "anthropic")
    monkeypatch.setenv("OPENCLAW_IMAGE_VISION_API_ATTEMPTS", "2")
    monkeypatch.setattr("openclaw.gateway.image_vision.httpx.AsyncClient", FakeAsyncClient)

    payload = await _call_minimax_vision(
        "data:image/png;base64,YWJjZA==",
        base_url="https://api.minimaxi.com/anthropic",
        api_key="key",
        model="MiniMax-M2.7",
    )

    assert calls == 2
    assert payload["id"] == "ok"
