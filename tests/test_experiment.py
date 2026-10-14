import json
from dataclasses import replace
from pathlib import Path

import pytest

from ai_lab.experiment import ExperimentConfig, check_model, price_trial, run_experiment
from ai_lab.pricing import PRICES_PER_MTOK, PRICING_CHECKED_ON, PRICING_SOURCE_URL
from ai_lab.problems import PROJECT_ROOT
from ai_lab.report import build_report

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


@pytest.mark.parametrize("problem, solution", [
    ("duration_parse", REFERENCE_SOLUTION),
    ("arithmetic_parser", FIXTURES / "arithmetic" / "reference.py"),
    ("inventory_allocation", FIXTURES / "inventory" / "reference.py"),
])
@pytest.mark.parametrize("model_id, label, effort, expected_cost", [
    ("claude-haiku-5-5", "haiku", "medium", FAKE_COST_USD),
    ("claude-haiku-5-5", "haiku", "max", FAKE_COST_USD),
    ("claude-opus-4-8", "opus48", "high", 0.02325),
])
def test_three_settings_use_existing_problems_and_record_results(
    tmp_path, fake_command, monkeypatch, problem, solution, model_id, label, effort, expected_cost,
):
    arg_log = _arg_log(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_CLAUDE_SOLUTION", str(solution))
    config = replace(_config(tmp_path, runs=1), problem=problem, model_id=model_id, model_label=label, effort=effort)

    exp_dir = run_experiment(config, fake_command, log=lambda _: None)

    call = _calls(arg_log)[0]
    assert call["argv"][call["argv"].index("--model") + 1] == model_id
    assert call["argv"][call["argv"].index("--effort") + 1] == effort
    assert sorted(Path(call["cwd"]).iterdir()) == [Path(call["cwd"]) / "solution.py"]
    trial = _json(exp_dir / "trial_01" / "trial.json")
    assert trial["problem"] == problem and trial["effort"] == effort
    assert trial["model_check"]["status"] == "match"
    assert trial["model_check"]["actual_model_ids"] == [model_id]
    assert trial["outcome"] == "pass" and trial["evaluation"]["tests"] > 0
    assert trial["claude"]["model_usage"][model_id]["inputTokens"] == 100
    assert trial["cost"]["api_equivalent_usd"] == pytest.approx(expected_cost)
    assert trial["claude"]["cli_total_cost_usd"] == pytest.approx(FAKE_COST_USD)
    assert trial["cost"]["pricing_source"] == PRICING_SOURCE_URL
    assert trial["cost"]["pricing_checked_on"] == PRICING_CHECKED_ON
    assert trial["cost"]["rates_per_mtok"][model_id] == PRICES_PER_MTOK[model_id]
    summary = _json(exp_dir / "summary.json")
    assert summary["comparison_basis"] == "model_and_effort"
    assert summary["actual_model_ids"] == [model_id]
    assert summary["model_mismatch_trials"] == summary["model_unverified_trials"] == 0
    assert summary["api_equivalent_usd_mean"] == pytest.approx(expected_cost)
    assert summary["mean_wall_seconds"] >= 0
    meta = _json(exp_dir / "experiment.json")
    assert meta["comparison_basis"] == "model_and_effort"
    assert meta["pricing_checked_on"] == PRICING_CHECKED_ON


@pytest.mark.parametrize("actual, status", [
    (["claude-opus-4-8"], "match"),
    (["claude-opus-4-8-20260528"], "match"),
    (["claude-opus-5-5"], "mismatch"),
    (["claude-opus-4-8", "claude-haiku-5-5"], "mismatch"),
    (["claude-opus-4-8-fast"], "mismatch"),
    ([], "unverified"),
])
def test_model_id_verification_uses_reported_ids(actual, status):
    check = check_model({"model_usage": dict.fromkeys(actual, {})}, "claude-opus-4-8")
    assert check["status"] == status
    assert check["actual_model_ids"] == sorted(actual)


@pytest.mark.parametrize("actual, expected_cost", [
    ("claude-opus-4-8", 0.02325),
    ("claude-opus-5-5", 0.018),
    ("claude-unknown-9", None),
])
def test_mismatched_model_is_visible_and_priced_using_actual_id(tmp_path, fake_command, monkeypatch, actual, expected_cost):
    monkeypatch.setenv("FAKE_CLAUDE_SOLUTION", str(REFERENCE_SOLUTION))
    monkeypatch.setenv("FAKE_CLAUDE_MODEL", actual)
    messages = []
    exp_dir = run_experiment(_config(tmp_path, runs=1), fake_command, log=messages.append)

    trial = _json(exp_dir / "trial_01" / "trial.json")
    assert trial["outcome"] == "pass"  # 隠しテストによる合否は維持
    assert trial["model_check"]["status"] == "mismatch"
    assert trial["model_check"]["unexpected_model_ids"] == [actual]
    if expected_cost is None:
        assert trial["cost"]["api_equivalent_usd"] is None
        assert trial["cost"]["complete"] is False
    else:
        assert trial["cost"]["api_equivalent_usd"] == pytest.approx(expected_cost)
    assert any("mismatch" in message for message in messages)
    summary = _json(exp_dir / "summary.json")
    assert summary["model_mismatch_trials"] == 1
    assert summary["actual_model_ids"] == [actual]
    report = build_report([exp_dir])
    assert actual in report and "model_mismatch" in report


def test_missing_actual_model_preserves_usage_without_guessing_a_cost(tmp_path, fake_command, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_SOLUTION", str(REFERENCE_SOLUTION))
    monkeypatch.setenv("FAKE_CLAUDE_NO_MODEL_USAGE", "1")
    exp_dir = run_experiment(_config(tmp_path, runs=1), fake_command, log=lambda _: None)

    trial = _json(exp_dir / "trial_01" / "trial.json")
    assert trial["model_check"]["status"] == "unverified"
    assert trial["model_check"]["actual_model_ids"] == []
    assert trial["tokens"] == {"input": 100, "output": 50, "cache_read": 3000, "cache_write": 2000}
    assert trial["cost"]["api_equivalent_usd"] is None
    assert trial["cost"]["complete"] is False
    summary = _json(exp_dir / "summary.json")
    assert summary["model_unverified_trials"] == 1
    assert summary["api_equivalent_usd_mean"] is None


@pytest.mark.parametrize("cache_5m, cache_1h", [(2000, 0), (0, 2000), (500, 1500)])
def test_cache_write_ttl_breakdown_uses_separate_official_prices(cache_5m, cache_1h):
    cli = {
        "model_usage": {"claude-opus-4-8": {
            "inputTokens": 100, "outputTokens": 50,
            "cacheReadInputTokens": 3000, "cacheCreationInputTokens": 2000,
        }},
        "usage": {"cache_creation": {
            "ephemeral_5m_input_tokens": cache_5m, "ephemeral_1h_input_tokens": cache_1h,
        }},
        "num_turns": 3,
    }
    tokens, cost = price_trial(cli, "claude-opus-4-8")
    expected = (100 * 5 + 50 * 25 + 3000 * 0.5 + cache_5m * 6.25 + cache_1h * 10) / 1_000_000
    assert cost["api_equivalent_usd"] == pytest.approx(expected)
    assert tokens["cache_write"] == 2000
    assert cost["cache_write_ttl_assumed"] is None
    assert cost["cache_write_tokens_by_ttl"] == {"5m": cache_5m, "1h": cache_1h}
    assert cost["complete"] is True


@pytest.mark.parametrize("models, cache_total", [
    (["claude-opus-4-8"], 1000),  # TTL内訳が合計と不一致
    (["claude-opus-4-8", "claude-haiku-5-5"], 4000),  # モデル別にTTLを割り当てられない
])
def test_ambiguous_ttl_retains_the_documented_one_hour_assumption(models, cache_total):
    cli = {
        "model_usage": {name: {"cacheCreationInputTokens": 2000} for name in models},
        "usage": {"cache_creation": {"ephemeral_5m_input_tokens": cache_total}},
    }
    _, cost = price_trial(cli, "claude-opus-4-8")
    assert cost["cache_write_ttl_assumed"] == "1h"
    assert cost["cache_write_tokens_by_ttl"] is None
    assert any("TTL内訳" in note for note in cost["notes"])
