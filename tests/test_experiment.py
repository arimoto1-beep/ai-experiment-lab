import json
from pathlib import Path

import pytest

from ai_lab.experiment import ExperimentConfig, price_trial, run_experiment
from ai_lab.problems import PROJECT_ROOT

FIXTURES = PROJECT_ROOT / "tests" / "fixtures"
REFERENCE_SOLUTION = FIXTURES / "reference" / "duration_parse.py"
NAIVE_SOLUTION = FIXTURES / "naive" / "duration_parse.py"
PROBLEMS_ROOT = PROJECT_ROOT / "problems"

# tests/fixtures/fake_claude.py が返す固定の使用量（テスト用の値であり、実際のモデルの使用量ではない）
FAKE_COST_USD = 0.000465


def _config(tmp_path: Path, runs: int = 2, timeout: float = 60.0) -> ExperimentConfig:
    return ExperimentConfig(
        problem="duration_parse",
        model_id="claude-haiku-5-5",
        model_label="haiku",
        effort="medium",
        runs=runs,
        timeout=timeout,
        results_dir=(tmp_path / "results").resolve(),
        problems_root=PROBLEMS_ROOT,
    )


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _arg_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "args.jsonl"
    monkeypatch.setenv("FAKE_CLAUDE_ARGLOG", str(path))
    return path


def _calls(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_trials_are_independent_and_results_are_recorded(tmp_path, fake_command, monkeypatch):
    arg_log = _arg_log(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_CLAUDE_SOLUTION", str(REFERENCE_SOLUTION))
    # 従量課金の鍵が設定されていても、子プロセスには渡らないことを確かめる
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-reach-claude")

    exp_dir = run_experiment(_config(tmp_path), fake_command, log=lambda _: None)

    calls = _calls(arg_log)
    assert len(calls) == 2
    assert len({call["cwd"] for call in calls}) == 2  # 試行ごとに別の作業ディレクトリ
    for call in calls:
        argv = call["argv"]
        assert argv[argv.index("--model") + 1] == "claude-haiku-5-5"
        assert argv[argv.index("--effort") + 1] == "medium"
        assert "--bare" not in argv
        assert call["env"]["ANTHROPIC_API_KEY"] is False
        assert call["env"]["CLAUDE_CODE_USE_BEDROCK"] is False

    summary = _json(exp_dir / "summary.json")
    assert summary["completed_runs"] == 2
    assert summary["passed"] == 2
    assert summary["pass_rate"] == 1.0
    assert summary["any_passed"] is True
    assert summary["cli_not_ok"] == 0
    assert summary["cost_complete"] is True
    assert summary["api_equivalent_usd_total"] == pytest.approx(2 * FAKE_COST_USD)
    assert summary["api_equivalent_usd_per_pass"] == pytest.approx(FAKE_COST_USD)
    assert summary["tokens"] == {"input": 200, "output": 100, "cache_read": 6000, "cache_write": 4000}

    trial = _json(exp_dir / "trial_01" / "trial.json")
    assert trial["outcome"] == "pass"
    assert trial["claude"]["status"] == "ok"
    assert trial["tokens"] == {"input": 100, "output": 50, "cache_read": 3000, "cache_write": 2000}
    assert trial["cost"]["api_equivalent_usd"] == pytest.approx(FAKE_COST_USD)
    assert trial["cost"]["cache_write_ttl_assumed"] == "1h"
    assert trial["claude"]["cli_total_cost_usd"] == pytest.approx(FAKE_COST_USD)
    assert trial["wall_seconds"] >= 0
    assert (exp_dir / "trial_01" / "junit.xml").exists()
    assert (exp_dir / "trial_01" / "claude_stdout.txt").exists()


def test_workspace_holds_only_the_answer_not_the_hidden_tests(tmp_path, fake_command, monkeypatch):
    _arg_log(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_CLAUDE_SOLUTION", str(REFERENCE_SOLUTION))

    exp_dir = run_experiment(_config(tmp_path, runs=1), fake_command, log=lambda _: None)

    workspace = exp_dir / "trial_01" / "workspace"
    assert sorted(p.name for p in workspace.iterdir()) == ["solution.py"]
    assert not any(p.name.startswith("test_") for p in workspace.rglob("*"))


def test_failing_answer_with_cli_error_is_still_evaluated_and_costed(tmp_path, fake_command, monkeypatch):
    _arg_log(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_CLAUDE_SOLUTION", str(NAIVE_SOLUTION))
    monkeypatch.setenv("FAKE_CLAUDE_EXIT", "1")

    exp_dir = run_experiment(_config(tmp_path, runs=1), fake_command, log=lambda _: None)

    trial = _json(exp_dir / "trial_01" / "trial.json")
    assert trial["outcome"] == "fail"
    assert trial["claude"]["status"] == "error"
    assert trial["evaluation"]["passed"] is False
    assert trial["evaluation"]["failures"] > 0
    assert trial["cost"]["api_equivalent_usd"] == pytest.approx(FAKE_COST_USD)
    summary = _json(exp_dir / "summary.json")
    assert summary["cli_not_ok"] == 1
    assert summary["any_passed"] is False
    assert summary["api_equivalent_usd_per_pass"] is None


def test_timeout_is_recorded_without_usage(tmp_path, fake_command, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_SLEEP", "10")

    exp_dir = run_experiment(_config(tmp_path, runs=1, timeout=1.0), fake_command, log=lambda _: None)

    trial = _json(exp_dir / "trial_01" / "trial.json")
    assert trial["claude"]["status"] == "timeout"
    assert trial["tokens"] is None
    assert trial["cost"]["api_equivalent_usd"] is None
    assert trial["cost"]["complete"] is False
    assert trial["outcome"] == "fail"


def test_unparsed_output_still_gets_the_answer_evaluated(tmp_path, fake_command, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_OUTPUT", "text")
    monkeypatch.setenv("FAKE_CLAUDE_SOLUTION", str(REFERENCE_SOLUTION))

    exp_dir = run_experiment(_config(tmp_path, runs=1), fake_command, log=lambda _: None)

    trial = _json(exp_dir / "trial_01" / "trial.json")
    assert trial["claude"]["status"] == "unparsed"
    assert trial["outcome"] == "pass"
    assert trial["tokens"] is None
    assert trial["cost"]["api_equivalent_usd"] is None


def test_non_subscription_login_stops_before_any_result_is_written(tmp_path, fake_command, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_AUTH", "api_key")

    with pytest.raises(RuntimeError, match="サブスクリプション"):
        run_experiment(_config(tmp_path), fake_command, log=lambda _: None)

    assert not (tmp_path / "results").exists()


def test_price_trial_prices_each_model_and_flags_unknown_ones():
    haiku = {"inputTokens": 100, "outputTokens": 50, "cacheReadInputTokens": 3000, "cacheCreationInputTokens": 2000}
    cli = {"model_usage": {"claude-haiku-5-5": haiku, "claude-unknown-9": {"inputTokens": 1}}, "num_turns": 2}

    tokens, cost = price_trial(cli, "claude-haiku-5-5")

    assert cost["api_equivalent_usd"] == pytest.approx(FAKE_COST_USD)
    assert cost["complete"] is False
    assert any("claude-unknown-9" in note for note in cost["notes"])
    assert tokens["input"] == 101


def test_price_trial_warns_when_haiku_prompts_exceed_the_long_context_threshold():
    big = {"inputTokens": 10, "outputTokens": 10, "cacheReadInputTokens": 300_000, "cacheCreationInputTokens": 0}
    cli = {"model_usage": {"claude-haiku-5-5": big}, "num_turns": 2}

    _, cost = price_trial(cli, "claude-haiku-5-5")

    assert cost["complete"] is True
    assert any("100000" in note for note in cost["notes"])


def test_price_trial_without_usage_reports_no_cost():
    tokens, cost = price_trial({"status": "timeout", "model_usage": None, "usage": None}, "claude-haiku-5-5")
    assert tokens is None
    assert cost["api_equivalent_usd"] is None
    assert cost["complete"] is False
