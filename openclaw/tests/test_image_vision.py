import pytest

from openclaw.gateway.image_vision import (
    _anthropic_image_source,
    _message_content,
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
