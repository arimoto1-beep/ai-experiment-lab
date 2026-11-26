"""Audit private B36 streams and score four independently checkable instructions."""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from ai_lab import claude_cli
from ai_lab.experiment import check_model, price_trial
from run import EFFORT, HERE, MODEL, OUT, cases, digest, dump, prompt, schedule

KEYS = ("R", "B", "G", "Y")


def score(text: str | None, answers: dict) -> tuple[dict[str, bool], bool]:
    lines = [line.strip() for line in (text or "").strip().splitlines()]
    expected = [f"{key}={answers[key]}" for key in KEYS]
    instruction = {key: lines.count(want) == 1 for key, want in zip(KEYS, expected, strict=True)}
    return instruction, lines == expected


def main() -> None:
    rows = cases()
    by_id = {row["id"]: row for row in rows}
    plan = schedule(rows)
    frozen = json.loads((OUT / "frozen.json").read_text(encoding="utf-8"))
    progress = json.loads((OUT / "progress.json").read_text(encoding="utf-8"))
    for field, filename in (("cases_sha256", "cases.json"),
                            ("preregistration_sha256", "preregistration.md"),
                            ("runner_sha256", "run.py"),
                            ("analyzer_sha256", "analyze.py")):
        assert frozen[field] == digest((HERE / filename).read_bytes())
    assert frozen["schedule"] == plan and frozen["model"] == MODEL and frozen["effort"] == EFFORT
    records = progress["records"]
    assert progress["planned"] == 32 and progress["completed"] == len(records) <= 32
    public = []
    session_hashes = []
    total_tool_calls = 0
    for index, record in enumerate(records, 1):
        item = plan[index - 1]
        assert all(record[key] == value for key, value in item.items()) and record["trial"] == index
        trial = OUT / f"trial_{index:02d}"
        expected_prompt = prompt(by_id[item["case_id"]], item["condition"])
        assert (trial / "prompt.txt").read_text(encoding="utf-8") == expected_prompt
        assert record["prompt_sha256"] == digest(expected_prompt)
        raw = (trial / "stream.jsonl").read_text(encoding="utf-8")
        stderr = (trial / "stderr.txt").read_text(encoding="utf-8")
        assert record["raw_sha256"] == digest(raw)
        cli = claude_cli.summarize_run(claude_cli.CliRun(
            returncode=record["returncode"], stdout=raw, stderr=stderr,
            wall_seconds=record["wall_seconds"], timed_out=record["status"] == "timeout",
        ))
        assert cli["status"] == record["status"]
        assert cli["result_text"] == record["result_text"]
        assert check_model(cli, MODEL) == record["model_check"]
        tokens, cost = price_trial(cli, MODEL)
        assert tokens == record["tokens"] and cost == record["cost"]
        events = [json.loads(line) for line in raw.splitlines() if line.strip()]
        for event in events:
            message = event.get("message", {})
            blocks = message.get("content", []) if isinstance(message, dict) else []
            total_tool_calls += sum(block.get("type") == "tool_use" for block in blocks if isinstance(block, dict))
        session_hash = digest(cli["session_id"]) if cli["session_id"] else None
        assert session_hash == record["session_sha256"]
        if session_hash:
            session_hashes.append(session_hash)
        valid = record["status"] == "ok" and record["model_check"]["status"] == "match"
        scores, exact_format = score(record["result_text"], by_id[item["case_id"]]["answers"]) if valid else ({}, False)
        public.append({
            "trial": index, **item, "prompt_sha256": record["prompt_sha256"],
            "status": record["status"], "model_check": record["model_check"]["status"],
            "valid": valid, "response_text": record["result_text"],
            "scores": scores, "exact_format": exact_format,
            "session_sha256_prefix": session_hash[:16] if session_hash else None,
            "raw_sha256": record["raw_sha256"], "wall_seconds": record["wall_seconds"],
            "tokens": tokens, "thinking_tokens": record["thinking_tokens"],
            "api_equivalent_usd": cost["api_equivalent_usd"],
            "cli_reported_usd": record["cli_reported_usd"],
        })
    assert len(session_hashes) == len(set(session_hashes))
    assert total_tool_calls == 0
    conditions = {}
    for condition in ("A", "B"):
        chosen = [r for r in public if r["condition"] == condition and r["valid"]]
        conditions[condition] = {
            "valid_trials": len(chosen),
            "instruction_correct": {key: sum(r["scores"][key] for r in chosen) for key in KEYS},
            "other_correct": sum(sum(r["scores"][key] for key in KEYS[1:]) for r in chosen),
            "other_possible": 3 * len(chosen),
            "all_four_correct": sum(all(r["scores"].values()) for r in chosen),
            "exact_format": sum(r["exact_format"] for r in chosen),
            "wall_seconds_total": round(sum(r["wall_seconds"] for r in chosen), 3),
            "wall_seconds_mean": round(mean(r["wall_seconds"] for r in chosen), 3) if chosen else None,
            "tokens": {key: sum((r["tokens"] or {}).get(key) or 0 for r in chosen)
                       for key in ("input", "output", "cache_read", "cache_write")},
            "thinking_tokens": sum(r["thinking_tokens"] or 0 for r in chosen),
            "api_equivalent_usd": round(sum(r["api_equivalent_usd"] or 0 for r in chosen), 6),
            "cli_reported_usd": round(sum(r["cli_reported_usd"] or 0 for r in chosen), 6),
        }
    pairs = defaultdict(dict)
    for r in public:
        if r["valid"]:
            pairs[(r["case_id"], r["repetition"])][r["condition"]] = r
    complete_pairs = [p for p in pairs.values() if set(p) == {"A", "B"}]
    pair_counts = Counter()
    pair_differences = []
    for p in complete_pairs:
        a = sum(p["A"]["scores"][k] for k in KEYS[1:])
        b = sum(p["B"]["scores"][k] for k in KEYS[1:])
        pair_counts["A_higher" if a > b else "B_higher" if b > a else "equal"] += 1
        pair_differences.append(b - a)
    summary = {
        "experiment": 15, "backlog_id": "B36", "date_jst": "2026-11-26",
        "model": MODEL, "effort": EFFORT,
        "planned_trials": len(plan), "completed_trials": len(records),
        "valid_trials": sum(r["valid"] for r in public),
        "invalid_trials": sum(not r["valid"] for r in public),
        "unrun_trials": len(plan) - len(records), "stop_reason": progress["stop_reason"],
        "conditions": conditions, "complete_pairs": len(complete_pairs),
        "paired_outcomes": {key: pair_counts[key] for key in ("A_higher", "B_higher", "equal")},
        "paired_B_minus_A_total": sum(pair_differences),
        "paired_B_minus_A_by_pair": pair_differences,
        "case_results": {row["id"]: {condition: [r["scores"] for r in public
                                             if r["case_id"] == row["id"] and r["condition"] == condition and r["valid"]]
                                      for condition in ("A", "B")} for row in rows},
    }
    preflight = json.loads((OUT / "preflight.json").read_text(encoding="utf-8"))
    assert preflight["auth_method"] == "claude.ai"
    audit = {
        **{key: frozen[key] for key in ("cases_sha256", "preregistration_sha256", "runner_sha256", "analyzer_sha256")},
        "cli_image": preflight["cli_image"], "auth_method": preflight["auth_method"],
        "trial_count": len(records), "unique_sessions": len(session_hashes),
        "model_matches": sum(r["model_check"] == "match" for r in public),
        "tool_calls": total_tool_calls, "raw_records_checked": len(records),
        "prompt_hashes_match": True, "raw_hashes_match": True,
        "answer_keys_not_mounted_in_cli": True, "stop_reason": progress["stop_reason"],
    }
    dump(HERE / "public-runs.json", public)
    dump(HERE / "summary.json", summary)
    dump(HERE / "audit.json", audit)
    dump(HERE / "preflight-public.json", {
        "cli_image": preflight["cli_image"], "cli_version": preflight["cli_version"],
        "auth_method": preflight["auth_method"], "model": MODEL, "effort": EFFORT,
    })
    print(json.dumps({"conditions": conditions, "paired_outcomes": summary["paired_outcomes"],
                      "audit": audit}, ensure_ascii=False))


if __name__ == "__main__":
    main()
