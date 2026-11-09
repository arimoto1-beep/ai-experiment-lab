"""Validate the frozen #9 inputs against all saved model runs and export a public audit."""

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from ai_lab.review_perspectives import parse_perspectives, task_config


RUNS = HERE.parents[1] / "results" / "review_perspectives_20261109"
REVIEW_TOOLS = {"mcp__lab__list_files", "mcp__lab__read_file"}


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(value):
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def source_files(root):
    return {p.relative_to(root).as_posix(): digest(p.read_bytes())
            for p in sorted(root.rglob("*")) if p.is_file()}


def result_event(path):
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    matches = [event for event in events if event.get("type") == "result"]
    assert len(matches) == 1, f"missing or repeated CLI result: {path}"
    return matches[0]


public = {"schema": 1, "tasks": {}, "total_reviews": 0, "total_designs": 0}
all_sessions = []
for task in ("parcel", "react"):
    directory = RUNS / task
    frozen = read_json(directory / "frozen-inputs.json")
    work, statement, worker, _, _ = task_config(task)
    assert frozen["task"] == task
    assert frozen["files"] == source_files(work)
    assert frozen["statement_sha256"] == digest(statement)
    assert frozen["worker_sha256"] == digest(worker.read_bytes())
    assert frozen["model"] == "claude-haiku-5-5" and frozen["effort"] == "medium"
    order = [(phase, index) for phase, index in frozen["order"]]
    assert order == [("A", 1), ("B", 1), ("C_design", 0), ("C", 1),
                     ("A", 2), ("B", 2), ("C", 2), ("A", 3), ("B", 3), ("C", 3)]
    progress = read_json(directory / "progress.json")
    assert [(row["phase"], row["index"]) for row in progress] == order
    records = { (read_json(p)["phase"], read_json(p)["index"]): (p, read_json(p))
                for p in directory.glob("*/run.json") }
    assert len(records) == len(order) == 10
    designer_path, designer = records[("C_design", 0)]
    generated = read_json(directory / "generated-perspectives.json")
    assert generated == parse_perspectives(designer["result_text"])
    assert generated == read_json(HERE / f"perspectives-{task}.json")
    tree = "\n".join(frozen["files"])
    task_runs = []
    prompt_hashes = {"A": [], "B": [], "C": []}
    sessions = []
    for phase, index in order:
        path, record = records[(phase, index)]
        if phase == "C_design":
            expected_prompt = (f"{frozen['design_instruction']}\n\nTASK SPECIFICATION:\n{statement}"
                               f"\n\nFILE NAMES:\n{tree}")
            public["total_designs"] += 1
        else:
            role = (frozen["roles"]["A"] if phase == "A" else
                    frozen["roles"]["B"][index - 1] if phase == "B" else
                    generated[index - 1]["prompt"])
            expected_prompt = (f"TASK SPECIFICATION:\n{statement}\n\nCOMMON REVIEW INSTRUCTIONS:"
                               f"\n{frozen['common']}\n\nPERSPECTIVE:\n{role}")
            prompt_hashes[phase].append(record["prompt_sha256"])
            public["total_reviews"] += 1
        prompt = path.with_name("prompt.txt").read_text(encoding="utf-8")
        assert prompt == expected_prompt, f"prompt differs from frozen condition: {path}"
        assert record["prompt_sha256"] == digest(prompt)
        assert record["status"] == "ok" and record["model_check"]["status"] == "match"
        assert record["code_unchanged"]
        result = result_event(path.with_name("stream.jsonl"))
        session = result["session_id"]
        assert session and session not in all_sessions
        all_sessions.append(session)
        sessions.append(session)
        history = read_json(path.with_name("history.json"))["events"]
        calls = [event for event in history if event["kind"] == "tool_use"]
        assert {event["tool"] for event in calls} <= REVIEW_TOOLS
        if phase == "C_design":
            assert not calls
        by_id = {event["id"]: event for event in calls}
        errors = [event for event in history if event["kind"] == "tool_result" and event["is_error"]]
        denied_paths = [by_id[event["id"]]["input"].get("path") for event in errors]
        task_runs.append({
            "run_id": record["run_id"], "phase": phase, "index": index,
            "prompt_sha256": record["prompt_sha256"],
            "session_sha256_prefix": digest(session)[:16],
            "status": record["status"], "model_check": record["model_check"]["status"],
            "code_unchanged": record["code_unchanged"],
            "tool_calls": len(calls), "tools_used": sorted({event["tool"] for event in calls}),
            "read_errors": len(errors), "denied_paths": denied_paths,
            "cli_seconds": record["cli_seconds"], "tokens": record["tokens"],
            "thinking_tokens": record["thinking_tokens"],
            "api_equivalent_usd": record["cost"]["api_equivalent_usd"],
        })
    assert len(set(prompt_hashes["A"])) == 1
    assert len(set(prompt_hashes["B"])) == 3
    assert len(set(prompt_hashes["C"])) == 3
    assert len(set(sessions)) == 10
    public["tasks"][task] = {
        "target_file_count": len(frozen["files"]),
        "statement_sha256": frozen["statement_sha256"],
        "worker_sha256": frozen["worker_sha256"],
        "phase_order": order,
        "prompt_variants": {method: len(set(hashes)) for method, hashes in prompt_hashes.items()},
        "unique_sessions": len(set(sessions)),
        "read_errors": sum(run["read_errors"] for run in task_runs),
        "runs": task_runs,
    }

assert public["total_reviews"] == 18 and public["total_designs"] == 2
assert len(set(all_sessions)) == 20
public["unique_sessions"] = len(all_sessions)
public["preregistration_sha256"] = digest((HERE / "preregistration.md").read_bytes())
(HERE / "audit.json").write_text(json.dumps(public, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"reviews": public["total_reviews"], "designs": public["total_designs"],
                  "sessions": public["unique_sessions"],
                  "read_errors": {task: value["read_errors"] for task, value in public["tasks"].items()}}))
