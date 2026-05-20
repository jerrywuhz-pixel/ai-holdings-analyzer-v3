import subprocess
from pathlib import Path

from local_connectors.openai_codex_bridge.codex_cli_adapter import create_completion


def test_codex_cli_adapter_wraps_codex_auth_session_as_chat_completion(tmp_path):
    recorded = {}

    def fake_run(args, **kwargs):
        recorded["args"] = args
        recorded["kwargs"] = kwargs
        output_path = Path(args[args.index("--output-last-message") + 1])
        output_path.write_text("Codex auth profile response", encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, stdout="codex logs", stderr="")

    completion = create_completion(
        {
            "auth_profile": "system-pro",
            "model": "openai-codex/gpt-5.5",
            "messages": [
                {"role": "system", "content": "Be precise."},
                {"role": "user", "content": "Summarize NVDA."},
            ],
            "temperature": 0.2,
        },
        codex_binary="/usr/local/bin/codex",
        workdir=str(tmp_path),
        timeout_seconds=123,
        run=fake_run,
    )

    assert recorded["args"][0] == "/usr/local/bin/codex"
    assert recorded["args"][1:4] == ["exec", "--ephemeral", "--skip-git-repo-check"]
    assert recorded["args"][recorded["args"].index("-m") + 1] == "gpt-5.5"
    assert recorded["args"][recorded["args"].index("-C") + 1] == str(tmp_path)
    assert recorded["kwargs"]["stdin"] == subprocess.DEVNULL
    assert recorded["kwargs"]["timeout"] == 123
    assert completion["model"] == "openai-codex/gpt-5.5"
    assert completion["choices"][0]["message"]["content"] == "Codex auth profile response"
    assert completion["usage"]["prompt_tokens"] > 0
    assert completion["usage"]["completion_tokens"] > 0
