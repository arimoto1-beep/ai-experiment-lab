import hashlib
import json
import shutil

import pytest

from ai_lab import spec_benchmark
from ai_lab.spec_scoring import SET2_DATASET_ROOT, SET2_SPEC_NAMES, SPEC_NAMES, build_prompt, load_spec, score_response


def _json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _response(entries):
    # conditionは正解側専用。モデルの回答契約を変えない。
    return json.dumps({"contradictions": [
        {"requirement_ids": item["requirement_ids"], "reason": item["reason"]} for item in entries
    ]})


@pytest.mark.parametrize("name", SET2_SPEC_NAMES)
def test_new_data_is_fixed_complete_and_not_in_the_prompt(name):
    case = load_spec(name)
    assert case.dataset_set == "set2"
    assert case.requirement_ids == frozenset(f"R{index:02d}" for index in range(1, 29))
    gold = case.answer_key["contradictions"]
    assert len(gold) == 5
    assert sorted(len(item["requirement_ids"]) for item in gold) == [2, 2, 2, 3, 4]
    assert all(item["condition"].strip() for item in gold)
    assert len(case.answer_key["insufficient_information"]) == 2
    assert len(case.answer_key["non_contradictions"]) == 4
    assert len(case.answer_key["normal_requirement_ids"]) == 5
    prompt = build_prompt(case)
    assert case.statement.strip() in prompt
    assert "answer_keys" not in prompt and "REVIEW.md" not in prompt
    assert all(item["condition"] not in prompt and item["reason"] not in prompt for item in gold)


@pytest.mark.parametrize("name", SET2_SPEC_NAMES)
def test_existing_scoring_rules_apply_to_the_new_set(name):
    case = load_spec(name)
    entries = case.answer_key["contradictions"]
    perfect = score_response(_response(entries), case)
    assert perfect["status"] == "ok"
    assert perfect["metrics"] == {"tp": 5, "fp": 0, "fn": 0, "precision": 1, "recall": 1, "f1": 1}
    assert perfect["missed_critical"] == 0
    assert all(item["reason_verdict"] is None for item in perfect["reason_review"])
    critical = next(item for item in entries if item["severity"] == "critical")
    partial = [item for item in entries if item is not critical]
    partial.append(case.answer_key["non_contradictions"][0])
    reduced = score_response(_response(partial), case)
    assert reduced["metrics"]["tp"] == 4
    assert reduced["metrics"]["fp"] == reduced["metrics"]["fn"] == reduced["missed_critical"] == 1
    for metric in ("precision", "recall", "f1"):
        assert reduced["metrics"][metric] == pytest.approx(0.8)
    invalid = score_response('```json\n{"contradictions": []}\n```', case)
    assert invalid["status"] == "invalid_json" and invalid["metrics"]["f1"] == 0
    assert invalid["metrics"]["fn"] == 5


@pytest.mark.parametrize("name", SET2_SPEC_NAMES)
@pytest.mark.parametrize("model, label, effort, cost", [
    ("claude-haiku-5-5", "haiku", "medium", 0.000465),
    ("claude-haiku-5-5", "haiku", "max", 0.000465),
    ("claude-opus-4-8", "opus48", "high", 0.02325),
])
def test_new_specs_reuse_the_cli_isolation_and_recording(tmp_path, fake_command, monkeypatch, name, model, label, effort, cost):
    case = load_spec(name)
    monkeypatch.setenv("FAKE_CLAUDE_RESPONSE", _response(case.answer_key["contradictions"]))
    arglog = tmp_path / "args.jsonl"
    monkeypatch.setenv("FAKE_CLAUDE_ARGLOG", str(arglog))
    exp = spec_benchmark.run_benchmark([case], model_id=model, model_label=label, effort=effort,
                                       runs=1, timeout=60, results_dir=tmp_path / "results",
                                       claude_command=fake_command, log=lambda _: None)
    call = json.loads(arglog.read_text(encoding="utf-8").strip())
    args = call["argv"]
    assert args[1] == build_prompt(case) and call["cwd_entries"] == []
    assert args[args.index("--tools") + 1] == ""
    assert args[args.index("--disallowedTools") + 1] == "*"
    assert args[args.index("--model") + 1] == model
    assert args[args.index("--effort") + 1] == effort
    record = _json(exp / "trial_001" / "trial.json")
    assert record["dataset_set"] == "set2" and record["spec"] == name
    assert record["model_check"]["status"] == "match"
    assert record["scoring"]["metrics"]["tp"] == 5
    assert record["cost"]["api_equivalent_usd"] == pytest.approx(cost)
    assert record["claude"]["cli_total_cost_usd"] == pytest.approx(0.000465)
    assert record["wall_seconds"] >= 0 and record["tokens"]["input"] == 100
    summary = _json(exp / "summary.json")
    assert summary["spec_sets"] == {name: "set2"}
    assert summary["by_set"]["set2"]["tp"] == 5
    for snapshot, relative in ((f"{name}.md", f"specs/{name}.md"), (f"{name}.answer_key.json", f"answer_keys/{name}.json")):
        assert hashlib.sha256((exp / "snapshots" / snapshot).read_bytes()).hexdigest() == case.hashes[relative]


@pytest.mark.parametrize("model,effort", [("haiku", "medium"), ("haiku", "max"), ("opus48", "high")])
def test_cli_can_select_only_the_new_three_specs(tmp_path, capsys, model, effort):
    assert spec_benchmark.main(["run", "--set", "set2", "--spec", "all", "--model", model, "--effort", effort,
                                "--runs", "3", "--dry-run", "--results-dir", str(tmp_path / "results")]) == 0
    output = capsys.readouterr().out
    assert all(name in output for name in SET2_SPEC_NAMES)
    assert all(name not in output for name in SPEC_NAMES)
    assert "specs=3 runs_per_spec=3" in output
    assert not (tmp_path / "results").exists()


def test_default_selection_still_uses_only_the_original_set(capsys):
    assert spec_benchmark.main(["run", "--dry-run"]) == 0
    output = capsys.readouterr().out
    assert all(name in output for name in SPEC_NAMES)
    assert all(name not in output for name in SET2_SPEC_NAMES)


def test_new_single_spec_can_be_selected_without_a_set_switch(capsys):
    assert spec_benchmark.main(["run", "--spec", "subscription_billing", "--dry-run"]) == 0
    assert "specs=1" in capsys.readouterr().out


def test_mismatched_set_and_spec_are_rejected(capsys):
    assert spec_benchmark.main(["run", "--set", "set2", "--spec", "order_fulfillment", "--dry-run"]) == 1
    assert "所属が一致" in capsys.readouterr().err


def test_new_set_validate_is_read_only(capsys):
    assert spec_benchmark.main(["validate", "--set", "set2"]) == 0
    output = capsys.readouterr().out
    assert all(name in output for name in SET2_SPEC_NAMES)
    assert all(name not in output for name in SPEC_NAMES)


def test_report_distinguishes_legacy_results_and_new_set(tmp_path, fake_command, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_RESPONSE", '{"contradictions": []}')
    dirs = []
    for name in ("order_fulfillment", "subscription_billing"):
        exp = spec_benchmark.run_benchmark([load_spec(name)], model_id="claude-haiku-5-5", model_label="haiku", effort="medium",
                                           runs=1, timeout=60, results_dir=tmp_path / "results", claude_command=fake_command, log=lambda _: None)
        if name == "order_fulfillment":
            # 過去形式を模擬するだけで、保存済みの実験ファイルは変更しない。
            summary = _json(exp / "summary.json")
            del summary["spec_sets"]
            del summary["by_set"]
            (exp / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        dirs.append(exp)
    report = spec_benchmark.build_report(dirs)
    assert "set1" in report and "set2" in report
    assert "order_fulfillment" in report and "subscription_billing" in report


def test_mixed_cases_are_aggregated_separately_by_set(tmp_path, fake_command, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_RESPONSE", '{"contradictions": []}')
    cases = [load_spec("order_fulfillment"), load_spec("subscription_billing")]
    exp = spec_benchmark.run_benchmark(cases, model_id="claude-haiku-5-5", model_label="haiku", effort="medium",
                                       runs=1, timeout=60, results_dir=tmp_path / "results", claude_command=fake_command, log=lambda _: None)
    by_set = _json(exp / "summary.json")["by_set"]
    assert by_set["set1"]["fn"] == 4 and by_set["set2"]["fn"] == 5
    assert by_set["set1"]["completed_trials"] == by_set["set2"]["completed_trials"] == 1


@pytest.mark.parametrize("relative", ["specs/subscription_billing.md", "answer_keys/subscription_billing.json"])
def test_new_fixed_files_cannot_silently_change(tmp_path, relative):
    root = tmp_path / "dataset"
    shutil.copytree(SET2_DATASET_ROOT, root)
    target = root / relative
    target.write_bytes(target.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="SHA256"):
        load_spec("subscription_billing", root)
