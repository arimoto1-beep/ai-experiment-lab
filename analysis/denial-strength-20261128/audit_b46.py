"""Audit B46 locally and verify the published observations without a model call."""
import argparse
import importlib.util
import json
from collections import Counter
from decimal import Decimal

from run_b46 import (
    HERE, OUT, PHASES, PREVIOUS, PROMPTS, cases, first_prompt, fixed_state, grade, initial,
    parse_stream, plan, read_json, stop_reason,
)
from ai_lab.pricing import LONG_PROMPT_THRESHOLD_TOKENS, PRICES_PER_MTOK, TokenCounts, cost_usd

previous_analysis_spec = importlib.util.spec_from_file_location("b07_paired_analysis", PREVIOUS / "analyze.py")
previous_analysis = importlib.util.module_from_spec(previous_analysis_spec)
previous_analysis_spec.loader.exec_module(previous_analysis)
condition_counts = previous_analysis.condition_counts
distribution = previous_analysis.distribution

TOKEN_FIELDS = {"input": "input_tokens", "output": "output_tokens",
                "cache_read": "cache_read_input_tokens", "cache_write": "cache_creation_input_tokens"}
RATES = PRICES_PER_MTOK[initial.MODEL]
METRICS = ("thinking_tokens", "wall_seconds", "api_equivalent_usd", "cli_turn_usd")


def count(mapping, key):
    value = mapping.get(key) if isinstance(mapping, dict) else None
    return value if type(value) is int and value >= 0 else None


def tokens_from(result):
    usage = result.get("usage")
    if not isinstance(usage, dict):
        usage = {}
    return {"tokens": {name: count(usage, field) for name, field in TOKEN_FIELDS.items()},
            "thinking_tokens": count(usage.get("output_tokens_details"), "thinking_tokens"),
            "cache_write_by_ttl": {ttl: count(usage.get("cache_creation"), f"ephemeral_{ttl}_input_tokens")
                                   for ttl in ("5m", "1h")}}


def api_cost(record):
    if any(value is None for value in record["tokens"].values()):
        return None
    tokens = TokenCounts(**record["tokens"])
    if tokens.prompt_tokens > LONG_PROMPT_THRESHOLD_TOKENS[initial.MODEL]:
        return None
    ttl = record["cache_write_by_ttl"]
    if tokens.cache_write and (None in ttl.values() or sum(ttl.values()) != tokens.cache_write):
        return None
    return round(cost_usd(initial.MODEL, TokenCounts(tokens.input, tokens.output, tokens.cache_read, 0))
                 + sum(cost_usd(initial.MODEL, TokenCounts(cache_write=value or 0), key)
                       for key, value in ttl.items() if tokens.cache_write), 10)


def reconcile(record, parent):
    cumulative = record["model_usage_tokens"]
    previous = parent["model_usage_tokens"] if parent else dict.fromkeys(TOKEN_FIELDS, 0)
    matches = bool(cumulative and previous) and all(
        record["tokens"][name] == cumulative[name] - previous[name] for name in TOKEN_FIELDS
    )
    cli = record["cli_cumulative_usd"]
    parent_cli = parent["cli_cumulative_usd"] if parent else 0
    turn_cli = None
    if cli is not None and parent_cli is not None and cli >= parent_cli and (parent is None or matches):
        turn_cli = float(Decimal(str(cli)) - Decimal(str(parent_cli)))
    return {"usage_matches_model_delta": matches, "cli_turn_usd": turn_cli,
            "api_equivalent_usd": api_cost(record) if record["model_check"] == "match" else None}


def read_attempt(item, attempt, phase, parent, seen, timeouts):
    path = OUT / item["id"]
    prompt = (path / f"{phase}-prompt.txt").read_text(encoding="utf-8")
    raw = (path / f"{phase}-stream.jsonl").read_text(encoding="utf-8")
    stderr = (path / f"{phase}-stderr.txt").read_text(encoding="utf-8")
    assert prompt == (first_prompt(item) if phase == "first" else PROMPTS[phase])
    assert initial.sha(prompt) == attempt["prompt_sha256"] and initial.sha(raw) == attempt["raw_sha256"]
    parsed = initial.claude_cli.summarize_run(initial.claude_cli.CliRun(
        attempt["returncode"], raw, stderr, attempt["wall_seconds"], attempt["timed_out"]))
    assert all(attempt[key] == parsed[key] for key in ("status", "session_id", "result_text", "permission_denials"))
    assert attempt["model_check"] == initial.check_model(parsed, initial.MODEL)
    assert attempt["tool_use_count"] == initial.tool_count(raw)
    assert attempt["requested_parent"] == parent
    check, result = parse_stream(raw)
    stop = stop_reason(attempt, check, seen, timeouts, raw + stderr if attempt["status"] == "error" else "")
    assert stop == attempt["invalid_stop"]
    sid = attempt["session_id"]
    if sid:
        seen.add(sid)
    valid = initial.valid(attempt) and stop is None
    if valid and phase == "first":
        assert attempt["requested_session"] == sid
    answer = parsed["result_text"] if valid else None
    return {
        "phase": phase, "status": parsed["status"], "valid": valid, "stop": stop, **check,
        "timed_out": attempt["timed_out"], "model_check": attempt["model_check"]["status"],
        "model_usage_models": sorted(parsed["model_usage"]) if valid and parsed["model_usage"] else [],
        "tool_use_count": attempt["tool_use_count"], "permission_denials": parsed["permission_denials"],
        "start_offset_seconds": attempt["start_offset_seconds"], "wall_seconds": attempt["wall_seconds"],
        "answer_text": answer, "grade": grade(answer, item["answer"]) if valid else None,
        "prompt_sha256": initial.sha(prompt), "raw_sha256": initial.sha(raw),
        "session_sha256": initial.sha(sid) if sid else None, "parent_sha256": initial.sha(parent) if parent else None,
        **tokens_from(result), "model_usage_tokens": attempt["tokens"] if parsed["model_usage"] else None,
        "cli_cumulative_usd": parsed["cli_total_cost_usd"],
    }


def summarize(rows):
    eligible = [row for row in rows if correct(row["first"])]
    complete = [row for row in eligible if all(row[p] and row[p]["valid"] for p in PROMPTS)]
    outcomes = Counter({label: 0 for label in ("both", "W_only", "S_only", "neither")})
    for row in complete:
        outcomes[{(True, True): "both", (True, False): "W_only", (False, True): "S_only",
                  (False, False): "neither"}[correct(row["W"]), correct(row["S"])]] += 1
    metrics = {}
    for field in METRICS:
        known = [row for row in complete if all(row[p][field] is not None for p in PROMPTS)]
        metrics[field] = {p: distribution([row[p][field] for row in known]) for p in PROMPTS}
        for later, earlier in (("S", "W"), ("W", "N"), ("S", "N")):
            diffs = [round(row[later][field] - row[earlier][field], 10) for row in known]
            metrics[field][f"{later}_minus_{earlier}"] = {
                **distribution(diffs), "increase": sum(x > 0 for x in diffs),
                "decrease": sum(x < 0 for x in diffs), "tie": diffs.count(0),
            }
    totals = {}
    for phase in (*PHASES, "all"):
        calls = [row[p] for row in rows for p in PHASES if (phase in (p, "all")) and row[p]]
        totals[phase] = {"calls": len(calls), "usage_delta_matches": sum(r["usage_matches_model_delta"] for r in calls)}
        for field in METRICS:
            values = [r[field] for r in calls if r[field] is not None]
            totals[phase][field] = {"n": len(values), "sum": round(sum(values), 10) if values else None}
    return {
        "planned_cases": len(rows), "first": condition_counts([row["first"] for row in rows]),
        "eligible_first": len(eligible), "complete_groups": len(complete),
        "branches": {p: condition_counts([row[p] for row in eligible]) for p in PROMPTS},
        "complete_group_counts": {p: condition_counts([row[p] for row in complete]) for p in PROMPTS},
        "by_topic": {topic: {p: condition_counts([row[p] for row in complete if row["group"] == topic])
                             for p in PROMPTS} for topic in sorted({row["group"] for row in rows})},
        "primary_S_vs_W": {"outcomes": dict(outcomes), "S_minus_W_rate":
                           (outcomes["S_only"] - outcomes["W_only"]) / len(complete) if complete else None},
        "metrics": metrics, "totals": totals,
    }


def correct(record):
    return bool(record and record["valid"] and record["grade"]["content"] == "correct")


def audit():
    frozen, current = read_json(OUT / "frozen.json"), fixed_state()
    assert current == {**frozen, "revision": current["revision"]}
    progress = read_json(OUT / "progress.json")
    assert progress["finished"]
    attempts = iter(progress["records"])
    attempt = next(attempts, None)
    public, seen = [], set()
    timeouts = 0
    for item, step in zip(cases(), plan()):
        row = {**{key: item[key] for key in ("id", "group", "level")}, **dict.fromkeys(PHASES)}
        parent = None
        for phase in ("first", *step["branch_order"]):
            if attempt is None or (phase != "first" and not correct(row["first"])):
                break
            assert (attempt["id"], attempt["phase"]) == (item["id"], phase)
            timeouts = timeouts + 1 if attempt["timed_out"] else 0
            record = read_attempt(item, attempt, phase, parent, seen, timeouts)
            record.update(reconcile(record, row["first"] if phase != "first" else None))
            row[phase] = record
            if phase == "first":
                parent = attempt["session_id"]
            attempt = next(attempts, None)
            if record["stop"]:
                assert attempt is None and record["stop"] == progress["stop"]
                break
        public.append(row)
    assert attempt is None
    preflight = read_json(OUT / "preflight.json")
    preflight.pop("auth_volume")
    initial.dump(HERE / "public-runs.json", public)
    initial.dump(HERE / "summary.json", {"locked": frozen, "preflight": preflight,
                 "stop": progress["stop"], "rates_usd_per_mtok": RATES, "results": summarize(public)})
    verify()


def verify():
    rows, summary = (read_json(HERE / name) for name in ("public-runs.json", "summary.json"))
    assert len(rows) == len(cases()) and summary["locked"]["plan"] == plan()
    assert summary["locked"]["followups"] == PROMPTS and summary["rates_usd_per_mtok"] == RATES
    seen = set()
    earliest_start = 0
    ended = False
    for item, row, step in zip(cases(), rows, plan()):
        assert all(item[key] == row[key] for key in ("id", "group", "level"))
        first = row["first"]
        for phase in ("first", *(step["branch_order"] if correct(first) else ())):
            record = row[phase]
            if record is None:
                ended = True
                continue
            assert not ended and record["phase"] == phase
            parent = first if phase != "first" else None
            assert record["parent_sha256"] == (parent["session_sha256"] if parent else None)
            assert record["prompt_sha256"] == initial.sha(PROMPTS[phase] if parent else first_prompt(item))
            assert earliest_start <= record["start_offset_seconds"] < summary["locked"]["time_to_last_start_seconds"]
            earliest_start = record["start_offset_seconds"]
            assert all(record[key] == value for key, value in reconcile(record, parent).items())
            sid = record["session_sha256"]
            if record["valid"]:
                assert sid and sid not in seen and record["model_check"] == "match"
                assert record["status"] == "ok" and record["init_verified"] and record["num_turns"] == 1
                assert record["tool_use_count"] == record["permission_denials"] == 0
                assert not record["advertised_tools_or_mcp"] and record["stop"] is None
                assert record["grade"] == grade(record["answer_text"], item["answer"])
            if sid:
                seen.add(sid)
        if not correct(first):
            assert all(row[p] is None for p in PROMPTS)
    assert summary["results"] == summarize(rows)
    print(json.dumps({"verified_cases": len(rows), "verified_calls": summary["results"]["totals"]["all"]["calls"],
                      "complete_groups": summary["results"]["complete_groups"], "stop": summary["stop"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("audit", "verify"))
    (audit if parser.parse_args().mode == "audit" else verify)()
