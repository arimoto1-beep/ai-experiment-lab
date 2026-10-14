import copy
import json
from pathlib import Path

import pytest

from ai_lab import claude_cli, cli, spec_benchmark
from ai_lab.experiment import check_model, price_trial
from ai_lab.pricing import PRICING_CHECKED_ON, PRICING_SOURCE_URL, TokenCounts, cost_usd, price_key
from ai_lab.spec_scoring import SET2_SPEC_NAMES, build_prompt, load_spec

MODEL = "claude-haiku-4-5"


def _read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", ["haiku45", MODEL])
def test_alias_and_formal_id(name):
    assert cli._resolve_model(name) == (MODEL, name)


@pytest.mark.parametrize("effort", [None, "default"])
@pytest.mark.parametrize("model", [MODEL, MODEL + "-20251001"])
def test_cli_default_omits_effort_and_does_not_disable_thinking(model, effort):
    args = spec_benchmark.build_args(model, effort, "課題文")
    assert claude_cli.resolve_effort(model, effort) == "default"
    assert args[:2] == ["-p", "課題文"]
    assert args[args.index("--model") + 1] == model
    assert "--effort" not in args
    assert args[args.index("--tools") + 1] == "" and args[args.index("--disallowedTools") + 1] == "*"
    assert "--safe-mode" in args and "--no-session-persistence" in args
    assert "--settings" not in args and not any("thinking" in arg.lower() for arg in args)


@pytest.mark.parametrize("effort", ["low", "medium", "high", "xhigh", "max"])
def test_unsupported_effort_is_rejected_without_model_calls(tmp_path, capsys, effort):
    for main in (cli.main, spec_benchmark.main):
        assert main(["run", "--model", "haiku45", "--effort", effort, "--dry-run",
                     "--results-dir", str(tmp_path / "results")]) == 1
        assert "Effort非対応" in capsys.readouterr().err
    assert not (tmp_path / "results").exists()


@pytest.mark.parametrize("model, effort", [("haiku", "medium"), ("haiku", "max"), ("sonnet46", "high"),
                                         ("opus48", "high"), ("opus", "medium")])
def test_existing_model_effort_flags_are_preserved(model, effort):
    model_id, _ = cli._resolve_model(model)
    args = claude_cli.build_args(model_id, effort, "課題文")
    assert args[:6] == ["-p", "課題文", "--model", model_id, "--effort", effort]
    assert claude_cli.resolve_effort(model_id, None) == "medium"


@pytest.mark.parametrize("effort_args", [[], ["--effort", "default"]])
def test_both_clis_select_default_only_for_haiku45(tmp_path, capsys, effort_args):
    assert cli.main(["run", "--model", "haiku45", *effort_args, "--dry-run"]) == 0
    output = capsys.readouterr().out
    assert MODEL in output and "effort: default" in output and "--effort" not in output
    assert spec_benchmark.main([
        "run", "--set", "set2", "--model", "haiku45", *effort_args,
        "--runs", "5", "--prompt-variant", "baseline", "--dry-run", "--results-dir", str(tmp_path / "results"),
    ]) == 0
    output = capsys.readouterr().out
    assert f"model={MODEL} effort=default" in output and "specs=3 runs_per_spec=5" in output
    assert not (tmp_path / "results").exists()


@pytest.mark.parametrize("tokens, ttl, price", [
    (TokenCounts(input=1_000_000), "1h", 1.00),
    (TokenCounts(output=1_000_000), "1h", 5.00),
    (TokenCounts(cache_read=1_000_000), "1h", 0.10),
    (TokenCounts(cache_write=1_000_000), "5m", 1.25),
    (TokenCounts(cache_write=1_000_000), "1h", 2.00),
])
def test_official_rates(tokens, ttl, price):
    assert cost_usd(MODEL, tokens, ttl) == pytest.approx(price)


@pytest.mark.parametrize("actual, status", [
    ([MODEL], "match"), ([MODEL + "-20251001"], "match"),
    (["claude-haiku-5-5"], "mismatch"), (["claude-sonnet-4-6"], "mismatch"),
    ([MODEL, "claude-opus-4-8"], "mismatch"), ([MODEL + "-fast"], "mismatch"), ([], "unverified"),
])
def test_actual_model_is_verified(actual, status):
    check = check_model({"model_usage": dict.fromkeys(actual, {})}, MODEL)
    assert check["status"] == status and check["actual_model_ids"] == sorted(actual)
    if status == "match":
        assert all(price_key(name) == MODEL for name in actual)


@pytest.mark.parametrize("cache_5m, cache_1h, expected", [(2000, 0, 0.00315), (0, 2000, 0.00465), (500, 1500, 0.004275)])
def test_ttl_breakdown_and_thinking_are_not_double_charged(cache_5m, cache_1h, expected):
    payload = {"type": "result", "result": "mock", "usage": {
        "output_tokens": 50, "output_tokens_details": {"thinking_tokens": 40},
        "cache_creation": {"ephemeral_5m_input_tokens": cache_5m, "ephemeral_1h_input_tokens": cache_1h},
    }, "modelUsage": {MODEL: {"inputTokens": 100, "outputTokens": 50,
                               "cacheReadInputTokens": 3000, "cacheCreationInputTokens": 2000}}}
    summary = claude_cli.summarize_run(claude_cli.CliRun(0, json.dumps(payload), "", 1, False))
    assert summary["thinking_tokens"] == 40
    tokens, cost = price_trial(summary, MODEL)
    assert tokens["output"] == 50
    assert cost["api_equivalent_usd"] == pytest.approx(expected)
    assert cost["cache_write_tokens_by_ttl"] == {"5m": cache_5m, "1h": cache_1h}
    assert cost["cache_write_ttl_assumed"] is None


@pytest.mark.parametrize("usage, per_model, expected", [
    ({"output_tokens_details": {"thinking_tokens": 20}}, {MODEL: {"thinkingTokens": 20}}, 20),
    ({"output_tokens_details": {"thinking_tokens": 0}}, {}, 0),
    ({}, {MODEL: {"thinkingTokens": 20}}, 20),
    ({}, {MODEL: {"thinkingTokens": 20}, "claude-opus-4-8": {"thinkingTokens": 30}}, 50),
    ({}, {MODEL: {"thinkingTokens": 20}, "claude-opus-4-8": {}}, None),
    ({}, {}, None),
    ({"output_tokens_details": {"thinking_tokens": -1}}, {}, None),
    ({"output_tokens_details": {"thinking_tokens": True}}, {}, None),
])
def test_thinking_reports_are_preserved_without_guessing(usage, per_model, expected):
    payload = {"type": "result", "usage": usage, "modelUsage": per_model}
    result = claude_cli.summarize_run(claude_cli.CliRun(0, json.dumps(payload), "", 1, False))
    assert result["thinking_tokens"] == expected
    assert result["usage"] == usage and result["model_usage"] == per_model


def test_fifteen_fake_trials_record_default_thinking_cost_and_report(tmp_path, fake_command, monkeypatch, capsys):
    monkeypatch.setattr(claude_cli, "find_claude_command", lambda: fake_command)
    monkeypatch.setenv("FAKE_CLAUDE_RESPONSE", '{"contradictions": []}')
    monkeypatch.setenv("FAKE_CLAUDE_THINKING_TOKENS", "20")
    monkeypatch.setenv("FAKE_CLAUDE_MODEL", MODEL + "-20251001")
    monkeypatch.setenv("MAX_THINKING_TOKENS", "12000")
    arglog = tmp_path / "args.jsonl"
    monkeypatch.setenv("FAKE_CLAUDE_ARGLOG", str(arglog))
    results = tmp_path / "results"
    assert spec_benchmark.main([
        "run", "--set", "set2", "--spec", "all", "--model", "haiku45", "--prompt-variant", "baseline",
        "--runs", "5", "--results-dir", str(results),
    ]) == 0
    capsys.readouterr()
    exp, = results.iterdir()
    meta = _read_json(exp / "experiment.json")
    assert meta["model"] == MODEL and meta["effort"] == "default" and meta["requested_trials"] == 15
    reasoning = meta["reasoning_settings"]
    assert reasoning["mode"] == "cli_default" and reasoning["effort_flag"] is None
    assert reasoning["thinking_budget_override"] is reasoning["effective_thinking_budget"] is None
    assert reasoning["environment"]["MAX_THINKING_TOKENS"] == "12000"
    assert meta["pricing_source"] == PRICING_SOURCE_URL and meta["pricing_checked_on"] == PRICING_CHECKED_ON
    records = [_read_json(path) for path in sorted(exp.glob("trial_*/trial.json"))]
    calls = [json.loads(line) for line in arglog.read_text(encoding="utf-8").splitlines()]
    assert len(records) == len(calls) == len({call["cwd"] for call in calls}) == 15
    for record, call in zip(records, calls):
        assert record["reasoning_settings"] == reasoning and record["effort"] == "default"
        assert record["spec"] in SET2_SPEC_NAMES and record["dataset_set"] == "set2"
        assert record["prompt_variant"] == "baseline"
        assert record["model_check"]["status"] == "match"
        assert record["model_check"]["actual_model_ids"] == [MODEL + "-20251001"]
        assert record["claude"]["thinking_tokens"] == 20 and record["tokens"]["output"] == 50
        assert record["cost"]["api_equivalent_usd"] == pytest.approx(0.00465)
        assert record["claude"]["cli_total_cost_usd"] == pytest.approx(0.000465)
        assert record["wall_seconds"] >= 0 and "--effort" not in call["argv"]
        assert call["argv"][1] == build_prompt(load_spec(record["spec"]))
        assert call["cwd_entries"] == [] and not Path(call["cwd"]).exists()
    summary = _read_json(exp / "summary.json")
    assert summary["completed_trials"] == 15 and summary["thinking_tokens"] == 300
    assert summary["api_equivalent_usd_mean"] == pytest.approx(0.00465)
    assert all(score["thinking_tokens"] == 100 for score in summary["by_spec"].values())
    # 過去形式の模擬結果を一緒に読み、保存料金や成績の再計算・上書きがないことを確認する。
    legacy = copy.deepcopy(summary)
    legacy.update(model="claude-haiku-5-5", effort="medium", actual_model_ids=["claude-haiku-5-5"])
    for key in ("reasoning_settings", "thinking_tokens"):
        legacy.pop(key)
    for score in legacy["by_spec"].values():
        score.pop("thinking_tokens")
    old = tmp_path / "legacy"
    old.mkdir()
    (old / "summary.json").write_text(json.dumps(legacy), encoding="utf-8")
    before = [(path / "summary.json").read_bytes() for path in (exp, old)]
    report = spec_benchmark.build_report([exp, old])
    assert MODEL in report and "claude-haiku-5-5" in report and "default" in report and "thinking_tokens" in report
    assert before == [(path / "summary.json").read_bytes() for path in (exp, old)]


def test_direct_unsupported_setting_fails_before_creating_results(tmp_path, fake_command):
    with pytest.raises(ValueError, match="Effort非対応"):
        spec_benchmark.run_benchmark([load_spec(SET2_SPEC_NAMES[0])], model_id=MODEL, model_label="haiku45",
                                     effort="high", runs=1, timeout=60, results_dir=tmp_path / "results",
                                     claude_command=fake_command)
    assert not (tmp_path / "results").exists()
