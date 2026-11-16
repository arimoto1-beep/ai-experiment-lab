"""Audit the saved #11 reviews without invoking a model."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ai_lab import review_perspectives as rp


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
RUNS = ROOT / "results/repeated_review_20261116"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    frozen = json.loads((OUT / "frozen-inputs.json").read_text(encoding="utf-8"))
    records = json.loads((RUNS / "progress.json").read_text(encoding="utf-8"))
    if len(records) != 15:
        raise RuntimeError("review count differs from preregistration")
    source_checks = {}
    for label, (run, trial) in frozen["sources"].items():
        source = ROOT / "results/react_lead_form_harbor" / run / "jobs" / run / trial / "artifacts/app"
        source_checks[label] = rp.files(source) == frozen["files"][label]
    rows = []
    for record in records:
        directory = RUNS / record["run_id"]
        run = json.loads((directory / "run.json").read_text(encoding="utf-8"))
        invocation = json.loads((directory / "invocation.json").read_text(encoding="utf-8"))
        history = json.loads((directory / "history.json").read_text(encoding="utf-8"))
        stream = (directory / "stream.jsonl").read_bytes()
        events = [json.loads(line) for line in stream.decode("utf-8").splitlines() if line.startswith("{")]
        init = next((event for event in events if event.get("type") == "system" and event.get("subtype") == "init"), {})
        result = next((event for event in reversed(events) if event.get("type") == "result"), {})
        error_count = sum(event.get("kind") == "tool_result" and event.get("is_error") is True for event in history["events"])
        actual_tools = sorted({event.get("tool") for event in history["events"] if event.get("kind") == "tool_use"})
        model, effort = frozen["settings"][run["phase"]]
        prompt = (directory / "prompt.txt").read_text(encoding="utf-8")
        rp.MODEL, rp.EFFORT = model, effort
        expected_args = rp.cli_args(prompt, True) + ["--max-budget-usd", "2.00"]
        public_record = {key: value for key, value in run.items() if key not in ("result_text", "stderr")}
        rows.append({
            "run_id": run["run_id"], "label": run["label"], "phase": run["phase"],
            "session_id": result.get("session_id"), "status": run["status"],
            "model": run["model_check"]["actual_model_ids"],
            "effort_requested": run["effort_requested"],
            "effort_active": init.get("per_turn_effort_active"),
            "cli_version": init.get("claude_code_version"),
            "prompt_match": sha(prompt.encode()) == frozen["prompt_sha256"],
            "invocation_match": (invocation == {"arguments": expected_args[1:], "model": model, "effort": effort}),
            "model_usage_match": (sorted(result.get("modelUsage", {})) == [model]),
            "tools_used": actual_tools,
            "tools_match": actual_tools == ["mcp__lab__list_files", "mcp__lab__read_file"],
            "progress_record_match": record == public_record,
            "code_unchanged": run["code_unchanged"],
            "read_calls": history["workflow"].get("reads"),
            "edits": history["workflow"].get("edits"),
            "tool_errors": error_count, "returncode": run["returncode"],
            "stderr_empty": not run["stderr"], "stream_sha256": sha(stream),
        })
    ids = [row["session_id"] for row in rows]
    audit = {
        "preregistration_sha256_match": sha((OUT / "preregistration.md").read_bytes()) == frozen["preregistration_sha256"],
        "source_hashes_match": source_checks,
        "session_ids_unique": all(ids) and len(set(ids)) == len(ids),
        "frozen_order_match": [(r["label"],r["phase"]) for r in rows] == [tuple(x) for x in frozen["order"]],
        "runs": rows,
    }
    if not (audit["preregistration_sha256_match"] and all(source_checks.values()) and
            audit["session_ids_unique"] and audit["frozen_order_match"] and
            all(r["status"] == "ok" and r["prompt_match"] and r["invocation_match"] and
                r["model_usage_match"] and r["tools_match"] and r["progress_record_match"] and r["code_unchanged"] and
                r["effort_active"] and r["edits"] == 0 and r["tool_errors"] == 0 and
                r["returncode"] == 0 and r["stderr_empty"] for r in rows)):
        raise RuntimeError("audit failed")
    (OUT / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"reviews": len(rows), "session_ids_unique": audit["session_ids_unique"],
                      "source_hashes_match": source_checks, "tool_errors": 0, "edits": 0}))


if __name__ == "__main__":
    main()
