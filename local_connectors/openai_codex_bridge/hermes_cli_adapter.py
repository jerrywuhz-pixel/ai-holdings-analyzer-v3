from __future__ import annotations

"""Hermes CLI command adapter for the OpenAI Codex auth bridge."""

import json
import os
import subprocess
import sys
from typing import Any, Mapping, Sequence
from uuid import uuid4


class HermesCliAdapterError(RuntimeError):
    """Raised when Hermes CLI cannot produce a usable response."""


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _model_name(model: str) -> str:
    return model.rsplit("/", 1)[-1] if "/" in model else model


def _message_lines(messages: Sequence[Mapping[str, Any]]) -> list[str]:
    lines: list[str] = []
    for message in messages:
        role = str(message.get("role") or "user").upper()
        content = str(message.get("content") or "").strip()
        if content:
            lines.append(f"{role}: {content}")
    return lines


def build_hermes_prompt(payload: Mapping[str, Any]) -> str:
    messages = payload.get("messages") or []
    lines = _message_lines(messages if isinstance(messages, list) else [])
    return "\n\n".join(
        [
            "You are the OpenAI deep-research model behind Hermes/GBrain.",
            "Return only the final answer text for the caller.",
            "Conversation:",
            "\n".join(lines) if lines else "USER: Respond with a concise empty-result note.",
        ]
    )


def create_completion(payload: Mapping[str, Any]) -> dict[str, Any]:
    requested_model = str(payload.get("model") or "openai-codex/gpt-5.5")
    model = _model_name(requested_model)
    prompt = build_hermes_prompt(payload)
    timeout = float(os.getenv("HERMES_CLI_TIMEOUT_SECONDS", os.getenv("CODEX_BRIDGE_TIMEOUT_SECONDS", "300")))
    hermes = os.getenv("HERMES_CLI_PATH", "/usr/local/lib/hermes-agent/venv/bin/hermes")

    args = [hermes, "--provider", "openai-codex", "--model", model, "-z", prompt]
    env = {**os.environ, "HOME": os.getenv("HOME", "/root"), "NO_COLOR": "1"}
    try:
        result = subprocess.run(
            args,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise HermesCliAdapterError(f"hermes CLI timed out after {timeout:g}s") from exc

    if result.returncode != 0:
        stderr = (result.stderr or result.stdout or "").strip()
        raise HermesCliAdapterError(f"hermes CLI failed: {stderr[:800]}")

    text = (result.stdout or "").strip()
    if not text:
        raise HermesCliAdapterError("hermes CLI completed but produced no final message")

    prompt_tokens = _estimate_tokens(prompt)
    completion_tokens = _estimate_tokens(text)
    return {
        "id": f"hermes-codex-bridge-{uuid4()}",
        "object": "chat.completion",
        "model": requested_model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        completion = create_completion(payload)
    except (json.JSONDecodeError, HermesCliAdapterError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(completion, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
