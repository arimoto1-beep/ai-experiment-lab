"""Rebuild ignored analysis.json from the nine local runs without calling a model.

Run from the repository root with -m analysis.long_context_comparison_20261014.prepare_snapshot.
"""

import hashlib
import json
import tempfile
from pathlib import Path

from ai_lab.long_context_benchmark import export_report
from ai_lab.long_context_data import FACTS, build_prompt, load_case
from ai_lab.long_context_scoring import score_response
from ai_lab.spec_rescore import normalize_answer

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[1]


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def source_hashes(directories):
    return {str(path.relative_to(PROJECT_ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for directory in directories for path in sorted(directory.rglob("*")) if path.is_file()}


def main():
    config = read_json(HERE / "pilot_config.json")
    directories = [PROJECT_ROOT / "results" / "long_context_runs" / item["directory"] for item in config["experiments"]]
    before = source_hashes(directories)
    # Reuse existing validation/reporting. Its temporary output is separate from all inputs.
    with tempfile.TemporaryDirectory(prefix=".analysis-pilot-", dir=PROJECT_ROOT) as temp:
        output = Path(temp) / "report"
        export_report(directories, output)
        analysis = read_json(output / "analysis.json")
    details = []
    for item, directory in zip(config["experiments"], directories, strict=True):
        meta = read_json(directory / "experiment.json")
        trials = list(directory.glob("trial_*/trial.json"))
        assert len(trials) == config["runs_per_cell"] == 1
        path = trials[0]
        record = read_json(path)
        dims = record["case_config"]
        assert record["effort"] == item["effort"] and dims["length"] == item["length"]
        assert record["model"] == config["conditions"][item["effort"]]["model"]
        assert dims["seed"] == config["problem_seed"] and dims["position"] == config["position"]
        assert dims["distraction"] == config["distraction"] and dims["chars_per_token"] == config["chars_per_token"]
        assert dims["target_tokens"] == config["target_document_tokens"][item["length"]]
        case = load_case(directory / "cases" / record["case_id"])
        answer = (path.parent / "answer.txt").read_text(encoding="utf-8")
        assert answer.strip() == record["claude"]["result_text"].strip()
        assert score_response(answer, case, execution_error=record["scoring"]["execution_error"]) == record["scoring"]
        parsed = json.loads(normalize_answer(answer)["text"])
        assert read_json(path.parent / "stdin.jsonl")["message"]["content"] == build_prompt(case)
        events = [json.loads(line) for line in (path.parent / "claude_stdout.txt").read_text(encoding="utf-8").splitlines()]
        results = [event for event in events if event.get("type") == "result"]
        assert len(results) == 1
        raw = results[0]
        usage, tokens = raw["usage"], record["tokens"]
        for key, usage_key in (("input", "input_tokens"), ("output", "output_tokens"),
                               ("cache_read", "cache_read_input_tokens"), ("cache_write", "cache_creation_input_tokens")):
            assert tokens[key] == usage[usage_key]
        thinking = record["claude"]["thinking_tokens"]
        assert thinking == usage["output_tokens_details"]["thinking_tokens"]
        total = sum(tokens[key] for key in ("input", "cache_read", "cache_write"))
        assert total == record["context"]["reported_prompt_tokens"]
        rates = record["cost"]["rates_per_mtok"][record["model"]]
        ttl = record["cost"]["cache_write_tokens_by_ttl"]
        exact = (tokens["input"] * rates["input"] + tokens["cache_read"] * rates["cache_read"]
                 + ttl["1h"] * rates["cache_write_1h"] + ttl["5m"] * rates["cache_write_5m"]
                 + tokens["output"] * rates["output"]) / 1e6
        assert abs(exact - raw["total_cost_usd"]) < 1e-9
        assert abs(exact - record["cost"]["api_equivalent_usd"]) <= 1.1e-6
        fields = [{"field": field, "expected": case.gold["facts"][field],
                   "actual": parsed["facts"][field], **record["scoring"]["facts"][field]} for field in FACTS]
        init = next((event for event in events if event.get("type") == "system" and event.get("subtype") == "init"), {})
        details.append({
            "experiment": directory.name, "source_trial": str(path.relative_to(PROJECT_ROOT)),
            "record": record, "fields": fields, "actual_answer": parsed,
            "expected_answer": {key: case.gold[key] for key in ("facts", "final", "boundary_checks")},
            "metadata": {key: meta.get(key) for key in ("claude_version", "auth_method", "requested_trials", "started_at",
                         "reasoning_settings", "tool_policy", "context_environment", "input_transport", "source_sha256")},
            "raw_verification": {
                "saved_scoring_matches_existing_scorer": True, "raw_usage_matches_saved_tokens": True,
                "stdin_payload_matches_saved_prompt": True, "stderr_bytes": (path.parent / "claude_stderr.txt").stat().st_size,
                "result_count": 1, "usage_iterations": len(usage.get("iterations", [])),
                "compact_boundary_events": sum(e.get("type") == "system" and e.get("subtype") == "compact_boundary" for e in events),
                "per_turn_effort_active": init.get("per_turn_effort_active"),
                "tools_at_init": len(init.get("tools", [])), "mcp_servers_at_init": len(init.get("mcp_servers", [])),
            },
            "prompt_bytes": len(build_prompt(case).encode("utf-8")), "gold_evidence_offsets": case.gold["evidence_offsets"],
            "fact_correct_count": sum(field["correct"] for field in fields),
            "citation_id_correct_count": round(record["scoring"]["citation_accuracy"] * 9),
            "value_supported_fact_count": sum(f["correct"] and f["source_correct"] and f["unsupported_citations"] == 0 for f in fields),
            "cache_read_share": tokens["cache_read"] / total, "visible_output_tokens": tokens["output"] - thinking,
            "recomputed_api_equivalent_usd": exact,
            "normalized_costs": {
                "all_input_uncached_usd": (total * rates["input"] + tokens["output"] * rates["output"]) / 1e6,
                "all_input_cache_write_1h_usd": (total * rates["cache_write_1h"] + tokens["output"] * rates["output"]) / 1e6,
                "all_input_cache_read_usd": (total * rates["cache_read"] + tokens["output"] * rates["output"]) / 1e6,
            },
        })
    assert all(d["expected_answer"] == details[0]["expected_answer"] for d in details)
    assert source_hashes(directories) == before
    analysis.update(details=details, source_sha256=before, source_files_verified_unchanged=len(before),
                    same_question_and_scored_gold=True, additional_model_requests=0)
    (HERE / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Verified {len(details)} trials and {len(before)} unchanged source files; rebuilt analysis.json.")


if __name__ == "__main__":
    main()
