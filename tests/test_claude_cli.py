import json
import os

import pytest

from ai_lab import claude_cli
from ai_lab.claude_cli import CliRun


def _value(args: list[str], flag: str) -> str:
    return args[args.index(flag) + 1]


def test_build_args_uses_subscription_safe_flags():
    args = claude_cli.build_args("claude-haiku-5-5", "medium", "課題文")
    assert args[:2] == ["-p", "課題文"]
    assert _value(args, "--model") == "claude-haiku-5-5"
    assert _value(args, "--effort") == "medium"
    assert _value(args, "--output-format") == "json"
    assert _value(args, "--tools") == "Read,Write,Edit"
    assert _value(args, "--permission-mode") == "acceptEdits"
    assert _value(args, "--max-turns") == str(claude_cli.MAX_TURNS)
    assert "--no-session-persistence" in args
    assert "--safe-mode" in args
    # --bare は API キーを要求するため使わない。実行系のツールや権限の回避も与えない。
    assert "--bare" not in args
    assert "--dangerously-skip-permissions" not in args
    assert "Bash" not in _value(args, "--tools")


def test_child_environment_removes_billing_variables_only():
    base = {
        "PATH": "p",
        "HOME": "h",
        "ANTHROPIC_API_KEY": "k",
        "ANTHROPIC_AUTH_TOKEN": "t",
        "CLAUDE_CODE_USE_BEDROCK": "1",
        "CLAUDE_CODE_USE_VERTEX": "1",
        "CLAUDE_CODE_USE_FOUNDRY": "1",
    }
    assert claude_cli.child_environment(base) == {"PATH": "p", "HOME": "h"}


def test_nested_run_reason_detects_claude_code_session():
    assert claude_cli.nested_run_reason({"CLAUDECODE": "1"}) == "CLAUDECODE"
    assert claude_cli.nested_run_reason({"CLAUDE_CODE_ENTRYPOINT": "cli"}) == "CLAUDE_CODE_ENTRYPOINT"
    assert claude_cli.nested_run_reason({"CLAUDECODE": ""}) is None
    assert claude_cli.nested_run_reason({"PATH": "p"}) is None


def test_parse_output_accepts_object_array_and_noisy_output():
    result = {"type": "result", "subtype": "success", "result": "ok"}
    assert claude_cli.parse_output(json.dumps(result)) == result
    assert claude_cli.parse_output(json.dumps([{"type": "system"}, result])) == result
    assert claude_cli.parse_output("warning: something\n" + json.dumps(result) + "\n") == result
    assert claude_cli.parse_output("not json at all") is None
    assert claude_cli.parse_output(json.dumps({"type": "system"})) is None


def _result(**fields):
    base = {"type": "result", "subtype": "success", "is_error": False, "num_turns": 2, "total_cost_usd": 0.01}
    base.update(fields)
    return json.dumps(base)


@pytest.mark.parametrize(
    "run, expected",
    [
        (CliRun(0, _result(), "", 1.0, False), "ok"),
        (CliRun(1, _result(), "", 1.0, False), "error"),
        (CliRun(0, _result(subtype="error_max_turns", is_error=True), "", 1.0, False), "error"),
        (CliRun(0, "junk", "", 1.0, False), "unparsed"),
        (CliRun(None, "", "", 1.0, True), "timeout"),
    ],
)
def test_summarize_run_status(run, expected):
    assert claude_cli.summarize_run(run)["status"] == expected


def test_summarize_run_keeps_usage_and_per_model_usage():
    usage = {"input_tokens": 1, "output_tokens": 2, "cache_read_input_tokens": 3, "cache_creation_input_tokens": 4}
    model_usage = {"claude-haiku-5-5": {"inputTokens": 1, "outputTokens": 2}}
    summary = claude_cli.summarize_run(CliRun(0, _result(usage=usage, modelUsage=model_usage), "", 1.0, False))
    assert summary["usage"] == usage
    assert summary["model_usage"] == model_usage
    assert summary["cli_total_cost_usd"] == pytest.approx(0.01)
    assert summary["num_turns"] == 2
    assert summary["permission_denials"] == 0


def test_preflight_accepts_subscription_login(fake_command, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_AUTH", "claude.ai")
    info = claude_cli.preflight(fake_command, dict(os.environ))
    assert info == {"version": "9.9.9 (Claude Code)", "auth_method": "claude.ai"}


@pytest.mark.parametrize("method", ["api_key", "api_key_helper", "third_party", "none"])
def test_preflight_refuses_non_subscription_auth(fake_command, monkeypatch, method):
    monkeypatch.setenv("FAKE_CLAUDE_AUTH", method)
    with pytest.raises(RuntimeError, match="サブスクリプション"):
        claude_cli.preflight(fake_command, dict(os.environ))


def test_preflight_refuses_when_logged_out(fake_command, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_LOGGED_OUT", "1")
    with pytest.raises(RuntimeError, match="ログイン"):
        claude_cli.preflight(fake_command, dict(os.environ))


def test_preflight_reports_a_hung_cli_as_an_error(fake_command, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_AUTH_SLEEP", "10")
    with pytest.raises(RuntimeError, match="タイムアウト"):
        claude_cli.preflight(fake_command, dict(os.environ), timeout=1.0)


def test_cmd_wrapper_is_refused_so_the_prompt_is_not_mangled_by_cmd_exe():
    with pytest.raises(RuntimeError, match="--claude-bin"):
        claude_cli.check_native_executable(r"C:\tools\claude.cmd")
    with pytest.raises(RuntimeError):
        claude_cli.check_native_executable(r"C:\tools\claude.BAT")
    claude_cli.check_native_executable(r"C:\Users\me\bin\claude.exe")  # 実行ファイル本体は通す
