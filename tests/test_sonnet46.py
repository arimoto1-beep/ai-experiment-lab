import copy
import json
from collections import Counter
from pathlib import Path

import pytest

from ai_lab import claude_cli, cli, spec_benchmark
from ai_lab.experiment import check_model, price_trial
from ai_lab.pricing import PRICING_CHECKED_ON, PRICING_SOURCE_URL, TokenCounts, cost_usd, price_key
from ai_lab.spec_scoring import SET2_SPEC_NAMES, SPEC_NAMES, build_prompt, load_spec


MODEL = "claude-sonnet-4-6"


def _read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", ["sonnet46", MODEL])
def test_sonnet46_alias_and_formal_model_id(name):
    assert cli._resolve_model(name) == (MODEL, name)


@pytest.mark.parametrize("tokens, ttl, expected", [
    (TokenCounts(input=1_000_000), "1h", 3.00),
    (TokenCounts(output=1_000_000), "1h", 15.00),
    (TokenCounts(cache_read=1_000_000), "1h", 0.30),
    (TokenCounts(cache_write=1_000_000), "5m", 3.75),
    (TokenCounts(cache_write=1_000_000), "1h", 6.00),
])
def test_sonnet46_official_rates_including_long_context(tokens, ttl, expected):
    assert cost_usd(MODEL, tokens, ttl) == pytest.approx(expected)


@pytest.mark.parametrize("actual, status", [
    ([MODEL], "match"),
    ([MODEL + "-20260217"], "match"),
    (["claude-haiku-5-5"], "mismatch"),
    (["claude-opus-4-8"], "mismatch"),
    (["claude-sonnet-4-5"], "mismatch"),
    ([MODEL, "claude-haiku-5-5"], "mismatch"),
    ([MODEL + "-fast"], "mismatch"),
    ([], "unverified"),
])
def test_sonnet46_actual_model_verification(actual, status):
    checked = check_model({"model_usage": dict.fromkeys(actual, {})}, MODEL)
    assert checked["status"] == status
    assert checked["actual_model_ids"] == sorted(actual)
    assert checked["requested_model_id"] == MODEL
    if status == "match":
        assert all(price_key(name) == MODEL for name in actual)
        assert checked["unexpected_model_ids"] == []
    if status == "mismatch":
        assert checked["unexpected_model_ids"]


def test_other_sonnet_versions_and_unknown_variants_are_not_priced():
    for name in ("claude-sonnet-4-5", "claude-sonnet-4-60", MODEL + "-fast", MODEL + "-unknown"):
        assert price_key(name) is None
    _, cost = price_trial({"model_usage": {MODEL + "-unknown": {"inputTokens": 100}}}, MODEL)
    assert cost["api_equivalent_usd"] is None and cost["complete"] is False


@pytest.mark.parametrize("breakdown, expected", [
    ({"5m": 2000, "1h": 0}, 0.00945),
    ({"5m": 0, "1h": 2000}, 0.01395),
    ({"5m": 500, "1h": 1500}, 0.012825),
    (None, 0.01395),
])
def test_sonnet46_trial_cost_uses_reported_cache_ttl(breakdown, expected):
    reported = {
        "model_usage": {MODEL: {
            "inputTokens": 100, "outputTokens": 50,
            "cacheReadInputTokens": 3000, "cacheCreationInputTokens": 2000,
        }},
        "usage": {}, "num_turns": 1,
    }
    if breakdown is not None:
        reported["usage"]["cache_creation"] = {
            "ephemeral_5m_input_tokens": breakdown["5m"],
            "ephemeral_1h_input_tokens": breakdown["1h"],
        }
    tokens, cost = price_trial(reported, MODEL)
    assert tokens == {"input": 100, "output": 50, "cache_read": 3000, "cache_write": 2000}
    assert cost["api_equivalent_usd"] == pytest.approx(expected)
    assert cost["complete"] is True
    assert cost["cache_write_tokens_by_ttl"] == breakdown
    assert cost["cache_write_ttl_assumed"] == ("1h" if breakdown is None else None)
    assert bool(cost["notes"]) == (breakdown is None)
    assert cost["pricing_checked_on"] == PRICING_CHECKED_ON
    assert cost["pricing_source"] == PRICING_SOURCE_URL


def test_both_benchmark_clis_accept_sonnet46_high_without_model_calls(tmp_path, capsys):
    common = ["--model", "sonnet46", "--effort", "high", "--dry-run",
              "--results-dir", str(tmp_path / "results")]
    assert cli.main(["run", *common]) == 0
    output = capsys.readouterr().out
    assert f"--model {MODEL}" in output and "--effort high" in output
    assert spec_benchmark.main([
        "run", "--set", "set2", "--spec", "all", "--prompt-variant", "baseline", "--runs", "5", *common,
    ]) == 0
    output = capsys.readouterr().out
    assert f"model={MODEL} effort=high" in output and "prompt_variant=baseline" in output
    assert "specs=3 runs_per_spec=5" in output
    assert all(name in output for name in SET2_SPEC_NAMES)
    assert all(name not in output for name in SPEC_NAMES)
    assert not (tmp_path / "results").exists()


def test_set2_sonnet46_fifteen_mock_trials_keep_recording_and_isolation(tmp_path, fake_command, monkeypatch, capsys):
    monkeypatch.setattr(claude_cli, "find_claude_command", lambda: fake_command)
    monkeypatch.setenv("FAKE_CLAUDE_RESPONSE", '{"contradictions": []}')
    arglog = tmp_path / "args.jsonl"
    monkeypatch.setenv("FAKE_CLAUDE_ARGLOG", str(arglog))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key-must-not-reach-cli")
    monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
    results = tmp_path / "results"
    assert spec_benchmark.main([
        "run", "--set", "set2", "--spec", "all", "--model", "sonnet46", "--effort", "high",
        "--prompt-variant", "baseline", "--runs", "5", "--results-dir", str(results),
    ]) == 0
    capsys.readouterr()
    exp, = results.iterdir()
    meta = _read_json(exp / "experiment.json")
    assert meta["model"] == MODEL and meta["effort"] == "high" and meta["prompt_variant"] == "baseline"
    assert meta["runs_per_spec"] == 5 and meta["requested_trials"] == 15
    assert meta["specs"] == list(SET2_SPEC_NAMES)
    assert set(meta["spec_sets"].values()) == {"set2"}
    assert meta["auth_method"] == "claude.ai"
    assert meta["pricing_checked_on"] == PRICING_CHECKED_ON
    records = [_read_json(path) for path in sorted(exp.glob("trial_*/trial.json"))]
    assert len(records) == 15
    assert Counter(record["spec"] for record in records) == dict.fromkeys(SET2_SPEC_NAMES, 5)
    calls = [json.loads(line) for line in arglog.read_text(encoding="utf-8").splitlines()]
    assert len(calls) == len({call["cwd"] for call in calls}) == 15
    for call, record in zip(calls, records):
        args = call["argv"]
        case = load_spec(record["spec"])
        assert args[1] == build_prompt(case, "baseline")
        assert all(item["reason"] not in args[1] for item in case.answer_key["contradictions"])
        assert args[args.index("--model") + 1] == MODEL
        assert args[args.index("--effort") + 1] == "high"
        assert args[args.index("--tools") + 1] == ""
        assert args[args.index("--disallowedTools") + 1] == "*"
        assert "--safe-mode" in args and "--no-session-persistence" in args
        assert call["cwd_entries"] == [] and not Path(call["cwd"]).exists()
        assert not any(call["env"].values())
        assert record["model_check"]["status"] == "match"
        assert record["model_check"]["actual_model_ids"] == [MODEL]
        assert record["effort"] == "high" and record["prompt_variant"] == "baseline"
        assert record["dataset_set"] == "set2" and 1 <= record["trial"] <= 5
        assert record["wall_seconds"] >= 0
        assert record["tokens"] == {"input": 100, "output": 50, "cache_read": 3000, "cache_write": 2000}
        assert record["cost"]["api_equivalent_usd"] == pytest.approx(0.01395)
        assert record["claude"]["cli_total_cost_usd"] == pytest.approx(0.000465)
    summary = _read_json(exp / "summary.json")
    assert summary["completed_trials"] == 15 and summary["fn"] == 75 and summary["f1"] == 0
    assert summary["api_equivalent_usd_mean"] == pytest.approx(0.01395)
    assert summary["model_mismatch_trials"] == summary["model_unverified_trials"] == 0
    assert all(scores["completed_trials"] == 5 for scores in summary["by_spec"].values())
    assert spec_benchmark.main(["report", str(exp)]) == 0
    report = capsys.readouterr().out
    assert MODEL in report and "0.013950" in report and "mean_sec" in report


@pytest.mark.parametrize("actual, status, expected_cost", [
    ("claude-opus-4-8", "mismatch", 0.02325),
    (None, "unverified", None),
])
def test_sonnet46_model_problems_are_recorded_and_priced_by_actual_id(
    tmp_path, fake_command, monkeypatch, actual, status, expected_cost,
):
    monkeypatch.setenv("FAKE_CLAUDE_RESPONSE", '{"contradictions": []}')
    if actual is None:
        monkeypatch.setenv("FAKE_CLAUDE_NO_MODEL_USAGE", "1")
    else:
        monkeypatch.setenv("FAKE_CLAUDE_MODEL", actual)
    exp = spec_benchmark.run_benchmark(
        [load_spec(SET2_SPEC_NAMES[0])], model_id=MODEL, model_label="sonnet46", effort="high",
        runs=1, timeout=60, results_dir=tmp_path / "results", claude_command=fake_command, log=lambda _: None,
    )
    record = _read_json(exp / "trial_001" / "trial.json")
    assert record["model_check"]["status"] == status
    cost = record["cost"]
    if expected_cost is None:
        assert cost["api_equivalent_usd"] is None and cost["complete"] is False
    else:
        assert cost["api_equivalent_usd"] == pytest.approx(expected_cost)
        assert list(cost["rates_per_mtok"]) == [actual]
    summary = _read_json(exp / "summary.json")
    assert summary["model_mismatch_trials" if actual else "model_unverified_trials"] == 1


def test_report_combines_sonnet46_and_legacy_results_without_repricing(tmp_path, fake_command, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_RESPONSE", '{"contradictions": []}')
    sonnet = spec_benchmark.run_benchmark(
        [load_spec(SET2_SPEC_NAMES[0])], model_id=MODEL, model_label="sonnet46", effort="high",
        runs=1, timeout=60, results_dir=tmp_path / "results", claude_command=fake_command, log=lambda _: None,
    )
    dirs = [sonnet]
    for model, effort, stored_cost in (("claude-haiku-5-5", "medium", 0.777),
                                       ("claude-haiku-5-5", "max", 0.778), ("claude-opus-4-8", "high", 0.888)):
        legacy = copy.deepcopy(_read_json(sonnet / "summary.json"))
        legacy.update(model=model, effort=effort, pricing_checked_on="2026-10-11", actual_model_ids=[model])
        for key in ("prompt_variant", "spec_sets", "by_set"):
            del legacy[key]
        # 過去形式の模擬結果。保存料金を優先することを、現行単価と違う値で確認する。
        for scores in (legacy, *legacy["by_spec"].values()):
            scores["api_equivalent_usd_mean"] = scores["api_equivalent_usd_total"] = stored_cost
        path = tmp_path / f"legacy_{model}_{effort}"
        path.mkdir()
        (path / "summary.json").write_text(json.dumps(legacy), encoding="utf-8")
        dirs.append(path)
    before = [(path / "summary.json").read_bytes() for path in dirs]
    report = spec_benchmark.build_report(dirs)
    assert all(model in report for model in (MODEL, "claude-haiku-5-5", "claude-opus-4-8"))
    assert all(value in report for value in ("0.013950", "0.777000", "0.778000", "0.888000"))
    assert "set2" in report and "baseline" in report and "mean_api_usd" in report
    assert [(path / "summary.json").read_bytes() for path in dirs] == before
