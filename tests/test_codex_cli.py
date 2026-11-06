"""Codex subprocess protocol and existing API-key transport, without paid calls."""

import io
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from hiro.brain.llm import ClaudeCLI, CodexCLI, LLMAdapter, from_spec


def test_spec_keeps_default_and_accepts_codex(monkeypatch):
    monkeypatch.delenv("HIRO_LLM", raising=False)
    assert isinstance(from_spec(), ClaudeCLI)
    assert isinstance(from_spec("codex"), LLMAdapter)
    assert from_spec("codex-cli:example-model").model == "example-model"
    monkeypatch.setenv("HIRO_CODEX_COMMAND", "C:/Program Files/Codex/codex.exe")
    assert CodexCLI().executable == "C:/Program Files/Codex/codex.exe"


def test_stdin_utf8_image_final_file_and_usage():
    seen = {}

    def run(cmd, **kw):
        seen.update(cmd=cmd, **kw)
        assert kw["input"] == "系统\n\nReturn only a JSON object. Do not use tools.\n\n選ぶ"
        assert kw["encoding"] == "utf-8" and kw["text"]
        assert kw["timeout"] == 7
        assert cmd[0] == "C:/Program Files/Codex/codex.exe"
        assert "--ignore-user-config" in cmd and "--ephemeral" in cmd
        assert 'features.shell_tool=false' in cmd and 'web_search="disabled"' in cmd
        assert cmd[cmd.index("--sandbox") + 1] == "read-only"
        assert cmd.index("-") < cmd.index("--image")
        assert Path(cmd[cmd.index("--image") + 1]).read_bytes() == b"jpeg"
        Path(cmd[cmd.index("--output-last-message") + 1]).write_text('{"reason":"選ぶ"}', encoding="utf-8")
        event = {"type": "turn.completed", "usage": {"input_tokens": 120, "cached_input_tokens": 100, "output_tokens": 9}}
        return subprocess.CompletedProcess(cmd, 0, "not-json\n[]\n" + json.dumps(event), "")

    with patch("hiro.brain.llm.subprocess.run", side_effect=run):
        result = CodexCLI("example", timeout=7, executable="C:/Program Files/Codex/codex.exe").ask_json_image("系统", "選ぶ", b"jpeg")
    assert result.data == {"reason": "選ぶ"} and result.error is None
    assert (result.input_tokens, result.cache_read_input_tokens, result.output_tokens) == (20, 100, 9)
    assert result.cost_usd is None
    assert not Path(seen["cwd"]).exists()


@pytest.mark.parametrize("mode,expected", [
    ("timeout", "timeout"), ("missing_exe", "codex launch:"),
    ("exit", "exit 1: login required"), ("event", "exit 0: failed"),
    ("missing_file", "missing codex final message"), ("invalid", "no json in reply"),
])
def test_failures_return_adapter_errors(mode, expected):
    def run(cmd, **kw):
        if mode == "timeout":
            raise subprocess.TimeoutExpired(cmd, kw["timeout"])
        if mode == "missing_exe":
            raise FileNotFoundError("codex")
        if mode == "invalid":
            Path(cmd[cmd.index("--output-last-message") + 1]).write_text("unknown", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 1 if mode == "exit" else 0,
                                           '{"type":"turn.failed","error":"failed"}' if mode == "event" else "",
                                           "login required" if mode == "exit" else "")
    with patch("hiro.brain.llm.subprocess.run", side_effect=run):
        result = CodexCLI().ask_json("s", "u")
    assert result.data is None and result.error.startswith(expected)


def test_temp_directory_failure_is_reported():
    with patch("hiro.brain.llm.tempfile.TemporaryDirectory", side_effect=PermissionError("temp denied")):
        result = CodexCLI().ask_json("s", "u")
    assert result.data is None and result.error == "codex temporary files: temp denied"


def test_api_key_env_utf8_image_and_cached_usage(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.invalid/v1/")
    payload = {"choices": [{"message": {"content": '{"reason":"好"}'}}],
               "usage": {"prompt_tokens": 30, "completion_tokens": 4, "prompt_tokens_details": {"cached_tokens": 20}}}

    def urlopen(req, timeout):
        assert req.full_url == "https://example.invalid/v1/chat/completions"
        assert req.get_header("Authorization") == "Bearer test-key"
        body = json.loads(req.data.decode("utf-8"))
        assert body["messages"][0] == {"role": "system", "content": "系统"}
        assert body["messages"][1]["content"][0]["image_url"]["url"] == "data:image/jpeg;base64,anBlZw=="
        assert body["messages"][1]["content"][1]["text"] == "選ぶ"
        assert body["response_format"] == {"type": "json_object"}
        return io.BytesIO(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    with patch("hiro.brain.llm.urllib.request.urlopen", side_effect=urlopen):
        result = from_spec("openai:example").ask_json_image("系统", "選ぶ", b"jpeg")
    assert result.data == {"reason": "好"}
    assert (result.input_tokens, result.cache_read_input_tokens, result.output_tokens) == (10, 20, 4)
