"""Six preregistered, isolated reviews using the existing #9 review components."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
import uuid
from pathlib import Path

from ai_lab import claude_cli, review_perspectives as rp
from ai_lab.agentic_dev import AgenticConfig, _check_auth, _events
from ai_lab.experiment import check_model, price_trial


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
RUNS = ROOT / "results/effort_review_20261112"
DOCKER = os.environ["RLFM_DOCKER"]
ORDER = (("A", "medium"), ("B", "medium"), ("A", "high"),
         ("B", "high"), ("A", "max"), ("B", "max"))


def dump(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    restoration = json.loads((OUT / "restoration.json").read_text(encoding="utf-8"))
    if RUNS.exists():
        raise RuntimeError("run directory exists; automatic reruns are forbidden")
    for label in ("A", "B"):
        if rp.files(OUT / "restored" / label) != restoration[label]["files"]:
            raise RuntimeError(f"{label} restoration changed")
    for image in (rp.CLI_IMAGE, rp.REACT_WORKER_IMAGE):
        if rp.checked_run([DOCKER, "image", "inspect", image, "--format", "{{.Id}}"]).stdout.strip() != image:
            raise RuntimeError("pinned image missing")
    config = AgenticConfig(task="parcel_manifest", model_id=rp.MODEL, effort="medium", runs=1,
                           timeout=600, results_dir=OUT, docker_bin=DOCKER, image=rp.CLI_IMAGE,
                           worker_image=rp.REACT_WORKER_IMAGE, auth_volume=rp.AUTH_VOLUME)
    auth = _check_auth(config)
    statement = (ROOT / "analysis/terminal-bench-v4.0.0/tasks/react-lead-form/instruction.md").read_text(encoding="utf-8")
    prompt = f"TASK SPECIFICATION:\n{statement}\n\nCOMMON REVIEW INSTRUCTIONS:\n{rp.REVIEW_COMMON}\n\nPERSPECTIVE:\n{rp.A_ROLE}"
    RUNS.mkdir(parents=True)
    dump(RUNS / "conditions.json", {
        "order": ORDER, "model": rp.MODEL, "cli_image": rp.CLI_IMAGE,
        "worker_image": rp.REACT_WORKER_IMAGE, "cli_version": "2.1.302 (Claude Code)",
        "auth_method": auth.get("auth_method"), "statement_sha256": hashlib.sha256(statement.encode()).hexdigest(),
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "worker_sha256": rp.sha(ROOT / "benchmarks/react_lead_form_adapter/mcp_worker.mjs"),
        "timeout_seconds": 600, "max_turns": 35, "max_budget_usd": 0.20,
        "restoration": {key: {"run_id": row["run_id"], "file_count": row["file_count"]}
                        for key, row in restoration.items()},
    })
    records = []
    for label, effort in ORDER:
        work = OUT / "restored" / label
        run_id = f"{label.lower()}-{effort}-{uuid.uuid4().hex[:8]}"
        destination = RUNS / run_id
        destination.mkdir()
        (destination / "prompt.txt").write_text(prompt, encoding="utf-8")
        ipc = "ai-lab-review-" + uuid.uuid4().hex[:12]
        worker_name = "ai-lab-review-" + uuid.uuid4().hex[:12]
        started = time.perf_counter()
        process = None
        try:
            rp.checked_run([DOCKER, "volume", "create", ipc])
            rp.start_worker(DOCKER, "react", work, ROOT / "benchmarks/react_lead_form_adapter/mcp_worker.mjs",
                            rp.REACT_WORKER_IMAGE, "node", ipc, worker_name)
            rp.EFFORT = effort
            args = rp.cli_args(prompt, True) + ["--max-budget-usd", "0.20"]
            dump(destination / "invocation.json", {"args": args[1:], "effort": effort, "model": rp.MODEL})
            process = claude_cli.invoke(rp.cli_command(DOCKER, ipc), args,
                                        cwd=None, env=claude_cli.child_environment(os.environ), timeout=600)
        except Exception as error:
            dump(destination / "error.json", {"error": type(error).__name__, "message": str(error)})
            raise
        finally:
            subprocess.run([DOCKER, "rm", "-f", worker_name], capture_output=True, check=False)
            subprocess.run([DOCKER, "volume", "rm", "-f", ipc], capture_output=True, check=False)
        (destination / "stream.jsonl").write_text(process.stdout, encoding="utf-8")
        (destination / "stderr.txt").write_text(process.stderr, encoding="utf-8")
        events, workflow = _events(process.stdout)
        dump(destination / "history.json", {"events": events, "workflow": workflow})
        cli = claude_cli.summarize_run(process)
        tokens, cost = price_trial(cli, rp.MODEL)
        init = next((json.loads(line) for line in process.stdout.splitlines()
                     if line.startswith('{"type":"system","subtype":"init"')), {})
        record = {
            "label": label, "effort_requested": effort, "run_id": run_id,
            "status": cli["status"], "wall_seconds": round(time.perf_counter() - started, 3),
            "cli_seconds": round(process.wall_seconds, 3),
            "model_check": check_model(cli, rp.MODEL), "cli_version": init.get("claude_code_version"),
            "init_model": init.get("model"), "per_turn_effort_active": init.get("per_turn_effort_active"),
            "code_unchanged": rp.files(work) == restoration[label]["files"],
            "tokens": tokens, "thinking_tokens": cli["thinking_tokens"], "cost": cost,
            "result_text": cli["result_text"], "workflow": workflow,
            "stderr": process.stderr[-2000:], "returncode": process.returncode,
        }
        dump(destination / "run.json", record)
        records.append({key: value for key, value in record.items() if key not in ("result_text", "stderr")})
        dump(RUNS / "progress.json", records)
        print(json.dumps({"run_id": run_id, "status": record["status"], "seconds": record["wall_seconds"],
                          "cost": cost.get("api_equivalent_usd"), "model": record["model_check"],
                          "thinking_tokens": record["thinking_tokens"]}), flush=True)
        if (record["status"] != "ok" or not record["code_unchanged"] or
                record["model_check"]["status"] != "match" or
                cost.get("api_equivalent_usd") is None or cost["api_equivalent_usd"] > 0.20 or
                record["cli_version"] != "2.1.302"):
            raise RuntimeError("abnormal trial; subsequent trials stopped")


if __name__ == "__main__":
    main()
