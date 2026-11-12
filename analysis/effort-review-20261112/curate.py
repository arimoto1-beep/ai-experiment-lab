"""Create public #10 records from local, ignored run logs without rerunning models."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
LOCAL = ROOT / "results/effort_review_20261112"
RUNS = (
    "a-medium-b0fee227",
    "b-medium-c004ad44",
    "a-high-3d50edd3",
    "b-high-45cf5def",
    "a-max-f3f4310a",
)
PRIVATE = re.compile(r"[A-Za-z]:[\\/](?:Users|work)[\\/]|sk-ant-|ANTHROPIC_API_KEY|authToken|session_id", re.I)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    conditions = read_json(LOCAL / "conditions.json")
    reviews = HERE / "reviews"
    reviews.mkdir(exist_ok=True)
    public_runs = []
    for run_id in RUNS:
        folder = LOCAL / run_id
        raw_run = (folder / "run.json").read_bytes()
        run = json.loads(raw_run)
        raw_stream = (folder / "stream.jsonl").read_bytes()
        history = read_json(folder / "history.json")
        events = history["events"]
        errors = sum(event["kind"] == "tool_result" and event.get("is_error") is True for event in events)
        review_file = None
        review_sha = None
        if run["status"] == "ok":
            review = run["result_text"]
            if not isinstance(review, str) or PRIVATE.search(review):
                raise ValueError(f"missing review or private-looking content: {run_id}")
            review_file = f"reviews/{run_id}.md"
            encoded = review.encode("utf-8")
            (HERE / review_file).write_bytes(encoded)
            review_sha = sha(encoded)
        item = {
            "run_id": run_id,
            "target": run["label"],
            "requested_effort": run["effort_requested"],
            "effective_effort_api_value": None,
            "status": run["status"],
            "model_id_requested": conditions["model"],
            "model_id_reported_by_model_usage": run["model_check"]["actual_model_ids"],
            "model_id_in_init": run["init_model"],
            "cli_version": run["cli_version"],
            "per_turn_effort_active": run["per_turn_effort_active"],
            "wall_seconds": run["wall_seconds"],
            "cli_seconds": run["cli_seconds"],
            "tokens": run["tokens"],
            "thinking_tokens": run["thinking_tokens"],
            "api_equivalent_usd": run["cost"]["api_equivalent_usd"],
            "code_unchanged": run["code_unchanged"],
            "read_calls": run["workflow"]["reads"],
            "edit_calls": run["workflow"]["edits"],
            "command_calls": run["workflow"]["test_runs"],
            "tool_errors": errors,
            "stderr_empty": (folder / "stderr.txt").stat().st_size == 0,
            "review_file": review_file,
            "review_sha256": review_sha,
            "local_run_json_sha256": sha(raw_run),
            "local_stream_sha256": sha(raw_stream),
        }
        if run_id == "a-max-f3f4310a":
            stream = [json.loads(line) for line in raw_stream.decode("utf-8").splitlines()]
            thinking = [event for event in stream if event.get("type") == "system"
                        and event.get("subtype") == "thinking_tokens"]
            usage_by_request = {}
            for event in stream:
                if event.get("type") == "assistant" and event.get("request_id") and event["message"].get("usage"):
                    usage_by_request[event["request_id"]] = event["message"]["usage"]
            observed_usage = {
                "input": sum(u.get("input_tokens", 0) for u in usage_by_request.values()),
                "cache_write": sum(u.get("cache_creation_input_tokens", 0) for u in usage_by_request.values()),
                "cache_read": sum(u.get("cache_read_input_tokens", 0) for u in usage_by_request.values()),
                "output": sum(u.get("output_tokens", 0) for u in usage_by_request.values()),
            }
            rate_limit = next((event["rate_limit_info"]["status"] for event in stream
                               if event.get("type") == "rate_limit_event"), None)
            item["timeout_observation"] = {
                "stream_events": len(stream),
                "final_result_events": sum(event.get("type") == "result" for event in stream),
                "last_event": f"{stream[-1].get('type')}.{stream[-1].get('subtype')}",
                "last_thinking_estimate_tokens": thinking[-1]["estimated_tokens"],
                "thinking_estimate_is_total_usage": False,
                "usage_snapshot_request_count": len(usage_by_request),
                "usage_snapshot_sum_not_final_accounting": observed_usage,
                "rate_limit_status": rate_limit,
                "total_usage_and_api_cost_known": False,
            }
        public_runs.append(item)
    payload = {
        "experiment": 10,
        "date_jst": "2026-11-12",
        "model_id": conditions["model"],
        "cli_version": conditions["cli_version"],
        "prompt_sha256": conditions["prompt_sha256"],
        "statement_sha256": conditions["statement_sha256"],
        "worker_sha256": conditions["worker_sha256"],
        "cli_image": conditions["cli_image"],
        "worker_image": conditions["worker_image"],
        "timeout_seconds": conditions["timeout_seconds"],
        "max_turns": conditions["max_turns"],
        "max_budget_usd": conditions["max_budget_usd"],
        "planned_order": conditions["order"],
        "completed_reviews": 4,
        "timed_out": 1,
        "not_started": ["B-max"],
        "runs": public_runs,
    }
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if PRIVATE.search(encoded.decode("utf-8")):
        raise ValueError("private-looking content in public summary")
    (HERE / "public-runs.json").write_bytes(encoded)
    print(json.dumps({"reviews": len(list(reviews.glob("*.md"))),
                      "public_summary_sha256": sha(encoded),
                      "max_final_result_events": public_runs[-1]["timeout_observation"]["final_result_events"]}))


if __name__ == "__main__":
    main()
