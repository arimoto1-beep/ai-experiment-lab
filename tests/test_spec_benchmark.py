import hashlib
import json
from pathlib import Path

import pytest

from ai_lab import claude_cli, spec_benchmark
from ai_lab.spec_scoring import SPEC_NAMES, build_prompt, load_spec


def _json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _correct_response(case):
    return json.dumps({"contradictions": [
        {"requirement_ids": item["requirement_ids"], "reason": "模擬回答の理由"}
        for item in case.answer_key["contradictions"]
    ]})


def _run(tmp_path, fake_command, cases, **overrides):
    values = dict(model_id="claude-haiku-5-5", model_label="haiku", effort="medium", runs=1,
                  timeout=60, results_dir=tmp_path / "results", claude_command=fake_command, log=lambda _: None)
    values.update(overrides)
    return spec_benchmark.run_benchmark(cases, **values)


@pytest.mark.parametrize("name", SPEC_NAMES)
@pytest.mark.parametrize("model, label, effort, expected_cost", [
    ("claude-haiku-5-5", "haiku", "medium", 0.000465),
    ("claude-haiku-5-5", "haiku", "max", 0.000465),
    ("claude-opus-4-8", "opus48", "high", 0.02325),
])
def test_existing_cli_and_pricing_are_reused_for_all_nine_settings(
    tmp_path, fake_command, monkeypatch, name, model, label, effort, expected_cost,
):
    case = load_spec(name)
    monkeypatch.setenv("FAKE_CLAUDE_RESPONSE", _correct_response(case))
    log = tmp_path / "args.jsonl"
    monkeypatch.setenv("FAKE_CLAUDE_ARGLOG", str(log))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-reach-cli")
    monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
    exp = _run(tmp_path, fake_command, [case], model_id=model, model_label=label, effort=effort)
    call = json.loads(log.read_text(encoding="utf-8").strip())
    args = call["argv"]
    assert args[args.index("--model") + 1] == model
    assert args[args.index("--effort") + 1] == effort
    assert args[args.index("--tools") + 1] == ""
    assert args[args.index("--disallowedTools") + 1] == "*"
    assert "--safe-mode" in args and "--no-session-persistence" in args
    assert "--bare" not in args
    assert call["cwd_entries"] == []
    assert not Path(call["cwd"]).exists()
    assert not Path(call["cwd"]).is_relative_to(exp)
    assert call["env"]["ANTHROPIC_API_KEY"] is False
    assert call["env"]["CLAUDE_CODE_USE_BEDROCK"] is False
    assert args[1] == build_prompt(case)
    for answer in case.answer_key["contradictions"]:
        assert answer["reason"] not in args[1]
    trial = _json(exp / "trial_001" / "trial.json")
    assert trial["spec"] == name and trial["model"] == model and trial["effort"] == effort
    assert trial["model_check"]["status"] == "match"
    assert trial["scoring"]["metrics"]["f1"] == 1
    assert trial["tokens"] == {"input": 100, "output": 50, "cache_read": 3000, "cache_write": 2000}
    assert trial["cost"]["api_equivalent_usd"] == pytest.approx(expected_cost)
    assert trial["claude"]["cli_total_cost_usd"] == pytest.approx(0.000465)
    assert trial["wall_seconds"] >= 0
    review = _json(exp / "trial_001" / "reason_review.json")
    assert len(review["contradictions"]) == 4
    assert all(item["reason_verdict"] is None for item in review["contradictions"])
    assert (exp / "trial_001" / "answer.txt").exists()
    meta = _json(exp / "experiment.json")
    assert meta["input_hashes"][name] == case.hashes
    assert meta["comparison_basis"] == "model_and_effort"
    assert _json(exp / "snapshots" / f"{name}.answer_key.json") == case.answer_key
    for snapshot, original in ((f"{name}.md", f"specs/{name}.md"), (f"{name}.answer_key.json", f"answer_keys/{name}.json")):
        assert hashlib.sha256((exp / "snapshots" / snapshot).read_bytes()).hexdigest() == case.hashes[original]
    summary = _json(exp / "summary.json")
    assert summary["api_equivalent_usd_mean"] == pytest.approx(expected_cost)
    assert summary["by_spec"][name]["f1"] == 1


def test_all_specs_and_repeated_trials_are_independent_and_reportable(tmp_path, fake_command, monkeypatch):
    cases = [load_spec(name) for name in SPEC_NAMES]
    monkeypatch.setenv("FAKE_CLAUDE_RESPONSE", _correct_response(cases[0]))
    log = tmp_path / "args.jsonl"
    monkeypatch.setenv("FAKE_CLAUDE_ARGLOG", str(log))
    exp = _run(tmp_path, fake_command, cases, runs=2)
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert len(calls) == len({call["cwd"] for call in calls}) == 6
    assert all(call["cwd_entries"] == [] for call in calls)
    summary = _json(exp / "summary.json")
    assert summary["completed_trials"] == 6 and summary["tp"] == 24
    assert summary["f1"] == summary["mean_f1"] == 1
    assert summary["missed_critical"] == summary["invalid_responses"] == 0
    report = spec_benchmark.build_report([exp])
    assert all(name in report for name in SPEC_NAMES)
    assert "TP" in report and "critical_missed" in report and "mean_api_usd" in report
    assert "reason_review.json" in report


@pytest.mark.parametrize("mode", ["bad_json", "exit_error", "timeout", "unparsed"])
def test_failure_is_saved_and_penalized(tmp_path, fake_command, monkeypatch, mode):
    case = load_spec("access_control")
    monkeypatch.setenv("FAKE_CLAUDE_RESPONSE", _correct_response(case))
    timeout = 60
    if mode == "bad_json":
        monkeypatch.setenv("FAKE_CLAUDE_RESPONSE", "broken JSON")
    elif mode == "exit_error":
        monkeypatch.setenv("FAKE_CLAUDE_EXIT", "1")
    elif mode == "timeout":
        monkeypatch.setenv("FAKE_CLAUDE_SLEEP", "10")
        timeout = 1
    else:
        monkeypatch.setenv("FAKE_CLAUDE_OUTPUT", "text")
    exp = _run(tmp_path, fake_command, [case], timeout=timeout)
    trial = _json(exp / "trial_001" / "trial.json")
    assert trial["scoring"]["status"] != "ok" and trial["scoring"]["error"]
    assert trial["scoring"]["metrics"]["tp"] == 0
    assert trial["scoring"]["metrics"]["fn"] == 4
    assert trial["scoring"]["missed_critical"] == 3
    summary = _json(exp / "summary.json")
    assert summary["invalid_responses"] == 1 and summary["mean_f1"] == 0
    if mode in ("timeout", "unparsed"):
        assert trial["cost"]["api_equivalent_usd"] is None
        assert summary["api_equivalent_usd_mean"] is None
    assert (exp / "trial_001" / "claude_stdout.txt").exists()
    assert (exp / "trial_001" / "claude_stderr.txt").exists()


@pytest.mark.parametrize("missing_model", [False, True])
def test_actual_model_problems_are_visible(tmp_path, fake_command, monkeypatch, missing_model):
    case = load_spec("order_fulfillment")
    monkeypatch.setenv("FAKE_CLAUDE_RESPONSE", _correct_response(case))
    if missing_model:
        monkeypatch.setenv("FAKE_CLAUDE_NO_MODEL_USAGE", "1")
    else:
        monkeypatch.setenv("FAKE_CLAUDE_MODEL", "claude-opus-4-8")
    exp = _run(tmp_path, fake_command, [case])
    trial = _json(exp / "trial_001" / "trial.json")
    assert trial["model_check"]["status"] == ("unverified" if missing_model else "mismatch")
    summary = _json(exp / "summary.json")
    assert summary["model_unverified_trials" if missing_model else "model_mismatch_trials"] == 1


def test_subscription_authentication_is_required_before_writing_results(tmp_path, fake_command, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_AUTH", "api_key")
    with pytest.raises(RuntimeError, match="サブスクリプション"):
        _run(tmp_path, fake_command, [load_spec("order_fulfillment")])
    assert not (tmp_path / "results").exists()


@pytest.mark.parametrize("model, effort, model_id", [
    ("haiku", "medium", "claude-haiku-5-5"),
    ("haiku", "max", "claude-haiku-5-5"),
    ("opus48", "high", "claude-opus-4-8"),
])
def test_cli_dry_run_validates_three_conditions_without_model_calls(tmp_path, capsys, model, effort, model_id):
    assert spec_benchmark.main(["run", "--model", model, "--effort", effort, "--runs", "3",
                                "--results-dir", str(tmp_path / "results"), "--dry-run"]) == 0
    output = capsys.readouterr().out
    assert model_id in output and f"effort={effort}" in output
    assert "specs=3 runs_per_spec=3" in output
    assert not (tmp_path / "results").exists()


def test_validate_command_is_read_only_and_does_not_call_a_model(capsys):
    assert spec_benchmark.main(["validate"]) == 0
    output = capsys.readouterr().out
    assert all(name in output for name in SPEC_NAMES)


def test_interrupt_keeps_completed_trials_and_summary(tmp_path, monkeypatch):
    case = load_spec("order_fulfillment")
    monkeypatch.setattr(claude_cli, "preflight", lambda *_: {"version": "fake", "auth_method": "claude.ai"})
    calls = 0

    def invoke(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise KeyboardInterrupt
        payload = {"type": "result", "result": _correct_response(case), "is_error": False}
        return claude_cli.CliRun(0, json.dumps(payload), "", 1, False)

    monkeypatch.setattr(claude_cli, "invoke", invoke)
    with pytest.raises(KeyboardInterrupt):
        _run(tmp_path, ["fake"], [case], runs=2)
    exp = next((tmp_path / "results").iterdir())
    assert _json(exp / "summary.json")["completed_trials"] == 1
    assert _json(exp / "trial_001" / "trial.json")["scoring"]["metrics"]["f1"] == 1


def test_nested_cli_run_is_refused_before_locating_a_real_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CLAUDECODE", "1")
    assert spec_benchmark.main(["run", "--results-dir", str(tmp_path / "results")]) == 1
    assert "入れ子" in capsys.readouterr().err
    assert not (tmp_path / "results").exists()


def test_report_refuses_comparison_with_a_different_answer_key(tmp_path, fake_command, monkeypatch):
    case = load_spec("order_fulfillment")
    monkeypatch.setenv("FAKE_CLAUDE_RESPONSE", _correct_response(case))
    original = _run(tmp_path, fake_command, [case])
    changed = tmp_path / "changed"
    changed.mkdir()
    summary = _json(original / "summary.json")
    summary["input_hashes"][case.name]["answer_keys/order_fulfillment.json"] = "different_hash"
    (changed / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(ValueError, match="異なる固定データ"):
        spec_benchmark.build_report([original, changed])


def test_cli_report_reads_saved_results(tmp_path, fake_command, monkeypatch, capsys):
    case = load_spec("order_fulfillment")
    monkeypatch.setenv("FAKE_CLAUDE_RESPONSE", _correct_response(case))
    exp = _run(tmp_path, fake_command, [case])
    assert spec_benchmark.main(["report", str(exp)]) == 0
    output = capsys.readouterr().out
    assert "100.0%" in output and "mean_F1" in output and "order_fulfillment" in output


def test_full_cli_workflow_compares_three_conditions_with_mock_responses(tmp_path, fake_command, monkeypatch, capsys):
    monkeypatch.setattr(claude_cli, "find_claude_command", lambda: fake_command)
    monkeypatch.setenv("FAKE_CLAUDE_RESPONSE", _correct_response(load_spec("order_fulfillment")))
    results = tmp_path / "results"
    for model, effort in (("haiku", "medium"), ("haiku", "max"), ("opus48", "high")):
        assert spec_benchmark.main([
            "run", "--spec", "all", "--model", model, "--effort", effort,
            "--runs", "1", "--results-dir", str(results),
        ]) == 0
    experiments = sorted(results.iterdir())
    assert len(experiments) == 3
    assert all(_json(path / "summary.json")["completed_trials"] == 3 for path in experiments)
    capsys.readouterr()
    assert spec_benchmark.main(["report", *(str(path) for path in experiments)]) == 0
    report = capsys.readouterr().out
    assert "claude-haiku-5-5" in report and "claude-opus-4-8" in report
    assert all(effort in report for effort in ("medium", "max", "high"))
