"""Small CLI for generating, planning, running and reporting the long-context experiment."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import random
import re
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from ai_lab import claude_cli
from ai_lab.experiment import _now, _write_json, check_model, price_trial
from ai_lab.long_context_data import DEFAULT_LENGTHS, DISTRACTIONS, LENGTHS, POSITIONS, Case, build_case, build_prompt, digest, load_case, save_case
from ai_lab.long_context_scoring import score_response
from ai_lab.pricing import MODEL_IDS, PRICES_PER_MTOK, PRICING_SOURCE_URL, TokenCounts, cost_usd
from ai_lab.problems import PROJECT_ROOT
from ai_lab.spec_benchmark import build_args as spec_args

CONDITIONS = (("haiku45", "default"), ("haiku", "medium"), ("haiku", "high"))
CONTEXT_BUDGET = 180_000  # Leave a further 20k below Haiku 4.5's 200k window.
OVERHEAD_RESERVE = 20_000
OUTPUT_RESERVE = 8_000
CHECKED_ON = "2026-10-14"
LONG_RATE_MULTIPLIER = 5  # Official Haiku 5.5 pricing above 100k prompt tokens.


def corpus_cases(directory: Path) -> list[Case]:
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("version") != 1 or not isinstance(manifest.get("cases"), list) or not manifest["cases"]:
        raise ValueError("Unknown or empty corpus manifest")
    cases = []
    seen = set()
    length_names = "|".join(re.escape(name) for name in LENGTHS)
    for item in manifest["cases"]:
        name = item["case_id"]
        if not isinstance(name, str) or not re.fullmatch(fr"s\d+_({length_names})_(start|middle|end)_(neutral|similar)", name) or name in seen:
            raise ValueError("Invalid or duplicate case ID")
        seen.add(name)
        case = load_case(directory / name)
        if case.case_id != name or digest(build_prompt(case)) != item["prompt_sha256"]:
            raise ValueError(f"Corpus hash mismatch: {name}")
        cases.append(case)
    return cases


def generate(directory: Path, seeds: list[int], lengths: list[str], positions: list[str], distractions: list[str], chars_per_token: float) -> None:
    cases = [build_case(seed, length, position, distraction, chars_per_token=chars_per_token)
             for seed in seeds for length in lengths for position in positions for distraction in distractions]
    if not cases or len({case.case_id for case in cases}) != len(cases):
        raise ValueError("Corpus dimensions must be nonempty and unique")
    # Check every input before creating a directory; existing corpora are never overwritten.
    directory.mkdir(parents=True, exist_ok=False)
    for case in cases:
        save_case(case, directory / case.case_id)
    _write_json(directory / "manifest.json", {"version": 1, "created_at": _now(), "cases": [
        {"case_id": case.case_id, "prompt_sha256": digest(build_prompt(case)), **case.config} for case in cases]})


def plan(cases: list[Case], runs: int = 2) -> dict[str, Any]:
    if runs < 1 or not cases:
        raise ValueError("At least one case and one repeat are required")
    estimates = []
    for label, effort in CONDITIONS:
        model = MODEL_IDS[label]
        scenarios = {"cold_input_2k_output": 0.0, "all_input_1h_write_8k_output": 0.0}
        for case in cases:
            estimated_input = math.ceil(len(build_prompt(case)) / case.config["chars_per_token"]) + OVERHEAD_RESERVE
            factor = LONG_RATE_MULTIPLIER if label == "haiku" and estimated_input > 100_000 else 1
            scenarios["cold_input_2k_output"] += cost_usd(model, TokenCounts(input=estimated_input, output=2_000)) * factor * runs
            scenarios["all_input_1h_write_8k_output"] += cost_usd(model, TokenCounts(cache_write=estimated_input, output=OUTPUT_RESERVE)) * factor * runs
        estimates.append({"model": model, "effort": effort, "calls": len(cases) * runs,
                          "api_equivalent_usd_scenarios": {key: round(value, 4) for key, value in scenarios.items()}})
    calls = len(cases) * runs * len(CONDITIONS)
    return {"cases": len(cases), "independent_problem_seeds": sorted({case.config["seed"] for case in cases}),
            "repeats_per_case_condition": runs, "model_conditions": estimates, "calls": calls,
            "task_answers": calls * 2, "serial_hours_at_60_to_300_seconds_per_call": [calls / 60, calls / 12],
            "total_api_equivalent_usd_scenarios": {name: round(sum(row["api_equivalent_usd_scenarios"][name] for row in estimates), 4)
                                                  for name in estimates[0]["api_equivalent_usd_scenarios"]},
            "assumptions": ["Document token counts are character estimates, not tokenizer measurements.",
                            "20k CLI overhead assumed per call; output includes Thinking, never added twice.",
                            "Scenarios are not confidence bounds; cache reads can cost less, hidden retries can cost more.",
                            "60-300 seconds per call is a planning assumption; replace with pilot measurements.",
                            "Subscription spending is not API-equivalent cost; no API key is used."],
            "pricing_source": PRICING_SOURCE_URL, "pricing_checked_on": CHECKED_ON}


def build_args(model: str, effort: str) -> list[str]:
    args = spec_args(model, effort, "__STDIN__")
    del args[1]  # Large documents must not be passed as command-line arguments on Windows.
    args[args.index("--output-format") + 1] = "stream-json"
    args[args.index("--max-turns") + 1] = "1"
    return args + ["--input-format", "stream-json", "--verbose", "--replay-user-messages"]


def invoke_stdin(command: list[str], args: list[str], payload: str, *, cwd: str, env: dict[str, str], timeout: float) -> claude_cli.CliRun:
    started = time.perf_counter()
    try:
        # Binary stdin preserves exactly the archived UTF-8 bytes, including LF on Windows.
        proc = subprocess.run([*command, *args], input=payload.encode("utf-8"), cwd=cwd, env=env,
                              capture_output=True, timeout=timeout, check=False)
        return claude_cli.CliRun(proc.returncode, claude_cli._text(proc.stdout), claude_cli._text(proc.stderr),
                                 time.perf_counter() - started, False)
    except subprocess.TimeoutExpired as exc:
        return claude_cli.CliRun(None, claude_cli._text(exc.stdout), claude_cli._text(exc.stderr), time.perf_counter() - started, True)


def saved_usage_price(cli: dict[str, Any], model: str) -> tuple[Any, dict[str, Any]]:
    """Malformed usage is unknown, not zero; keep the raw logs and stop subsequent requests."""
    try:
        usage = cli.get("model_usage")
        entries = list(usage.values()) if isinstance(usage, dict) and usage else [cli.get("usage") or {}]
        for entry in entries:
            if not isinstance(entry, dict): raise ValueError("Usage entry is not an object")
            names = ("inputTokens", "outputTokens", "cacheReadInputTokens", "cacheCreationInputTokens") if usage else (
                "input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
            if any(name in entry and (type(entry[name]) is not int or entry[name] < 0) for name in names):
                raise ValueError("Usage counts must be nonnegative integers")
        return price_trial(cli, model)
    except (ValueError, TypeError, AttributeError, OverflowError) as exc:
        return None, {"api_equivalent_usd": None, "complete": False, "notes": [f"Usage could not be priced: {exc}"]}


def telemetry(run: claude_cli.CliRun, cli: dict[str, Any], prompt: str, requested_model: str) -> dict[str, Any]:
    events = []
    unparsed = 0
    for line in run.stdout.splitlines():
        try:
            item = json.loads(line)
            if isinstance(item, dict):
                events.append(item)
        except ValueError:
            unparsed += 1
    echoes = []
    messages = {}
    models = set()
    compactions = []
    tool_uses = 0
    window = None
    for event in events:
        if event.get("type") == "user":
            content = event.get("message", {}).get("content")
            if isinstance(content, list):
                content = "".join(block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text")
            if isinstance(content, str):
                echoes.append(digest(content))
        if event.get("type") == "system" and event.get("subtype") == "compact_boundary":
            compactions.append(event.get("compact_metadata"))
        if event.get("type") == "assistant" and isinstance(event.get("message"), dict):
            message = event["message"]
            if message.get("model"):
                models.add(message["model"])
            if message.get("id"):
                messages[message["id"]] = message.get("usage")
            tool_uses += sum(block.get("type") == "tool_use" for block in message.get("content", []) if isinstance(block, dict))
    model_usage = cli.get("model_usage") if isinstance(cli.get("model_usage"), dict) else {}
    for record in model_usage.values():
        if isinstance(record, dict) and type(record.get("contextWindow")) is int:
            window = min(window, record["contextWindow"]) if window is not None else record["contextWindow"]
    tokens, _ = saved_usage_price(cli, requested_model)
    total_prompt = sum(tokens[name] for name in ("input", "cache_read", "cache_write")) if tokens else None
    observed_model_check = check_model({"model_usage": dict.fromkeys(models, {})}, requested_model)
    echo_status = "match" if digest(prompt) in echoes else "mismatch" if echoes else "unverified"
    return {"prompt_sha256": digest(prompt), "stdin_echo_status": echo_status, "echo_sha256": echoes,
            "reported_prompt_tokens": total_prompt, "document_tokens_measured": None,
            "reported_context_window": window, "reported_turns": cli.get("num_turns"),
            "assistant_message_usage": messages, "assistant_models": sorted(models),
            "assistant_model_check": observed_model_check["status"], "tool_uses_observed": tool_uses,
            "compaction_events": compactions, "compaction_status": "observed" if compactions else "unverified",
            "truncation_status": "unverified", "api_payload_integrity": "unverified", "unparsed_stdout_lines": unparsed,
            "notes": ["An exact CLI echo verifies receipt by the CLI, not delivery of every token to the model.",
                      "No observed compaction event is not proof that compaction never happened.",
                      "Reported prompt tokens include CLI system/cache content and may aggregate requests; not document-only tokens."]}


def price_long_trial(cli: dict[str, Any], model: str, context: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    tokens, cost = saved_usage_price(cli, model)
    cost = {**cost, "pricing_checked_on": CHECKED_ON, "long_context_multiplier": 1,
            "pricing_resolution": "reported_single_turn", "notes": list(cost["notes"])}
    if model == MODEL_IDS["haiku"] and tokens and check_model(cli, model)["status"] == "match":
        prompt_tokens = sum(tokens[name] for name in ("input", "cache_read", "cache_write"))
        single = cli.get("num_turns") == 1 and len(context["assistant_message_usage"]) <= 1 and not context["compaction_events"]
        if not single:
            base = cost["api_equivalent_usd"]
            cost.update(api_equivalent_usd=None, complete=False, pricing_resolution="per_request_threshold_unknown",
                        api_equivalent_usd_bounds=[base, round(base * LONG_RATE_MULTIPLIER, 6)] if base is not None else None)
            cost["notes"].append("Per-request lengths are unavailable; aggregate usage cannot determine Haiku 5.5's pricing tier.")
        elif prompt_tokens > 100_000 and cost["api_equivalent_usd"] is not None:
            cost["api_equivalent_usd"] = round(cost["api_equivalent_usd"] * LONG_RATE_MULTIPLIER, 6)
            cost["long_context_multiplier"] = LONG_RATE_MULTIPLIER
            cost["rates_per_mtok"] = {name: {key: value * LONG_RATE_MULTIPLIER for key, value in rates.items()}
                                       for name, rates in cost.get("rates_per_mtok", {}).items()}
        cost["notes"].append("Tier assumes one reported turn corresponds to one billed request; hidden retries cannot be ruled out.")
    return tokens, cost


def input_guard(case: Case, model: str, calibration: dict[str, Any] | None) -> dict[str, Any]:
    prompt_bytes = len(build_prompt(case).encode("utf-8"))
    ratio = 1.0  # Conservative byte-based estimate before any token calibration.
    method = "utf8_bytes_upper_estimate_plus_reserves"
    if calibration is not None:
        entry = calibration.get("models", {}).get(model)
        if calibration.get("version") != 1 or not entry or not 0 < entry["tokens_per_byte_with_margin"] <= 2:
            raise ValueError(f"No valid measured calibration for {model}")
        if calibration.get("chars_per_token") != case.config["chars_per_token"]:
            raise ValueError("Calibration and corpus characters/token settings differ")
        ratio = entry["tokens_per_byte_with_margin"]
        method = "pilot_total_prompt_tokens_per_byte_times_1.15_plus_reserves"
    estimated = math.ceil(prompt_bytes * ratio) + OVERHEAD_RESERVE + OUTPUT_RESERVE
    if estimated > CONTEXT_BUDGET:
        raise ValueError(f"{case.case_id}: estimated context {estimated} > {CONTEXT_BUDGET}; run short pilots, calibrate, or regenerate a smaller corpus. No request sent.")
    return {"method": method, "estimated_context_tokens": estimated, "tokens_per_byte": ratio,
            "context_budget": CONTEXT_BUDGET, "cli_overhead_reserve": OVERHEAD_RESERVE, "output_reserve": OUTPUT_RESERVE,
            "guaranteed_within_window": False}


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    # Independent seeds and repeats remain separate; cell summaries do not treat repeats as new problems.
    for record in records:
        dims = record["case_config"]
        groups[(dims["length"], dims["position"], dims["distraction"], dims["seed"])].append(record)
    for key, items in sorted(groups.items()):
        valid = [item for item in items if item["comparison_eligible"] and item["claude"]["status"] == "ok"]
        costs = [item["cost"]["api_equivalent_usd"] for item in items]
        rows.append({"length": key[0], "position": key[1], "distraction": key[2], "problem_seed": key[3],
                     "repeats": len(items), "eligible_trials": len(valid),
                     "extraction_accuracy_all_attempts": sum(item["scoring"]["extraction_correct"] and item["comparison_eligible"] and item["claude"]["status"] == "ok" for item in items) / len(items),
                     "composition_accuracy_all_attempts": sum(item["scoring"]["composition_correct"] and item["comparison_eligible"] and item["claude"]["status"] == "ok" for item in items) / len(items),
                     "eligible_extraction_accuracy": sum(item["scoring"]["extraction_correct"] for item in valid) / len(valid) if valid else None,
                     "eligible_composition_accuracy": sum(item["scoring"]["composition_correct"] for item in valid) / len(valid) if valid else None,
                     "strict_success_rate": sum(item["scoring"]["strict_success"] for item in items) / len(items),
                     "json_compliance_rate": sum(item["scoring"]["format_compliant"] for item in items) / len(items),
                     "omitted_facts": sum(item["scoring"]["omitted_facts"] for item in items),
                     "fabricated_values": sum(item["scoring"]["fabricated_values"] for item in items),
                     "wrong_entity_values": sum(item["scoring"]["wrong_entity_values"] for item in items),
                     "mean_citation_accuracy": sum(item["scoring"]["citation_accuracy"] for item in items) / len(items),
                     "prerequisites_correct_trials": sum(item["scoring"]["prerequisites_correct"] for item in valid),
                     "composition_failures_given_correct_facts": sum(item["scoring"]["composition_failure_given_correct_facts"] for item in valid),
                     "boundary_probe_failures": sum(not item["scoring"]["boundary_probes_match"] for item in items),
                     "mean_wall_seconds": sum(item["wall_seconds"] for item in items) / len(items),
                     "api_equivalent_usd_total": round(sum(costs), 6) if all(value is not None for value in costs) and all(item["cost"]["complete"] for item in items) else None,
                     "reported_prompt_tokens": [item["context"]["reported_prompt_tokens"] for item in items],
                     "thinking_tokens": [item["claude"].get("thinking_tokens") for item in items]})
    return {"completed_trials": len(records), "by_problem_cell": rows,
            "comparison_basis": "model_and_effort; Haiku 4.5 CLI default is not matched to Haiku 5.5 effort",
            "context_confirmation": "CLI observations only; API delivery/truncation and absence of compression remain unverified"}


def trial_schedule(cases: list[Case], runs: int, limit: int, seed: int) -> list[tuple[Case, int]]:
    schedule = [(case, repeat) for case in cases for repeat in range(1, runs + 1)]
    random.Random(seed).shuffle(schedule)
    return schedule[:limit]


def run_benchmark(cases: list[Case], *, model_label: str, effort: str | None, runs: int, limit: int,
                  results_dir: Path, command: list[str], timeout: float = 1200, schedule_seed: int = 20261014,
                  calibration: dict[str, Any] | None = None) -> Path:
    model = MODEL_IDS.get(model_label)
    if not model or (model_label, claude_cli.resolve_effort(model, effort)) not in CONDITIONS:
        raise ValueError("Only haiku45/default, haiku/medium and haiku/high are allowed")
    effort = claude_cli.resolve_effort(model, effort)
    if not cases or runs < 1 or limit < 1 or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Cases, positive runs/limit and a finite positive timeout are required")
    if claude_cli.nested_run_reason(os.environ):
        raise RuntimeError("Nested Claude Code execution is refused; use an independent terminal")
    schedule = trial_schedule(cases, runs, limit, schedule_seed)
    guards = {case.case_id: input_guard(case, model, calibration) for case, _ in schedule}
    env = claude_cli.child_environment(os.environ)
    env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = str(OUTPUT_RESERVE)
    preflight = claude_cli.preflight(command, env)
    version = re.search(r"(\d+)\.(\d+)\.(\d+)", preflight["version"])
    if model_label == "haiku" and (version is None or tuple(map(int, version.groups())) < (2, 1, 293)):
        raise RuntimeError("Haiku 5.5 requires Claude Code 2.1.293 or later; no model request was sent")
    if calibration is not None and preflight["version"] not in calibration["models"][model].get("cli_versions", []):
        raise ValueError("Calibration CLI version differs from this run; recalibrate with the current CLI")
    results_dir.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix=f"long_context_{model_label}_{effort}_", dir=results_dir))
    meta = {"benchmark": "long_context", "version": 1, "model": model, "effort": effort, "started_at": _now(),
            "claude_version": preflight["version"], "auth_method": preflight["auth_method"], "requested_trials": len(schedule),
            "schedule_seed": schedule_seed, "schedule": [{"case_id": case.case_id, "repeat": repeat} for case, repeat in schedule],
            "tool_policy": "no_builtin_or_mcp_tools", "input_transport": "stdin_stream_json_single_user_message",
            "reasoning_settings": {"effort_flag": None if effort == "default" else effort,
                                   "effective_thinking_budget": None, "thinking_budget_override": None,
                                   "environment": {name: env.get(name) for name in ("MAX_THINKING_TOKENS", "CLAUDE_CODE_EFFORT_LEVEL", "CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING", "CLAUDE_CODE_DISABLE_THINKING")},
                                   "output_token_reserve": OUTPUT_RESERVE},
            "context_environment": {name: env.get(name) for name in ("DISABLE_COMPACT", "CLAUDE_CODE_AUTO_COMPACT_WINDOW", "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE",
                                    "CLAUDE_CODE_MAX_CONTEXT_TOKENS", "CLAUDE_CODE_MAX_TURNS", "DISABLE_PROMPT_CACHING", "DISABLE_PROMPT_CACHING_HAIKU", "CLAUDE_CODE_MAX_RETRIES")},
            "calibration": calibration, "input_guards": guards, "pricing_source": PRICING_SOURCE_URL,
            "pricing_checked_on": CHECKED_ON, "base_rates_per_mtok": PRICES_PER_MTOK,
            "source_sha256": {name: hashlib.sha256((PROJECT_ROOT / "ai_lab" / name).read_bytes()).hexdigest()
                              for name in ("long_context_data.py", "long_context_scoring.py", "long_context_benchmark.py")}}
    _write_json(output / "experiment.json", meta)
    for case in {case.case_id: case for case, _ in schedule}.values():
        save_case(case, output / "cases" / case.case_id)
    records = []
    for index, (case, repeat) in enumerate(schedule, 1):
        directory = output / f"trial_{index:03d}"
        directory.mkdir()
        prompt = build_prompt(case)
        payload = json.dumps({"type": "user", "message": {"role": "user", "content": prompt}}, ensure_ascii=False) + "\n"
        (directory / "stdin.jsonl").write_bytes(payload.encode("utf-8"))
        started = _now()
        with tempfile.TemporaryDirectory(prefix="ai-lab-long-") as isolated:
            run = invoke_stdin(command, build_args(model, effort), payload, cwd=isolated, env=env, timeout=timeout)
        (directory / "claude_stdout.txt").write_bytes(run.stdout.encode("utf-8"))
        (directory / "claude_stderr.txt").write_bytes(run.stderr.encode("utf-8"))
        cli = claude_cli.summarize_run(run)
        context = telemetry(run, cli, prompt, model)
        tokens, cost = price_long_trial(cli, model, context)
        answer = cli.get("result_text")
        (directory / "answer.txt").write_bytes((answer if isinstance(answer, str) else "").encode("utf-8"))
        scoring = score_response(answer, case, execution_error=cli["status"] if cli["status"] != "ok" else None)
        match = check_model(cli, model)
        actual_context = context["reported_prompt_tokens"]
        ceiling = min(CONTEXT_BUDGET, context["reported_context_window"] or CONTEXT_BUDGET)
        alerts = []
        if match["status"] != "match" or context["assistant_model_check"] == "mismatch": alerts.append("model_unverified_or_mismatch")
        if context["stdin_echo_status"] == "mismatch": alerts.append("stdin_echo_mismatch")
        if context["compaction_events"]: alerts.append("compaction_observed")
        if context["tool_uses_observed"]: alerts.append("tool_use_observed")
        if cli.get("num_turns") != 1: alerts.append("single_turn_unverified")
        if actual_context is None: alerts.append("input_usage_unavailable")
        elif actual_context + OUTPUT_RESERVE > ceiling: alerts.append("context_budget_exceeded")
        record = {"benchmark": "long_context", "model": model, "effort": effort, "case_id": case.case_id,
                  "case_config": case.config, "repeat": repeat, "started_at": started, "finished_at": _now(),
                  "prompt_sha256": digest(prompt), "stdin_sha256": digest(payload), "wall_seconds": round(run.wall_seconds, 3),
                  "claude": cli, "model_check": match, "context": context, "context_alerts": alerts,
                  "comparison_eligible": not alerts, "tokens": tokens, "cost": cost, "scoring": scoring}
        _write_json(directory / "trial.json", record)
        records.append(record)
        _write_json(output / "summary.json", {**meta, **summarize(records)})
        print(f"[{index}/{len(schedule)}] {case.case_id} repeat={repeat} extraction={scoring['extraction_correct']} composition={scoring['composition_correct']} alerts={alerts}")
        if alerts or cli["status"] != "ok":
            print("Stopping after an execution/context anomaly; completed records are preserved.")
            break
    return output


def calibrate(directories: list[Path], output_file: Path) -> dict[str, Any]:
    ratios: dict[str, list[float]] = defaultdict(list)
    versions: dict[str, set[str]] = defaultdict(set)
    sources = []
    chars_per_token = set()
    for directory in directories:
        meta = json.loads((directory / "experiment.json").read_text(encoding="utf-8"))
        if meta.get("benchmark") != "long_context":
            raise ValueError("Calibration requires long-context pilot results")
        for path in sorted(directory.glob("trial_*/trial.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            if not record["comparison_eligible"] or record["claude"]["status"] != "ok" or record["context"]["stdin_echo_status"] != "match":
                raise ValueError(f"Pilot telemetry is insufficient for calibration: {path}")
            case = load_case(directory / "cases" / record["case_id"])
            chars_per_token.add(case.config["chars_per_token"])
            ratios[record["model"]].append(record["context"]["reported_prompt_tokens"] / len(build_prompt(case).encode("utf-8")))
            versions[record["model"]].add(meta["claude_version"])
            sources.append({"trial_file": str(path.resolve()), "trial_sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    if not ratios or len(chars_per_token) != 1:
        raise ValueError("Calibration requires compatible nonempty pilots")
    result = {"version": 1, "created_at": _now(), "chars_per_token": chars_per_token.pop(), "sources": sources,
              "models": {model: {"pilot_trials": len(values), "max_observed_tokens_per_byte": max(values),
                                  "tokens_per_byte_with_margin": max(values) * 1.15, "cli_versions": sorted(versions[model])} for model, values in ratios.items()},
              "guaranteed_within_window": False, "note": "Empirical conservative estimate, not a tokenizer or a guarantee. Includes CLI overhead and adds further reserves."}
    with output_file.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return result


def export_report(directories: list[Path], output_dir: Path) -> None:
    entries = []
    all_trials = []
    hashes = {}
    seen_files = set()
    for directory in directories:
        meta = json.loads((directory / "experiment.json").read_text(encoding="utf-8"))
        if meta.get("benchmark") != "long_context": raise ValueError("Not a long-context experiment")
        trials = []
        for trial_dir in sorted(path for path in directory.iterdir() if path.is_dir() and path.name.startswith("trial_")):
            path = trial_dir / "trial.json"
            if path.resolve() in seen_files:
                raise ValueError("The same trial file was selected more than once")
            seen_files.add(path.resolve())
            record = json.loads(path.read_text(encoding="utf-8"))
            case = load_case(directory / "cases" / record["case_id"])
            if (record["model"] != meta["model"] or record["effort"] != meta["effort"]
                    or record["prompt_sha256"] != digest(build_prompt(case))):
                raise ValueError("Trial conditions or prompt hashes differ from saved inputs")
            if record["case_id"] in hashes and hashes[record["case_id"]] != record["prompt_sha256"]:
                raise ValueError("Different documents cannot be compared under one case ID")
            hashes[record["case_id"]] = record["prompt_sha256"]
            trials.append(record)
            all_trials.append({"experiment": directory.name, **record})
        for row in summarize(trials)["by_problem_cell"]:
            entries.append({"experiment": directory.name, "model": meta["model"], "effort": meta["effort"], **row})
    if not entries: raise ValueError("No completed trials")
    protected = [directory.resolve() for directory in directories] + [(PROJECT_ROOT / name).resolve() for name in ("results", "benchmarks", "problems", "data")]
    destination = output_dir.resolve()
    if any(destination == root or destination.is_relative_to(root) for root in protected):
        raise ValueError("Report output must be a new directory outside source results and datasets")
    destination.mkdir(parents=True, exist_ok=False)
    with (destination / "summary.csv").open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(entries[0]))
        writer.writeheader(); writer.writerows(entries)
    trial_rows = []
    for record in all_trials:
        row = {"experiment": record["experiment"], "model": record["model"], "effort": record["effort"],
               "case_id": record["case_id"], "problem_seed": record["case_config"]["seed"],
               "length": record["case_config"]["length"], "position": record["case_config"]["position"],
               "distraction": record["case_config"]["distraction"], "repeat": record["repeat"],
               "target_document_tokens": record["case_config"]["target_tokens"], "document_tokens_measured": None,
               "reported_prompt_tokens": record["context"]["reported_prompt_tokens"],
               "thinking_tokens": record["claude"].get("thinking_tokens"), "wall_seconds": record["wall_seconds"],
               "api_equivalent_usd": record["cost"]["api_equivalent_usd"], "cost_complete": record["cost"]["complete"],
               "model_check": record["model_check"]["status"], "comparison_eligible": record["comparison_eligible"],
               "context_alerts": ";".join(record["context_alerts"]), "stdin_echo_status": record["context"]["stdin_echo_status"]}
        row.update({f"tokens_{name}": (record["tokens"] or {}).get(name) for name in ("input", "output", "cache_read", "cache_write")})
        row.update({key: record["scoring"][key] for key in ("original_json_valid", "schema_valid", "format_compliant", "fence_recovered", "content_scorable",
                    "extraction_correct", "prerequisites_correct", "composition_correct", "composition_failure_given_correct_facts",
                    "strict_success", "fact_accuracy", "omitted_facts", "fabricated_values", "wrong_entity_values", "citation_accuracy", "unsupported_citations")})
        trial_rows.append(row)
    # Merge repeats spread over separate pilot runs, then compare identical seeded cells.
    cells = defaultdict(list)
    for record in all_trials:
        dims = record["case_config"]
        cells[(record["model"], record["effort"], dims["seed"], dims["position"], dims["distraction"], dims["length"])].append(record)
    changes = []
    for key, items in sorted(cells.items()):
        if key[-1] == "short": continue
        shorter = cells.get((*key[:-1], "short"))
        if not shorter: continue
        for metric in ("extraction_correct", "composition_correct"):
            def accuracy(values):
                return sum(row["scoring"][metric] and row["comparison_eligible"] and row["claude"]["status"] == "ok" for row in values) / len(values)
            short_accuracy = accuracy(shorter)
            long_accuracy = accuracy(items)
            changes.append({"model": key[0], "effort": key[1], "problem_seed": key[2], "position": key[3], "distraction": key[4],
                            "length": key[5], "metric": metric, "short_trials": len(shorter), "longer_trials": len(items),
                            "short_accuracy": short_accuracy, "longer_accuracy": long_accuracy, "longer_minus_short": long_accuracy - short_accuracy})
    contrasts = []
    old = {(row["problem_seed"], row["position"], row["distraction"], row["length"], row["metric"]): row
           for row in changes if row["model"] == MODEL_IDS["haiku45"] and row["effort"] == "default"}
    for row in changes:
        matched = old.get((row["problem_seed"], row["position"], row["distraction"], row["length"], row["metric"]))
        if row["model"] == MODEL_IDS["haiku"] and matched:
            contrasts.append({**{key: row[key] for key in ("effort", "problem_seed", "position", "distraction", "length", "metric")},
                              "haiku45_length_change": matched["longer_minus_short"], "haiku55_length_change": row["longer_minus_short"],
                              "haiku55_minus_haiku45_change": row["longer_minus_short"] - matched["longer_minus_short"]})
    for filename, rows in (("trials.csv", trial_rows), ("paired_length_changes.csv", changes), ("hypothesis_comparisons.csv", contrasts)):
        if rows:
            with (destination / filename).open("x", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader(); writer.writerows(rows)
    _write_json(destination / "analysis.json", {"benchmark": "long_context", "rows": entries, "prompt_hashes": hashes,
                                               "paired_length_changes": changes, "hypothesis_comparisons": contrasts})
    (destination / "report.md").write_text(
        f"# Long-context comparison\n\n{len(all_trials)} trials, {len(hashes)} case IDs, {len(changes)} paired length changes, {len(contrasts)} model contrasts. "
        "See summary.csv for seed/length/position/distraction cells and repeat variation; trials.csv retains measured usage and individual scores.\n\n"
        "Compare identical case IDs across model conditions; compute each seed's long-minus-short change, then compare those changes between models. "
        "A positive haiku55_minus_haiku45_change means less deterioration as input grows; it is descriptive, not proof. "
        "Do not count repeats as independent problems. Report all attempts and excluded context/execution anomalies together. "
        "Missing length/model pairs produce no contrast; unmatched repeat counts need caution.\n\n"
        "Haiku 4.5/default and Haiku 5.5/medium or high have different reasoning settings. Character targets are estimates; "
        "reported prompt tokens include CLI system/cache tokens. API delivery, truncation and absence of compression remain unverified.\n",
        encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ai_lab.long_context_benchmark")
    commands = parser.add_subparsers(dest="command", required=True)
    gen = commands.add_parser("generate")
    gen.add_argument("--output-dir", type=Path, required=True)
    gen.add_argument("--seeds", nargs="+", type=int, default=[101, 103, 104])
    gen.add_argument("--lengths", nargs="+", choices=LENGTHS, default=list(DEFAULT_LENGTHS))
    gen.add_argument("--positions", nargs="+", choices=POSITIONS, default=list(POSITIONS))
    gen.add_argument("--distractions", nargs="+", choices=DISTRACTIONS, default=list(DISTRACTIONS))
    gen.add_argument("--chars-per-token", type=float, default=4.0)
    for name in ("validate", "plan", "run"):
        sub = commands.add_parser(name)
        sub.add_argument("corpus", type=Path)
        if name in ("plan", "run"): sub.add_argument("--runs", type=int, default=2 if name == "plan" else 1)
        if name == "run":
            sub.add_argument("--model", choices=("haiku45", "haiku"), default="haiku45")
            sub.add_argument("--effort", choices=("default", "medium", "high"))
            sub.add_argument("--length", choices=LENGTHS)
            sub.add_argument("--case-id")
            sub.add_argument("--limit", type=int, default=1)
            sub.add_argument("--timeout", type=float, default=1200)
            sub.add_argument("--schedule-seed", type=int, default=20261014)
            sub.add_argument("--calibration", type=Path)
            sub.add_argument("--results-dir", type=Path, default=PROJECT_ROOT / "results" / "long_context_runs")
            sub.add_argument("--claude-bin")
            sub.add_argument("--dry-run", action="store_true")
    cal = commands.add_parser("calibrate")
    cal.add_argument("dirs", nargs="+", type=Path)
    cal.add_argument("--output-file", type=Path, required=True)
    report = commands.add_parser("report")
    report.add_argument("dirs", nargs="+", type=Path)
    report.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "generate":
            generate(args.output_dir, args.seeds, args.lengths, args.positions, args.distractions, args.chars_per_token)
            print(f"Corpus generated: {args.output_dir}")
        elif args.command == "calibrate": print(json.dumps(calibrate(args.dirs, args.output_file), indent=2))
        elif args.command == "report": export_report(args.dirs, args.output_dir)
        else:
            cases = corpus_cases(args.corpus)
            if args.command == "validate": print(f"{len(cases)} cases: regenerated inputs, gold and hashes match")
            elif args.command == "plan": print(json.dumps(plan(cases, args.runs), ensure_ascii=False, indent=2))
            else:
                cases = [case for case in cases if (not args.length or case.config["length"] == args.length) and (not args.case_id or case.case_id == args.case_id)]
                model = MODEL_IDS[args.model]
                effort = claude_cli.resolve_effort(model, args.effort)
                if (args.model, effort) not in CONDITIONS or not cases or args.runs < 1 or args.limit < 1 or not math.isfinite(args.timeout) or args.timeout <= 0:
                    raise ValueError("Invalid condition, case selection, repeat count, limit or timeout")
                calibration = json.loads(args.calibration.read_text(encoding="utf-8")) if args.calibration else None
                if args.dry_run:
                    scheduled = []
                    for case, repeat in trial_schedule(cases, args.runs, args.limit, args.schedule_seed):
                        try:
                            guard = {"status": "estimate_pass", **input_guard(case, model, calibration)}
                        except ValueError as exc:
                            guard = {"status": "blocked", "reason": str(exc)}
                        scheduled.append({"case_id": case.case_id, "repeat": repeat, "guard": guard})
                    print(json.dumps({"model": model, "effort": effort, "calls": min(len(cases) * args.runs, args.limit),
                                      "schedule": scheduled, "input_transport": "stdin_stream_json",
                                      "model_invoked": False, "requires_context_guard": True,
                                      "cli_version_checked": False, "haiku55_minimum_cli_version": "2.1.293"}, indent=2))
                else:
                    command = [args.claude_bin] if args.claude_bin else claude_cli.find_claude_command()
                    claude_cli.check_native_executable(command[0])
                    path = run_benchmark(cases, model_label=args.model, effort=effort, runs=args.runs, limit=args.limit,
                                         results_dir=args.results_dir, command=command, timeout=args.timeout,
                                         schedule_seed=args.schedule_seed, calibration=calibration)
                    print(f"Results: {path}")
        return 0
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        print(f"Long-context error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted; completed trial records are preserved.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
