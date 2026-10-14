import csv
import hashlib
import json
from pathlib import Path

import pytest

from ai_lab import spec_rescore
from ai_lab.spec_scoring import SET2_SPEC_NAMES, load_spec, score_response


def _response(case, information=True):
    answer = {"contradictions": [{"requirement_ids": item["requirement_ids"], "reason": item["reason"]}
                                 for item in case.answer_key["contradictions"]]}
    if information:
        answer["insufficient_information"] = [
            {"requirement_ids": item["requirement_ids"], "reason": item["reason"]}
            for item in case.answer_key["insufficient_information"]
        ]
    return json.dumps(answer, ensure_ascii=False)


def _write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _saved_experiment(root, model, effort, *, runs=5, variant=None, names=SET2_SPEC_NAMES, suffix=""):
    exp = root / f"saved_{model}_{effort}_{variant or 'baseline'}{suffix}"
    exp.mkdir(parents=True)
    cases = [load_spec(name) for name in names]
    meta = {"benchmark": "spec_contradictions", "model": model, "effort": effort,
            "specs": list(names), "input_hashes": {case.name: case.hashes for case in cases},
            "spec_sets": {case.name: case.dataset_set for case in cases}, "runs_per_spec": runs}
    if variant is not None:
        meta["prompt_variant"] = variant
    _write_json(exp / "experiment.json", meta)
    index = 0
    for case in cases:
        for trial_index in range(1, runs + 1):
            index += 1
            trial_dir = exp / f"trial_{index:03d}"
            trial_dir.mkdir()
            text = "```json\r\n" + _response(case) + "\r\n```"
            (trial_dir / "answer.txt").write_bytes(text.encode("utf-8"))
            record = {"model": model, "effort": effort, "spec": case.name, "trial": trial_index,
                      "dataset_set": case.dataset_set, "scoring": score_response(text, case),
                      "claude": {"status": "ok"}, "wall_seconds": 10.0 + trial_index,
                      "cost": {"complete": True, "api_equivalent_usd": 0.12345},
                      "model_check": {"status": "match", "actual_model_ids": [model]}}
            if variant is not None:
                record["prompt_variant"] = variant
            _write_json(trial_dir / "trial.json", record)
            _write_json(trial_dir / "reason_review.json", {"original": True})
    _write_json(exp / "summary.json", {"original": True, "completed_trials": index})
    return exp


@pytest.fixture
def saved_results(tmp_path):
    root = tmp_path / "results"
    for model, effort in spec_rescore.CONDITIONS:
        _saved_experiment(root, model, effort, variant="baseline" if "sonnet" in model else None)
    return root


@pytest.mark.parametrize("text", ['{"contradictions": []}', ' \r\n{"contradictions": []}\r\n ',
                                '{"contradictions": [], "insufficient_information": []}'])
def test_valid_json_is_not_changed(text):
    result = spec_rescore.normalize_answer(text)
    assert result["text"] == text and result["original_json_valid"] is True
    assert result["fence_removed"] is result["fence_recovered"] is result["normalized_unparseable"] is False
    assert result["json_error"] is None


@pytest.mark.parametrize("text", [
    '```json\n{"contradictions": []}\n```',
    '```\n{"contradictions": []}\n```',
    ' \r\n```json\r\n{"contradictions": []}\r\n```\r\n ',
    '````json\n{"contradictions": []}\n````',
    '~~~json\n{"contradictions": []}\n~~~',
])
def test_only_whole_single_json_or_unlabelled_fence_is_removed(text):
    result = spec_rescore.normalize_answer(text)
    assert result["original_json_valid"] is False and result["normalized_unparseable"] is False
    assert result["fence_removed"] is result["fence_recovered"] is True
    assert json.loads(result["text"]) == {"contradictions": []}
    assert score_response(result["text"], load_spec(SET2_SPEC_NAMES[0]))["status"] == "ok"


@pytest.mark.parametrize("text", [
    '回答です\n{"contradictions": []}',
    '{"contradictions": []}\n以上です',
    '回答です\n```json\n{"contradictions": []}\n```',
    '```json\n{"contradictions": []}\n```\n以上です',
    '```json\n{"contradictions": []}\n```\n```json\n{"contradictions": []}\n```',
    '````json\n```json\n{"contradictions": []}\n```\n````',
    '```python\n{"contradictions": []}\n```',
    '```json extra\n{"contradictions": []}\n```',
    '```json {"contradictions": []}```',
    '```json\n{"contradictions": []}',
    '````json\n{"contradictions": []}\n```',
    '```json\n{"contradictions": []}\n~~~',
])
def test_prose_multiple_blocks_and_other_languages_are_not_extracted(text):
    result = spec_rescore.normalize_answer(text)
    assert result["text"] == text and result["fence_removed"] is False
    assert result["fence_recovered"] is False and result["normalized_unparseable"] is True


@pytest.mark.parametrize("body", ['{"contradictions": [}', '{"contradictions": [],}',
                                '{"contradictions": [], "contradictions": []}',
                                '{"contradictions": [], "value": NaN}', '{"contradictions": []'])
def test_invalid_json_is_never_repaired(body):
    result = spec_rescore.normalize_answer("```json\n" + body + "\n```")
    assert result["fence_removed"] is True and result["fence_recovered"] is False
    assert result["normalized_unparseable"] is True and result["json_error"]
    assert result["text"].rstrip("\n") == body
    assert score_response(result["text"], load_spec(SET2_SPEC_NAMES[0]))["status"] == "invalid_json"


@pytest.mark.parametrize("body", ['[]', '{}', '{"contradictions": "none"}',
                                '{"contradictions":[{"requirement_ids":["R01","R99"],"reason":"理由"}]}',
                                '{"contradictions":[],"extra":true}'])
def test_json_recovery_does_not_bypass_existing_schema(body):
    result = spec_rescore.normalize_answer("```json\n" + body + "\n```")
    score = score_response(result["text"], load_spec(SET2_SPEC_NAMES[0]))
    assert result["fence_recovered"] is True and result["normalized_unparseable"] is False
    assert score["status"] == "invalid_schema" and score["metrics"]["f1"] == 0


def test_sixty_trials_use_identical_rules_preserve_strict_and_keep_information_separate(saved_results):
    _saved_experiment(saved_results, "claude-haiku-5-5", "medium", variant="minimality", runs=1)
    _saved_experiment(saved_results, "claude-haiku-5-5", "medium", runs=1, names=("order_fulfillment",), suffix="_set1")
    analysis = spec_rescore.analyze_saved(saved_results)
    assert analysis["trial_count"] == 60 and len(analysis["summary"]) == 16
    for record in analysis["trials"]:
        original = json.loads(Path(record["trial_file"]).read_text(encoding="utf-8"))
        assert record["strict"] == original["scoring"]
        assert record["strict"]["status"] == "invalid_json" and record["strict"]["metrics"]["f1"] == 0
        assert record["normalized"]["status"] == "ok" and record["normalized"]["metrics"]["f1"] == 1
        assert record["fence_recovered"] is True and record["original_json_valid"] is False
        assert record["dataset_set"] == "set2" and record["prompt_variant"] == "baseline"
        assert record["information"]["metrics"]["tp"] == 2
        assert record["normalized"]["metrics"]["tp"] == 5
    for row in analysis["summary"]:
        runs = 15 if row["spec"] == "ALL" else 5
        assert row["trials"] == row["fence_recovered"] == row["normalized_perfect"] == runs
        assert row["fence_recovery_rate"] == row["normalized_f1"] == row["information_f1"] == 1
        assert row["strict_format_compliance_rate"] == row["strict_f1"] == 0
        assert row["normalized_tp"] == 5 * runs and row["information_tp"] == 2 * runs
        assert row["mean_wall_seconds"] == 13.0
        assert row["mean_api_equivalent_usd"] == pytest.approx(0.12345)


def test_csv_report_and_analysis_are_separate_and_sources_are_unchanged(saved_results, tmp_path, capsys):
    files = sorted(path for path in saved_results.rglob("*") if path.is_file())
    before = [(str(path), hashlib.sha256(path.read_bytes()).hexdigest()) for path in files]
    output = tmp_path / "analysis"
    assert spec_rescore.main(["--results-dir", str(saved_results), "--output-dir", str(output)]) == 0
    assert "60試行" in capsys.readouterr().out
    assert sorted(path.name for path in output.iterdir()) == ["analysis.json", "report.md", "summary.csv", "trials.csv"]
    with (output / "trials.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 60 and all(row["normalized_f1"] == "1.0" for row in rows)
    assert all(row["strict_f1"] == "0.0" and row["fence_recovered"] == "True" for row in rows)
    assert all(row["answer_file"] and row["experiment_id"] and row["normalized_perfect"] == "True" for row in rows)
    with (output / "summary.csv").open(encoding="utf-8-sig", newline="") as handle:
        assert len(list(csv.DictReader(handle))) == 16
    assert before == [(str(path), hashlib.sha256(path.read_bytes()).hexdigest()) for path in files]
    assert files == sorted(path for path in saved_results.rglob("*") if path.is_file())
    original_output = (output / "analysis.json").read_bytes()
    assert spec_rescore.main(["--results-dir", str(saved_results), "--output-dir", str(output)]) == 1
    assert (output / "analysis.json").read_bytes() == original_output


@pytest.mark.parametrize("extra", [False, True])
def test_incomplete_or_excessive_trials_are_rejected_before_writing(saved_results, tmp_path, extra):
    if extra:
        _saved_experiment(saved_results, "claude-haiku-5-5", "medium", runs=1, suffix="_duplicate")
    else:
        answer = next(saved_results.glob("*/trial_001/answer.txt"))
        (answer.parent / "trial.json").unlink()
    output = tmp_path / "analysis"
    assert spec_rescore.main(["--results-dir", str(saved_results), "--output-dir", str(output)]) == 1
    assert not output.exists()


@pytest.mark.parametrize("change", ["hash", "model", "effort", "variant", "set"])
def test_inconsistent_metadata_is_rejected(saved_results, tmp_path, change):
    path = next(saved_results.glob("*/experiment.json" if change == "hash" else "*/trial_001/trial.json"))
    value = json.loads(path.read_text(encoding="utf-8"))
    if change == "hash":
        value["input_hashes"][SET2_SPEC_NAMES[0]] = {}
    else:
        field = {"model": "model", "effort": "effort", "variant": "prompt_variant", "set": "dataset_set"}[change]
        value[field] = "unexpected"
    _write_json(path, value)
    assert spec_rescore.main(["--results-dir", str(saved_results), "--output-dir", str(tmp_path / "analysis")]) == 1
    assert not (tmp_path / "analysis").exists()


def test_saved_execution_errors_and_incomplete_costs_are_not_hidden(saved_results):
    path = next(saved_results.glob("*/trial_001/trial.json"))
    trial = json.loads(path.read_text(encoding="utf-8"))
    case = load_spec(trial["spec"])
    trial["claude"]["status"] = "timeout"
    trial["scoring"] = score_response(_response(case), case, execution_error="CLI status=timeout")
    trial["cost"] = {"api_equivalent_usd": None, "complete": False}
    trial["model_check"]["status"] = "mismatch"
    _write_json(path, trial)
    analysis = spec_rescore.analyze_saved(saved_results)
    record = next(record for record in analysis["trials"] if record["trial_file"] == str(path.resolve()))
    assert record["fence_recovered"] is True and record["normalized"]["status"] == "execution_error"
    assert record["normalized"]["metrics"]["f1"] == 0
    row = next(row for row in analysis["summary"] if row["spec"] == "ALL" and row["model"] == trial["model"] and row["effort"] == trial["effort"])
    assert row["normalized_perfect"] == 14 and row["mean_api_equivalent_usd"] is None and row["model_mismatch"] == 1


def test_information_false_positives_and_omissions_do_not_change_contradiction_f1():
    case = load_spec(SET2_SPEC_NAMES[0])
    response = json.loads(_response(case))
    response["insufficient_information"] = [{"requirement_ids": ["R01"], "reason": "模擬の誤検出"}]
    score = score_response(json.dumps(response), case)
    info = spec_rescore.information_score(score, case)
    assert info["metrics"]["tp"] == 0 and info["metrics"]["fp"] == 1 and info["metrics"]["fn"] == 2
    assert score["metrics"]["f1"] == 1


def test_sources_cannot_be_used_as_output_directory(saved_results):
    with pytest.raises(ValueError, match="外にある"):
        spec_rescore.write_analysis(spec_rescore.analyze_saved(saved_results), saved_results / "analysis", saved_results)
    assert not (saved_results / "analysis").exists()


def test_permission_errors_are_not_silently_treated_as_missing_trials(tmp_path, monkeypatch, capsys):
    def deny(_):
        raise PermissionError("saved results are unreadable")

    monkeypatch.setattr(spec_rescore.os, "scandir", deny)
    assert spec_rescore.main(["--results-dir", str(tmp_path / "results"), "--output-dir", str(tmp_path / "analysis")]) == 1
    assert "saved results are unreadable" in capsys.readouterr().err
    assert not (tmp_path / "analysis").exists()


def test_unreadable_candidate_is_recorded_when_all_sixty_trials_are_available(saved_results, monkeypatch):
    unrelated = saved_results / "unreadable_candidate"
    unrelated.mkdir()
    original_scandir = spec_rescore.os.scandir

    def scandir(path):
        if Path(path) == unrelated:
            raise PermissionError("unreadable candidate")
        return original_scandir(path)

    monkeypatch.setattr(spec_rescore.os, "scandir", scandir)
    analysis = spec_rescore.analyze_saved(saved_results)
    assert analysis["trial_count"] == 60
    assert analysis["unreadable_directories"] == [{"path": str(unrelated), "error": "unreadable candidate"}]
    assert str(unrelated) in spec_rescore.format_report(analysis)


def test_explicit_haiku45_selection_adds_fifteen_trials_and_excludes_the_pilot(saved_results):
    selected = _saved_experiment(saved_results, "claude-haiku-4-5", "default", variant="baseline")
    pilot = _saved_experiment(saved_results, "claude-haiku-4-5", "default", variant="baseline", runs=1, suffix="_pilot")
    legacy = spec_rescore.analyze_saved(saved_results)
    analysis = spec_rescore.analyze_saved(saved_results, haiku45_dir=selected)
    assert legacy["trial_count"] == 60 and "by_requirement_count" not in legacy
    assert analysis["trial_count"] == 75 and len(analysis["summary"]) == 20
    assert analysis["summary"][:16] == legacy["summary"]
    new_trials = [record for record in analysis["trials"] if record["model"] == "claude-haiku-4-5"]
    assert len(new_trials) == 15 and all(record["experiment_id"] == selected.name for record in new_trials)
    assert all(record["experiment_id"] != pilot.name for record in analysis["trials"])
    assert all(record["effort"] == "default" and record["fence_recovered"] for record in new_trials)
    assert len(analysis["by_requirement_count"]) == 15
    for row in analysis["by_requirement_count"]:
        expected = {2: 45, 3: 15, 4: 15}[row["requirement_count"]]
        assert row["gold_occurrences"] == row["normalized_tp"] == expected
        assert row["strict_tp"] == row["normalized_fn"] == 0


def test_requirement_counts_classify_by_gold_size_not_the_size_of_wrong_predictions(saved_results):
    selected = _saved_experiment(saved_results, "claude-haiku-4-5", "default", variant="baseline")
    case = load_spec(SET2_SPEC_NAMES[0])
    answer = json.loads(_response(case))
    complex_finding = next(item for item in answer["contradictions"] if len(item["requirement_ids"]) == 4)
    complex_finding["requirement_ids"] = complex_finding["requirement_ids"][1:]
    (selected / "trial_001" / "answer.txt").write_text("```json\n" + json.dumps(answer) + "\n```", encoding="utf-8")
    analysis = spec_rescore.analyze_saved(saved_results, haiku45_dir=selected)
    rows = {row["requirement_count"]: row for row in analysis["by_requirement_count"] if row["model"] == "claude-haiku-4-5"}
    assert rows[2]["normalized_tp"] == 45
    assert rows[3]["normalized_tp"] == 15 and rows[3]["normalized_fn"] == 0
    assert rows[4]["normalized_tp"] == 14 and rows[4]["normalized_fn"] == 1
    summary = next(row for row in analysis["summary"] if row["model"] == "claude-haiku-4-5" and row["spec"] == "ALL")
    assert summary["normalized_fp"] == summary["normalized_fn"] == 1
    assert summary["normalized_perfect"] == 14


def test_selecting_a_three_trial_pilot_does_not_produce_a_partial_comparison(saved_results, tmp_path):
    pilot = _saved_experiment(saved_results, "claude-haiku-4-5", "default", variant="baseline", runs=1)
    output = tmp_path / "analysis"
    assert spec_rescore.main(["--results-dir", str(saved_results), "--haiku45-dir", str(pilot), "--output-dir", str(output)]) == 1
    assert not output.exists()


@pytest.mark.parametrize("field,value", [("model", "claude-sonnet-4-6"), ("effort", "high"), ("prompt_variant", "minimality")])
def test_selected_haiku45_experiment_must_match_the_requested_condition(saved_results, field, value):
    selected = _saved_experiment(saved_results, "claude-haiku-4-5", "default", variant="baseline")
    path = selected / "experiment.json"
    meta = json.loads(path.read_text(encoding="utf-8"))
    meta[field] = value
    _write_json(path, meta)
    with pytest.raises(ValueError, match="Haiku 4.5/default/baseline"):
        spec_rescore.analyze_saved(saved_results, haiku45_dir=selected)


def test_selected_haiku45_cli_saves_additional_csv_and_preserves_source_files(saved_results, tmp_path, capsys):
    selected = _saved_experiment(saved_results, "claude-haiku-4-5", "default", variant="baseline")
    files = sorted(path for path in saved_results.rglob("*") if path.is_file())
    before = [path.read_bytes() for path in files]
    output = tmp_path / "analysis"
    assert spec_rescore.main(["--results-dir", str(saved_results), "--haiku45-dir", str(selected), "--output-dir", str(output)]) == 0
    assert "75試行" in capsys.readouterr().out
    with (output / "by_requirement_count.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 15
    assert all(row["normalized_tp"] == row["gold_occurrences"] for row in rows)
    assert "情報不足の指摘" in (output / "report.md").read_text(encoding="utf-8")
    assert before == [path.read_bytes() for path in files]
    assert files == sorted(path for path in saved_results.rglob("*") if path.is_file())


def test_explicit_experiment_outside_results_is_also_protected_from_output(saved_results, tmp_path):
    selected = _saved_experiment(tmp_path / "external", "claude-haiku-4-5", "default", variant="baseline")
    analysis = spec_rescore.analyze_saved(saved_results, haiku45_dir=selected)
    with pytest.raises(ValueError, match="外にある"):
        spec_rescore.write_analysis(analysis, selected / "analysis", saved_results)
    assert not (selected / "analysis").exists()
