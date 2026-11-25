"""Audit raw B27 trials, apply the frozen integer-only rule, and publish summaries."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from ai_lab import claude_cli
from ai_lab.experiment import check_model, price_trial

from run import HERE, MODEL, OUT, cases, digest, dump, prompt, schedule


INTEGER = re.compile(r"[+-]?[0-9]+\Z")


def score(text: str | None, answer: int) -> tuple[bool, bool, int | None]:
    value = (text or "").strip(" \t\r\n。．.")
    if not INTEGER.fullmatch(value):
        return False, False, None
    number = int(value)
    return number == answer, True, number


def main() -> None:
    rows = cases()
    by_id = {row["id"]: row for row in rows}
    plan = schedule(rows)
    frozen = json.loads((OUT / "frozen.json").read_text(encoding="utf-8"))
    progress = json.loads((OUT / "progress.json").read_text(encoding="utf-8"))
    assert frozen["cases_sha256"] == digest((HERE / "cases.json").read_bytes())
    assert frozen["preregistration_sha256"] == digest((HERE / "preregistration.md").read_bytes())
    assert frozen["runner_sha256"] == digest((HERE / "run.py").read_bytes())
    assert frozen["schedule"] == plan
    assert frozen["model"] == MODEL and frozen["effort"] == "medium"
    records = progress["records"]
    assert progress["planned"] == 40 and progress["completed"] == len(records)
    assert progress["stop_reason"] is None and len(records) == 40
    public = []
    sessions = []
    total_tool_calls = 0
    for index, (item, record) in enumerate(zip(plan, records, strict=True), 1):
        assert all(record[key] == value for key, value in item.items())
        assert record["trial"] == index
        trial = OUT / f"trial_{index:02d}"
        expected_prompt = prompt(by_id[item["case_id"]], item["condition"])
        assert (trial / "prompt.txt").read_text(encoding="utf-8") == expected_prompt
        assert record["prompt_sha256"] == digest(expected_prompt)
        raw = (trial / "stream.jsonl").read_text(encoding="utf-8")
        stderr = (trial / "stderr.txt").read_text(encoding="utf-8")
        assert record["raw_sha256"] == digest(raw)
        events = [json.loads(line) for line in raw.splitlines() if line.strip()]
        results = [event for event in events if event.get("type") == "result"]
        assert len(results) == 1
        parsed = claude_cli.parse_output(raw)
        assert parsed is not None and parsed.get("result") == record["result_text"]
        for event in events:
            message = event.get("message", {})
            blocks = message.get("content", []) if isinstance(message, dict) else []
            total_tool_calls += sum(block.get("type") == "tool_use" for block in blocks if isinstance(block, dict))
        cli = claude_cli.summarize_run(claude_cli.CliRun(
            returncode=record["returncode"], stdout=raw, stderr=stderr,
            wall_seconds=record["wall_seconds"], timed_out=False,
        ))
        assert cli["status"] == record["status"] == "ok"
        assert check_model(cli, MODEL) == record["model_check"]
        assert record["model_check"]["status"] == "match"
        tokens, cost = price_trial(cli, MODEL)
        assert record["tokens"] == tokens and record["cost"] == cost
        assert record["thinking_tokens"] == cli["thinking_tokens"]
        session_hash = digest(cli["session_id"])
        assert record["session_sha256"] == session_hash
        sessions.append(session_hash)
        correct, valid_format, parsed_integer = score(record["result_text"], by_id[item["case_id"]]["answer"])
        public.append({
            "trial": index, **item, "difficulty": by_id[item["case_id"]]["difficulty"],
            "prompt_sha256": record["prompt_sha256"],
            "session_sha256_prefix": session_hash[:16], "status": record["status"],
            "model_check": record["model_check"]["status"],
            "response_text": record["result_text"],
            "format_valid": valid_format, "parsed_integer": parsed_integer,
            "correct": correct, "wall_seconds": record["wall_seconds"],
            "tokens": tokens, "thinking_tokens": cli["thinking_tokens"],
            "api_equivalent_usd": cost["api_equivalent_usd"],
            "cli_reported_usd": record["cli_reported_usd"],
            "raw_sha256": record["raw_sha256"],
        })
    assert len(set(sessions)) == 40
    assert total_tool_calls == 0
    assert all(row["api_equivalent_usd"] is not None for row in public)

    conditions = {}
    for condition in ("A", "B"):
        chosen = [row for row in public if row["condition"] == condition]
        conditions[condition] = {
            "valid_trials": len(chosen),
            "correct": sum(row["correct"] for row in chosen),
            "format_invalid": sum(not row["format_valid"] for row in chosen),
            "wall_seconds_total": round(sum(row["wall_seconds"] for row in chosen), 3),
            "wall_seconds_mean": round(mean(row["wall_seconds"] for row in chosen), 3),
            "wall_seconds_median": round(median(row["wall_seconds"] for row in chosen), 3),
            "tokens": {key: sum(row["tokens"][key] for row in chosen)
                       for key in ("input", "output", "cache_read", "cache_write")},
            "thinking_tokens": sum(row["thinking_tokens"] or 0 for row in chosen),
            "api_equivalent_usd": round(sum(row["api_equivalent_usd"] for row in chosen), 6),
            "cli_reported_usd": round(sum(row["cli_reported_usd"] or 0 for row in chosen), 6),
            "difficulty": {level: {"correct": sum(row["correct"] for row in chosen if row["difficulty"] == level),
                                   "trials": sum(row["difficulty"] == level for row in chosen)}
                           for level in ("easy", "medium", "reasoning")},
        }
    pairs = defaultdict(dict)
    for row in public:
        pairs[(row["case_id"], row["repetition"])][row["condition"]] = row
    assert len(pairs) == 20 and all(set(pair) == {"A", "B"} for pair in pairs.values())
    pair_counts = Counter(
        "both_correct" if pair["A"]["correct"] and pair["B"]["correct"] else
        "A_only" if pair["A"]["correct"] else
        "B_only" if pair["B"]["correct"] else "both_incorrect"
        for pair in pairs.values()
    )
    summary = {
        "experiment": 14, "backlog_id": "B27", "date_jst": "2026-11-25",
        "model": MODEL, "effort": "medium",
        "pricing_source": "https://platform.claude.com/docs/en/about-claude/pricing",
        "pricing_verified_on": "2026-11-25",
        "planned_trials": 40, "completed_trials": 40, "valid_trials": 40,
        "conditions": conditions,
        "paired_outcomes": {key: pair_counts[key] for key in ("both_correct", "A_only", "B_only", "both_incorrect")},
        "case_results": {row["id"]: {condition: [r["correct"] for r in public
                                             if r["case_id"] == row["id"] and r["condition"] == condition]
                                      for condition in ("A", "B")} for row in rows},
    }
    preflight = json.loads((OUT / "preflight.json").read_text(encoding="utf-8"))
    assert preflight["auth_method"] == "claude.ai"
    audit = {
        "cases_sha256": frozen["cases_sha256"],
        "preregistration_sha256": frozen["preregistration_sha256"],
        "runner_sha256": frozen["runner_sha256"],
        "cli_image": preflight["cli_image"],
        "auth_method": "claude.ai", "trial_count": len(public),
        "unique_sessions": len(set(sessions)), "model_matches": 40,
        "tool_calls": total_tool_calls,
        "raw_records_checked": 40,
        "prompt_hashes_match": True, "raw_hashes_match": True,
        "answer_keys_not_mounted_in_cli": True,
        "stop_reason": progress["stop_reason"],
    }
    dump(HERE / "public-runs.json", public)
    dump(HERE / "summary.json", summary)
    dump(HERE / "audit.json", audit)
    dump(HERE / "preflight-public.json", {
        "cli_image": preflight["cli_image"],
        "cli_version": preflight["cli_version"],
        "auth_method": preflight["auth_method"],
        "model": MODEL, "effort": "medium",
    })
    print(json.dumps({"A": conditions["A"], "B": conditions["B"],
                      "paired_outcomes": summary["paired_outcomes"],
                      "audit": audit}, ensure_ascii=False))


if __name__ == "__main__":
    main()
