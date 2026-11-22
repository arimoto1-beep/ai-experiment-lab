"""Publish a small, credential-free digest of the already completed second trial."""

from __future__ import annotations

import collections
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
RAW = ROOT / "results/test_driven_review_20261122_trial2"
WORK = OUT / "test-work-trial2"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    record = json.loads((RAW / "run.json").read_text(encoding="utf-8"))
    events = json.loads((RAW / "history.json").read_text(encoding="utf-8"))["events"]
    operations = [json.loads(line) for line in (RAW / "operations.jsonl").read_text(encoding="utf-8").splitlines()]
    manifest = json.loads((OUT / "frozen-inputs.json").read_text(encoding="utf-8"))
    if record.get("trial_number") != 2 or not record.get("source_unchanged"):
        raise RuntimeError("second trial record or source integrity failed")
    if record["model_check"]["status"] != "match" or record["per_turn_effort_active"] is not True:
        raise RuntimeError("model or effort verification failed")
    for name, key in [("preregistration.md", "preregistration_sha256"),
                      ("prompt.txt", "prompt_sha256"), ("test_worker.mjs", "worker_sha256")]:
        if digest(OUT / name) != manifest[key]:
            raise RuntimeError(f"frozen input changed: {name}")
    rows = []
    for i, operation in enumerate(x for x in operations if x["tool"] == "run_tests"):
        output = operation["detail"]
        def number(key: str) -> int:
            match = re.search(rf"(?m)^# {key} (\d+)$", output)
            if not match:
                raise RuntimeError(f"missing TAP {key}")
            return int(match.group(1))
        code = re.search(r"^exit_code=(\d+)", output)
        if not code:
            raise RuntimeError("missing test exit code")
        rows.append({"run_index": i + 1, "completed_at_utc": operation["at"],
                     "exit_code": int(code.group(1)), "tests": number("tests"),
                     "passed": number("pass"), "failed": number("fail"),
                     "skipped": number("skipped"), "cancelled": number("cancelled"),
                     "failed_test_names": re.findall(r"(?m)^    not ok \d+ - (.+)$", output),
                     "tap_output_sha256": hashlib.sha256(output.encode()).hexdigest()})
    test_files = {p.name: digest(p) for p in sorted((WORK / "tests").glob("*.test.ts"))}
    counts = collections.Counter((x["tool"], x["status"]) for x in operations)
    tool_calls = collections.Counter(x["tool"] for x in events if x["kind"] == "tool_use")
    response = record["result_text"] or ""
    (OUT / "model-response.md").write_text(response + ("" if response.endswith("\n") else "\n"), encoding="utf-8")
    save(OUT / "test-runs.json", {"runs": rows, "total_executions": sum(x["tests"] for x in rows),
                                  "total_passed": sum(x["passed"] for x in rows),
                                  "total_failed": sum(x["failed"] for x in rows),
                                  "final_unique_tests": rows[-1]["tests"]})
    save(OUT / "trial2-public-run.json", {
        "trial_number": 2, "status": record["status"], "inference_started": True,
        "model_requested": record["model_requested"], "model_actual": record["model_check"]["actual_model_ids"],
        "model_check": record["model_check"]["status"],
        "effort_requested": record["effort_requested"], "per_turn_effort_active": record["per_turn_effort_active"],
        "cli_version": record["cli_version"], "auth_method_at_start": record["auth_method_at_start"],
        "wall_seconds": record["wall_seconds"], "cli_seconds": record["cli_seconds"],
        "returncode": record["returncode"], "timed_out": record["timed_out"],
        "tokens": record["tokens"], "thinking_tokens": record["thinking_tokens"],
        "api_equivalent_usd_basic_tier": record["cost"]["api_equivalent_usd"],
        "cache_write_tokens_by_ttl": record["cost"]["cache_write_tokens_by_ttl"],
        "source_unchanged": record["source_unchanged"],
        "prompt_sha256": manifest["prompt_sha256"], "worker_sha256": manifest["worker_sha256"],
        "test_file_sha256": test_files,
        "tool_calls": dict(tool_calls),
        "read_paths": [x["input"].get("path") for x in events
                       if x["kind"] == "tool_use" and x["tool"] == "mcp__lab__read_file"],
        "tool_operation_statuses": {f"{tool}:{status}": count for (tool, status), count in counts.items()},
        "test_runs": len(rows), "final_test_cases": rows[-1]["tests"],
        "final_passed": rows[-1]["passed"], "final_failed": rows[-1]["failed"],
        "final_unrunnable": rows[-1]["cancelled"],
        "model_response_sha256": hashlib.sha256(response.encode()).hexdigest(),
        "raw_stream_sha256": digest(RAW / "stream.jsonl"),
        "raw_stream_git_ignored": True,
    })
    print(json.dumps({"test_runs": len(rows), "final": rows[-1], "tools": dict(tool_calls)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
