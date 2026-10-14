import copy
import csv
import json
import sys
from pathlib import Path

import pytest

from ai_lab import claude_cli
from ai_lab import long_context_benchmark as bench
from ai_lab.long_context_data import FACTS, LENGTHS, build_case, build_prompt, load_case, save_case
from ai_lab.long_context_scoring import score_response


def answer(case):
    return copy.deepcopy({key: case.gold[key] for key in ("facts", "final", "boundary_checks")})


@pytest.fixture
def case():
    return build_case(101, "short", "middle", "similar")


@pytest.fixture
def fake_command():
    return [sys.executable, str(Path(__file__).parent / "fixtures" / "fake_long_context_claude.py")]


@pytest.mark.parametrize("seed", [101, 102, 103, 201])
def test_generated_truth_is_invariant_across_lengths_positions_and_similarity(seed):
    original = build_case(seed, "short", "start", "neutral")
    for length in LENGTHS:
        for position in ("start", "middle", "end"):
            neutral = build_case(seed, length, position, "neutral")
            similar = build_case(seed, length, position, "similar")
            assert neutral.question == similar.question == original.question
            for key in ("facts", "final", "boundary_checks"):
                assert neutral.gold[key] == similar.gold[key] == original.gold[key]
            assert neutral.gold["source_values"] == similar.gold["source_values"]
            assert len(neutral.document) == len(similar.document) == LENGTHS[length] * 4
            assert neutral.config["filler_count"] == similar.config["filler_count"]
            assert neutral.config["similar_filler_count"] == 0 < similar.config["similar_filler_count"]
            fee_source = neutral.gold["facts"]["base_fee"]["sources"][0]
            fraction = neutral.gold["evidence_offsets"][fee_source] / len(neutral.document)
            assert abs(fraction - {"start": .05, "middle": .5, "end": .95}[position]) < .04
    assert build_case(seed, "short", "start", "neutral") == original


def test_oracle_uses_integer_arithmetic_and_exercises_all_applicability_branches():
    branches = set()
    for seed in range(30):
        item = build_case(seed, "short", "start", "neutral", chars_per_token=1)
        facts = {key: row["value"] for key, row in item.gold["facts"].items()}
        discounted = facts["discount_segment"] == item.question["segment"]
        special = facts["exception_kind"] == item.question["kind"]
        expected = facts["base_fee"] - (facts["base_fee"] * facts["discount_percent"] // 100 if discounted else 0)
        expected += facts["exception_surcharge"] if special else 0
        assert item.gold["final"]["amount"] == expected
        assert item.gold["final"]["route"] == facts["exception_route" if special else "standard_route"]
        branches.add((discounted, special))
    assert len(branches) == 4


def test_generated_files_are_regenerated_and_tampering_is_rejected(case, tmp_path):
    output = tmp_path / "case"
    save_case(case, output)
    assert load_case(output) == case
    with pytest.raises(FileExistsError): save_case(case, output)
    path = output / "answer_key.json"
    data = json.loads(path.read_text())
    data["final"]["amount"] += 1
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="metadata or gold"): load_case(output)


def test_long90k_preserves_question_gold_evidence_and_distraction_profile(tmp_path):
    original = build_case(101, "long", "middle", "similar")
    smaller = build_case(101, "long90k", "middle", "similar")
    assert smaller.case_id == "s101_long90k_middle_similar"
    assert smaller.question == original.question
    assert answer(smaller) == answer(original)
    assert len(smaller.document) == 360_000 < len(original.document) == 480_000
    assert smaller.config["chars_per_token"] == original.config["chars_per_token"] == 4
    assert smaller.config["similar_filler_count"] == (smaller.config["filler_count"] + 4) // 5
    for sid, offset in smaller.gold["evidence_offsets"].items():
        original_offset = original.gold["evidence_offsets"][sid]
        assert abs(offset / len(smaller.document) - original_offset / len(original.document)) < .005
        assert smaller.document[offset:].splitlines()[0] == original.document[original_offset:].splitlines()[0]
    assert all(original.gold["source_values"][sid] == values for sid, values in smaller.gold["source_values"].items())
    corpus = tmp_path / "corpus"
    bench.generate(corpus, [101], ["long90k"], ["middle"], ["similar"], 4)
    assert bench.corpus_cases(corpus) == [smaller]
    assert build_case(101, "long90k", "middle", "similar") == smaller
    assert score_response(json.dumps(answer(smaller)), smaller)["strict_success"]


def test_default_generation_keeps_original_three_lengths(tmp_path):
    corpus = tmp_path / "corpus"
    assert bench.main(["generate", "--output-dir", str(corpus), "--seeds", "101",
                       "--positions", "middle", "--distractions", "similar"]) == 0
    assert [case.config["length"] for case in bench.corpus_cases(corpus)] == ["short", "medium", "long"]


@pytest.mark.parametrize("label,effort,ratio", [("haiku45", "default", .30), ("haiku", "medium", .39), ("haiku", "high", .39)])
def test_long90k_dry_run_passes_common_guard_without_invoking_cli(tmp_path, capsys, monkeypatch, label, effort, ratio):
    corpus = tmp_path / "corpus"
    bench.generate(corpus, [101], ["long90k"], ["middle"], ["similar"], 4)
    model = bench.MODEL_IDS[label]
    calibration = {"version": 1, "chars_per_token": 4.0, "models": {model: {"tokens_per_byte_with_margin": ratio}}}
    calibration_path = tmp_path / "calibration.json"
    calibration_path.write_text(json.dumps(calibration), encoding="utf-8")
    monkeypatch.setattr(bench, "run_benchmark", lambda *args, **kwargs: pytest.fail("Dry-run must not invoke the model"))
    monkeypatch.setattr(claude_cli, "preflight", lambda *args, **kwargs: pytest.fail("Dry-run must not invoke CLI preflight"))
    assert bench.main(["run", str(corpus), "--case-id", "s101_long90k_middle_similar", "--model", label,
                       "--effort", effort, "--calibration", str(calibration_path), "--limit", "1", "--dry-run"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["model"] == model and result["effort"] == effort
    assert result["calls"] == 1 and result["model_invoked"] is False
    guard = result["schedule"][0]["guard"]
    assert guard["status"] == "estimate_pass"
    assert guard["estimated_context_tokens"] <= guard["context_budget"] == 180_000
    assert guard["cli_overhead_reserve"] == 20_000 and guard["output_reserve"] == 8_000
    if label == "haiku":
        with pytest.raises(ValueError, match="No request sent"):
            bench.input_guard(build_case(101, "long", "middle", "similar"), model, calibration)


def test_prompt_contains_only_manual_question_schema_and_generic_instructions(case):
    prompt = build_prompt(case)
    assert case.document in prompt
    assert "source_values" not in prompt and "evidence_offsets" not in prompt
    assert "final" in prompt and "grace_period_days" in prompt
    assert case.config["document_tokens_measured"] is None


def test_perfect_answer_and_fence_format_are_scored_separately(case):
    text = json.dumps(answer(case))
    score = score_response(text, case)
    assert score["strict_success"] and score["fact_accuracy"] == score["citation_accuracy"] == 1
    fenced = score_response('```json\n' + text + '\n```', case)
    assert fenced["content_correct"] and fenced["schema_valid"] and fenced["fence_recovered"]
    assert not fenced["format_compliant"] and not fenced["strict_success"]
    assert not score_response(text, case, execution_error="timeout")["strict_success"]


def test_retrieval_failure_and_combination_failure_are_different(case):
    data = answer(case)
    data["final"]["amount"] += 1
    score = score_response(json.dumps(data), case)
    assert score["extraction_correct"] and score["prerequisites_correct"]
    assert score["composition_failure_given_correct_facts"]
    data["facts"]["base_fee"]["value"] = None
    score = score_response(json.dumps(data), case)
    assert not score["extraction_correct"] and not score["prerequisites_correct"]
    assert not score["composition_failure_given_correct_facts"] and score["omitted_facts"] == 1


def test_fabrication_wrong_entity_and_bad_citations_are_separate(case):
    data = answer(case)
    data["facts"]["base_fee"]["value"] = 123456789
    score = score_response(json.dumps(data), case)
    assert score["fabricated_values"] == 1 and score["wrong_entity_values"] == 0
    data = answer(case)
    data["facts"]["grace_period_days"] = {"value": 10, "sources": []}
    score = score_response(json.dumps(data), case)
    assert score["wrong_entity_values"] == 1 and not score["content_correct"]
    data = answer(case)
    data["facts"]["base_fee"]["sources"] = ["S000000"]
    score = score_response(json.dumps(data), case)
    assert score["content_correct"] and score["unsupported_citations"] == 1 and not score["strict_success"]
    data = answer(case)
    data["final"]["route"] = "invented_route"
    data["final"]["sources"] = ["S000000"]
    score = score_response(json.dumps(data), case)
    assert score["fabricated_final_route"] and score["fabricated_values"] == score["unsupported_citations"] == 1


@pytest.mark.parametrize("text", ['{}', '[]', '{"facts": NaN}', '{"facts": {}, "facts": {}}', 'prose\n```json\n{}\n```'])
def test_bad_format_cannot_become_a_success(text, case):
    score = score_response(text, case)
    assert not score["strict_success"] and not score["format_compliant"]


@pytest.mark.parametrize("malformation", [True, ["S000000", []], {"bad": 1}])
def test_malformed_types_do_not_crash_or_count_as_correct(malformation, case):
    data = answer(case)
    data["facts"]["base_fee"]["value"] = malformation
    data["facts"]["base_fee"]["sources"] = malformation
    score = score_response(json.dumps(data), case)
    assert not score["strict_success"] and not score["schema_valid"]


def test_context_guard_blocks_unmeasured_long_inputs_and_uses_matching_calibration(case):
    model = "claude-haiku-4-5"
    assert bench.input_guard(case, model, None)["estimated_context_tokens"] < bench.CONTEXT_BUDGET
    long = build_case(101, "long", "start", "neutral")
    with pytest.raises(ValueError, match="No request sent"): bench.input_guard(long, model, None)
    calibration = {"version": 1, "chars_per_token": 4.0, "models": {model: {"tokens_per_byte_with_margin": .25}}}
    assert bench.input_guard(long, model, calibration)["estimated_context_tokens"] < bench.CONTEXT_BUDGET
    calibration["chars_per_token"] = 3
    with pytest.raises(ValueError, match="settings differ"): bench.input_guard(long, model, calibration)


@pytest.mark.parametrize("label, effort", bench.CONDITIONS)
def test_stdin_transport_records_tokens_thinking_and_isolates_gold(case, tmp_path, monkeypatch, fake_command, label, effort):
    monkeypatch.setenv("FAKE_LONG_RESPONSE", json.dumps(answer(case)))
    log = tmp_path / "calls.json"
    monkeypatch.setenv("FAKE_LONG_ARGLOG", str(log))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "never-pass-this-key")
    output = bench.run_benchmark([case], model_label=label, effort=effort, runs=1, limit=1,
                                 results_dir=tmp_path / "results", command=fake_command)
    record = json.loads((output / "trial_001/trial.json").read_text())
    call = json.loads(log.read_text())
    assert record["comparison_eligible"] and record["scoring"]["strict_success"]
    assert record["context"]["stdin_echo_status"] == "match"
    assert record["context"]["truncation_status"] == record["context"]["compaction_status"] == "unverified"
    assert record["claude"]["thinking_tokens"] == 100 and record["tokens"]["output"] == 1000
    assert record["context"]["reported_prompt_tokens"] > 10_000
    assert not call["api_key_present"] and call["cwd_entries"] == []
    assert call["output_budget"] == "8000" and call["stdin_bytes"] > 40_000
    assert call["stdin_sha256"] == record["stdin_sha256"]
    assert len(" ".join(call["argv"])) < 1000 and "--safe-mode" in call["argv"]
    assert call["argv"][call["argv"].index("--tools") + 1] == ""
    assert ("--effort" in call["argv"]) is (effort != "default")
    assert load_case(output / "cases" / case.case_id) == case
    calibration = bench.calibrate([output], tmp_path / "calibration.json")
    assert calibration["models"][record["model"]]["pilot_trials"] == 1
    assert calibration["guaranteed_within_window"] is False
    bench.export_report([output], tmp_path / "analysis")
    assert (tmp_path / "analysis/summary.csv").exists()


@pytest.mark.parametrize("variable", ["FAKE_LONG_BAD_ECHO", "FAKE_LONG_COMPACT", "FAKE_LONG_MODEL", "FAKE_LONG_PROMPT_TOKENS"])
def test_context_anomalies_stop_after_one_trial(case, tmp_path, monkeypatch, fake_command, variable):
    value = "claude-opus-4-8" if variable == "FAKE_LONG_MODEL" else "190000" if variable == "FAKE_LONG_PROMPT_TOKENS" else "1"
    monkeypatch.setenv(variable, value)
    monkeypatch.setenv("FAKE_LONG_RESPONSE", json.dumps(answer(case)))
    output = bench.run_benchmark([case], model_label="haiku45", effort=None, runs=2, limit=2,
                                 results_dir=tmp_path / "results", command=fake_command)
    assert len(list(output.glob("trial_*"))) == 1
    record = json.loads((output / "trial_001/trial.json").read_text())
    assert not record["comparison_eligible"] and record["context_alerts"]
    with pytest.raises(ValueError, match="insufficient"): bench.calibrate([output], tmp_path / "bad.json")


def test_long_pricing_switches_all_rates_without_double_charging_thinking():
    model = "claude-haiku-5-5"
    cli = {"num_turns": 1, "model_usage": {model: {"inputTokens": 120000, "outputTokens": 1000}}, "thinking_tokens": 900}
    context = {"assistant_message_usage": {"m": {}}, "compaction_events": []}
    tokens, cost = bench.price_long_trial(cli, model, context)
    assert tokens["output"] == 1000 and cost["api_equivalent_usd"] == pytest.approx(.0625)
    assert cost["long_context_multiplier"] == 5 and cost["rates_per_mtok"][model]["output"] == 2.5
    cli["num_turns"] = 2
    _, cost = bench.price_long_trial(cli, model, context)
    assert cost["api_equivalent_usd"] is None and not cost["complete"]


def test_plan_counts_independent_problems_repeats_and_two_tasks(case):
    report = bench.plan([case], runs=2)
    assert report["calls"] == 6 and report["task_answers"] == 12
    assert report["independent_problem_seeds"] == [101]


def test_cli_dry_run_never_invokes_model_and_existing_corpora_are_protected(tmp_path, capsys):
    corpus = tmp_path / "corpus"
    arguments = ["generate", "--output-dir", str(corpus), "--seeds", "101", "--lengths", "short", "--positions", "start", "--distractions", "neutral"]
    assert bench.main(arguments) == 0
    assert bench.main(arguments) == 1
    assert bench.main(["validate", str(corpus)]) == 0
    assert bench.main(["run", str(corpus), "--model", "haiku", "--effort", "high", "--dry-run"]) == 0
    assert '"model_invoked": false' in capsys.readouterr().out
    assert bench.main(["run", str(corpus), "--model", "haiku45", "--effort", "high", "--dry-run"]) == 1
    assert not (tmp_path / "results").exists()


def test_paired_report_measures_model_difference_in_length_degradation(tmp_path, monkeypatch, fake_command):
    outputs = []
    calibration = {"version": 1, "chars_per_token": 4.0, "models": {
        model: {"tokens_per_byte_with_margin": .25, "cli_versions": ["9.9.9 (Claude Code)"]} for model in ("claude-haiku-4-5", "claude-haiku-5-5")}}
    for label, effort in (("haiku45", "default"), ("haiku", "medium")):
        for length in ("short", "long"):
            item = build_case(104, length, "end", "similar")
            response = answer(item)
            if label == "haiku45" and length == "long":
                response["facts"]["base_fee"]["value"] = None
                response["final"]["amount"] += 1
            monkeypatch.setenv("FAKE_LONG_RESPONSE", json.dumps(response))
            outputs.append(bench.run_benchmark([item], model_label=label, effort=effort, runs=1, limit=1,
                                               results_dir=tmp_path / "results", command=fake_command, calibration=calibration))
    report = tmp_path / "report"
    bench.export_report(outputs, report)
    with (report / "hypothesis_comparisons.csv").open(encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2
    assert all(float(row["haiku55_minus_haiku45_change"]) == 1 for row in rows)
    with (report / "trials.csv").open(encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 4 and "tokens_cache_read" in rows[0] and "thinking_tokens" in rows[0]
    assert all(row["document_tokens_measured"] == "" for row in rows)
    with pytest.raises(FileExistsError): bench.export_report(outputs, report)
    with pytest.raises(ValueError, match="more than once"): bench.export_report([outputs[0], outputs[0]], tmp_path / "duplicate")
    with pytest.raises(ValueError, match="outside source"): bench.export_report(outputs, outputs[0] / "report")


def test_model_mismatch_is_priced_using_actual_model_without_long_multiplier():
    cli = {"num_turns": 1, "model_usage": {"claude-haiku-4-5": {"inputTokens": 120000, "outputTokens": 1000}}}
    _, cost = bench.price_long_trial(cli, "claude-haiku-5-5", {"assistant_message_usage": {}, "compaction_events": []})
    assert cost["api_equivalent_usd"] == pytest.approx(.125) and cost["long_context_multiplier"] == 1


@pytest.mark.parametrize("prompt_tokens,factor", [(100000, 1), (100001, 5)])
def test_long_pricing_threshold_includes_cache_reads(prompt_tokens, factor):
    model = "claude-haiku-5-5"
    cli = {"num_turns": 1, "model_usage": {model: {"inputTokens": 1000, "outputTokens": 1000,
                                                   "cacheReadInputTokens": prompt_tokens - 1000}}}
    _, cost = bench.price_long_trial(cli, model, {"assistant_message_usage": {}, "compaction_events": []})
    assert cost["long_context_multiplier"] == factor
    assert cost["api_equivalent_usd"] == pytest.approx((1000 * .1 + (prompt_tokens - 1000) * .01 + 1000 * .5) / 1e6 * factor, abs=1e-6)


def test_old_cli_is_rejected_before_any_haiku55_model_request(case, tmp_path, monkeypatch, fake_command):
    monkeypatch.setattr(claude_cli, "preflight", lambda *args: {"version": "2.1.286 (Claude Code)", "auth_method": "claude.ai"})
    log = tmp_path / "calls.json"
    monkeypatch.setenv("FAKE_LONG_ARGLOG", str(log))
    with pytest.raises(RuntimeError, match="2.1.293"):
        bench.run_benchmark([case], model_label="haiku", effort="high", runs=1, limit=1,
                            results_dir=tmp_path / "results", command=fake_command)
    assert not log.exists() and not (tmp_path / "results").exists()


def test_timeout_is_saved_without_inventing_cost_or_accuracy(case, tmp_path, monkeypatch, fake_command):
    monkeypatch.setenv("FAKE_LONG_SLEEP", "3")
    output = bench.run_benchmark([case], model_label="haiku45", effort=None, runs=2, limit=2, timeout=.15,
                                 results_dir=tmp_path / "results", command=fake_command)
    record = json.loads((output / "trial_001/trial.json").read_text())
    assert record["claude"]["status"] == "timeout" and record["cost"]["api_equivalent_usd"] is None
    assert not record["scoring"]["strict_success"] and not record["comparison_eligible"]
    assert len(list(output.glob("trial_*"))) == 1


def test_conservative_guard_and_nested_run_refusal_happen_before_preflight(tmp_path, monkeypatch, fake_command):
    long = build_case(101, "long", "middle", "neutral")
    monkeypatch.setattr(claude_cli, "preflight", lambda *args: pytest.fail("Preflight should not run"))
    with pytest.raises(ValueError, match="No request sent"):
        bench.run_benchmark([long], model_label="haiku45", effort=None, runs=1, limit=1,
                            results_dir=tmp_path / "results", command=fake_command)
    monkeypatch.setenv("CLAUDECODE", "1")
    with pytest.raises(RuntimeError, match="Nested"):
        bench.run_benchmark([long], model_label="haiku45", effort=None, runs=1, limit=1,
                            results_dir=tmp_path / "results", command=fake_command)


def test_corpus_rejects_duplicate_or_traversing_manifest_entries(tmp_path):
    directory = tmp_path / "corpus"
    bench.generate(directory, [101], ["short"], ["start"], ["neutral"], 4)
    path = directory / "manifest.json"
    meta = json.loads(path.read_text())
    meta["cases"].append(meta["cases"][0])
    path.write_text(json.dumps(meta))
    with pytest.raises(ValueError, match="duplicate"): bench.corpus_cases(directory)
    meta["cases"] = [{"case_id": "..", "prompt_sha256": "ignored"}]
    path.write_text(json.dumps(meta))
    with pytest.raises(ValueError, match="Invalid"): bench.corpus_cases(directory)


@pytest.mark.parametrize("count", [-1, True, "12000", None])
def test_invalid_reported_token_counts_are_unknown_not_priced(count):
    model = "claude-haiku-4-5"
    tokens, cost = bench.saved_usage_price({"model_usage": {model: {"inputTokens": count, "outputTokens": 1000}}}, model)
    assert tokens is None and cost["api_equivalent_usd"] is None and not cost["complete"]
