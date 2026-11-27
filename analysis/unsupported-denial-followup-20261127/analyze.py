"""Audit local CLI records and verify the published data without a model call."""
import argparse
import json
import statistics
from collections import Counter

from runner import HERE, OUT, PROMPTS, cases, first_prompt, fixed_state, initial, order, read_json
from score import grade

PHASES = ("first", "A", "B")


def audit_record(item, phase, record, parent):
    if record is None:
        return None
    stem = OUT / item["id"] / phase
    prompt = stem.with_name(f"{phase}-prompt.txt").read_text(encoding="utf-8")
    raw = stem.with_name(f"{phase}-stream.jsonl").read_text(encoding="utf-8")
    assert prompt == (first_prompt(item) if phase == "first" else PROMPTS[phase])
    assert initial.sha(prompt) == record["prompt_sha256"]
    assert initial.sha(raw) == record["raw_sha256"]
    parsed = initial.claude_cli.summarize_run(initial.claude_cli.CliRun(
        record["returncode"], raw, "", record["wall_seconds"], record["timed_out"]))
    assert record["phase"] == phase
    assert record["session_id"] == parsed["session_id"]
    assert record["model_check"] == initial.check_model(parsed, initial.MODEL)
    assert record["thinking_tokens"] == parsed["thinking_tokens"]
    assert record["status"] == parsed["status"] and record["result_text"] == parsed["result_text"]
    assert record["cli_duration_ms"] == parsed["duration_ms"]
    tokens, cost = initial.price_trial(parsed, initial.MODEL)
    assert tokens == record["tokens"] and cost == record["cost"]
    assert record["cli_reported_usd"] == parsed["cli_total_cost_usd"]
    assert record["tool_use_count"] == initial.tool_count(raw)
    assert record["permission_denials"] == parsed["permission_denials"]
    assert record["requested_parent"] == parent
    if phase == "first" and parsed["status"] == "ok" and not record["invalid_stop"]:
        assert record["requested_session"] == parsed["session_id"]
    valid = initial.valid(record) and not record["invalid_stop"]
    session = record["session_id"]
    result = {key: record[key] for key in (
        "status", "model_check", "wall_seconds", "cli_duration_ms", "thinking_tokens", "tokens",
        "cli_reported_usd", "raw_sha256", "prompt_sha256", "tool_use_count", "permission_denials",
        "invalid_stop")}
    result.update({"valid": valid, "session_sha256": initial.sha(session) if session else None,
                   "parent_sha256": initial.sha(parent) if parent else None,
                   "answer_text": parsed["result_text"] if valid else None,
                   "api_equivalent_usd": cost["api_equivalent_usd"],
                   "api_cost_complete": cost["complete"],
                   "cache_write_tokens_by_ttl": cost.get("cache_write_tokens_by_ttl"),
                   "cache_write_ttl_assumed": cost.get("cache_write_ttl_assumed")})
    return result


def distribution(values):
    return {"n": len(values), "median": statistics.median(values) if values else None,
            "min": min(values, default=None), "max": max(values, default=None)}


def condition_counts(rows):
    counts = Counter({key: 0 for key in ("correct", "wrong", "withdrawn", "unresolved",
                                        "invalid", "not_run", "format_ok")})
    for record in rows:
        if record is None:
            counts["not_run"] += 1
        elif not record["valid"]:
            counts["invalid"] += 1
        else:
            counts[record["grade"]["content"]] += 1
            counts["format_ok"] += int(record["grade"]["format_ok"])
    return dict(counts)


def usage(rows):
    calls = [row for row in rows if row is not None]
    result = {"calls": len(calls)}
    for field in ("wall_seconds", "thinking_tokens", "cli_reported_usd", "api_equivalent_usd"):
        values = [row[field] for row in calls if row[field] is not None]
        result[field] = {
            "n": len(values),
            "sum": round(sum(values), 6) if values else None,
            "median": statistics.median(values) if values else None,
        }
    for field in ("input", "output", "cache_read", "cache_write"):
        values = [row["tokens"][field] for row in calls if row["tokens"] is not None]
        result[field + "_tokens"] = {"n": len(values), "sum": sum(values) if values else None}
    return result


def summarize(public):
    pairs = [row for row in public if all(row[p] and row[p]["valid"] for p in ("A", "B"))]
    eligible = [row for row in public if row["first"] and row["first"]["valid"]
                and row["first"]["grade"]["content"] == "correct"]
    both_correct = []
    outcomes = Counter({"both_maintained": 0, "only_A": 0, "only_B": 0, "neither": 0})
    for row in pairs:
        a, b = (row[p]["grade"]["content"] == "correct" for p in ("A", "B"))
        if a and b:
            both_correct.append(row)
        outcome = {(True, True): "both_maintained", (True, False): "only_A",
                   (False, True): "only_B", (False, False): "neither"}[a, b]
        outcomes[outcome] += 1
    metrics = {}
    for field in ("thinking_tokens", "wall_seconds"):
        known = [row for row in pairs if all(row[p][field] is not None for p in ("A", "B"))]
        metrics[field] = {p: distribution([row[p][field] for row in known]) for p in ("A", "B")}
        metrics[field]["B_minus_A"] = distribution([round(row["B"][field] - row["A"][field], 6)
                                                     for row in known])
    return {
        "planned_cases": len(public), "eligible_first": len(eligible), "complete_pairs": len(pairs),
        "first": condition_counts([row["first"] for row in public]),
        "branches": {p: condition_counts([row[p] for row in eligible]) for p in ("A", "B")},
        "paired_counts": {p: condition_counts([row[p] for row in pairs]) for p in ("A", "B")},
        "pair_outcomes": dict(outcomes),
        "maintained_pair_format": {p: sum(row[p]["grade"]["format_ok"] for row in both_correct)
                                   for p in ("A", "B")},
        "groups": {group: {"pairs": len(group_rows),
                           **{p: condition_counts([row[p] for row in group_rows]) for p in ("A", "B")}}
                   for group in sorted({row["group"] for row in public})
                   for group_rows in [[r for r in pairs if r["group"] == group]]},
        "paired_metrics": metrics,
        "usage": {p: usage([row[p] for row in public]) for p in PHASES},
    }


def audit():
    frozen = read_json(OUT / "frozen.json")
    current = fixed_state()
    current["revision"] = frozen["revision"]
    current["plan"] = json.loads(json.dumps(current["plan"]))
    assert frozen == current
    progress = read_json(OUT / "progress.json")
    assert progress["finished"]
    planned = cases()
    assert [row["id"] for row in progress["records"]] == [item["id"] for item in planned[:len(progress["records"])]]
    records = {row["id"]: row for row in progress["records"]}
    public = []
    for item in planned:
        row = records.get(item["id"], {})
        parent = row["first"]["session_id"] if row else None
        result = {key: item[key] for key in ("id", "group", "level")}
        for phase in PHASES:
            record = audit_record(item, phase, row.get(phase), None if phase == "first" else parent)
            if record:
                record["grade"] = grade(record["answer_text"], item["answer"]) if record["valid"] else None
            result[phase] = record
        public.append(result)
    preflight = read_json(OUT / "preflight.json")
    preflight.pop("auth_volume")
    initial.dump(HERE / "public-runs.json", public)
    initial.dump(HERE / "summary.json", {
        "locked": frozen, "preflight": preflight, "stop": progress["stop"], "results": summarize(public)})
    verify()


def verify():
    public = read_json(HERE / "public-runs.json")
    summary = read_json(HERE / "summary.json")
    assert len(public) == len(cases())
    seen = set()
    for i, (item, row) in enumerate(zip(cases(), public), 1):
        assert item["id"] == row["id"] and item["group"] == row["group"] and item["level"] == row["level"]
        assert list(order(i)) == summary["locked"]["plan"][i-1]["branch_order"]
        first = row["first"]
        for phase in ("first", *order(i)):
            record = row[phase]
            if record is None:
                continue
            sid = record["session_sha256"]
            if record["valid"]:
                assert sid and sid not in seen
                assert record["model_check"]["status"] == "match"
                assert record["tool_use_count"] == record["permission_denials"] == 0
                assert record["grade"] == grade(record["answer_text"], item["answer"])
            if sid:
                seen.add(sid)
            if phase == "first":
                assert record["parent_sha256"] is None
                assert record["prompt_sha256"] == initial.sha(first_prompt(item))
            else:
                assert first["valid"] and first["grade"]["content"] == "correct"
                assert record["parent_sha256"] == first["session_sha256"] and (sid != first["session_sha256"] or not record["valid"])
                assert record["prompt_sha256"] == initial.sha(PROMPTS[phase])
    computed = summarize(public)
    assert computed == summary["results"]
    print(json.dumps({key: computed[key] for key in ("planned_cases", "eligible_first", "complete_pairs",
                     "pair_outcomes", "paired_counts", "paired_metrics")}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("audit", "verify"))
    if parser.parse_args().mode == "audit":
        audit()
    else:
        verify()
