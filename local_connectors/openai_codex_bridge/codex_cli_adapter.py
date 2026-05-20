from __future__ import annotations

"""
Codex CLI command adapter for the OpenAI Codex auth bridge.

The bridge `command` mode calls this module with an OpenAI-compatible payload on
stdin. The adapter invokes the local `codex exec` binary, which uses the
machine's ChatGPT/Codex auth session, then wraps the final Codex message as a
chat-completions response for Hermes/GBrain.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from uuid import uuid4


RunFn = Callable[..., subprocess.CompletedProcess[str]]


class CodexCliAdapterError(RuntimeError):
    """Raised when the local Codex CLI cannot produce a usable response."""


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _codex_model_name(model: str) -> str:
    return model.rsplit("/", 1)[-1] if "/" in model else model


def _message_lines(messages: Sequence[Mapping[str, Any]]) -> list[str]:
    lines: list[str] = []
    for message in messages:
        role = str(message.get("role") or "user").upper()
        content = str(message.get("content") or "").strip()
        if content:
            lines.append(f"{role}: {content}")
    return lines


def build_codex_prompt(payload: Mapping[str, Any]) -> str:
    messages = payload.get("messages") or []
    message_lines = _message_lines(messages if isinstance(messages, list) else [])
    auth_profile = str(payload.get("auth_profile") or "default")

    return "\n\n".join(
        [
            "You are the OpenAI deep-research model behind Hermes/GBrain.",
            "Return only the final answer text for the caller. Do not describe Codex internals.",
            f"Hermes auth profile: {auth_profile}",
            "Conversation:",
            "\n".join(message_lines) if message_lines else "USER: Respond with a concise empty-result note.",
        ]
    )


def create_completion(
    payload: Mapping[str, Any],
    *,
    codex_binary: str | None = None,
    workdir: str | None = None,
    timeout_seconds: float | None = None,
    run: RunFn = subprocess.run,
) -> dict[str, Any]:
    requested_model = str(payload.get("model") or "openai-codex/gpt-5.5")
    codex_model = _codex_model_name(requested_model)
    prompt = build_codex_prompt(payload)
    timeout = timeout_seconds or float(os.getenv("CODEX_CLI_TIMEOUT_SECONDS", "300"))
    codex = codex_binary or os.getenv("CODEX_BINARY", "codex")
    cwd = workdir or os.getenv("CODEX_BRIDGE_CODEX_WORKDIR", "/tmp")

    with tempfile.TemporaryDirectory(prefix="codex-bridge-") as tmp:
        output_path = Path(tmp) / "last-message.txt"
        args = [
            codex,
            "exec",
            "--ephemeral",
            "--skip-git-repo-check",
            "--ignore-rules",
            "-C",
            cwd,
            "-m",
            codex_model,
            "--sandbox",
            "read-only",
            "--output-last-message",
            str(output_path),
            prompt,
        ]
        env = {
            **os.environ,
            "NO_COLOR": "1",
        }
        try:
            result = run(
                args,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            raise CodexCliAdapterError(f"codex exec timed out after {timeout:g}s") from exc

        if result.returncode != 0:
            stderr = (result.stderr or result.stdout or "").strip()
            raise CodexCliAdapterError(f"codex exec failed: {stderr[:800]}")

        text = output_path.read_text(encoding="utf-8").strip() if output_path.exists() else ""
        if not text:
            raise CodexCliAdapterError("codex exec completed but produced no final message")

    prompt_tokens = _estimate_tokens(prompt)
    completion_tokens = _estimate_tokens(text)
    return {
        "id": f"codex-bridge-{uuid4()}",
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
    except (json.JSONDecodeError, CodexCliAdapterError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(completion, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
