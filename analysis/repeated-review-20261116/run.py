"""AI実験室 #11: fifteen isolated, read-only reviews."""

from __future__ import annotations

import argparse
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
RUNS = ROOT / "results/repeated_review_20261116"
SOURCES = {
    "X": ("rlfm-55c4dc725287", "react-lead-form__7S2gRVa"),
    "Y": ("rlfm-8fc5a785bdcd", "react-lead-form__mE4ZMAE"),
    "Z": ("rlfm-0df740e1d9e8", "react-lead-form__YRqsvPJ"),
}
ORDER = tuple((label, phase) for phase in ("A1", "B", "C", "A2", "A3") for label in "XYZ")
SETTINGS = {
    "A1": ("claude-haiku-5-5", "medium"),
    "A2": ("claude-haiku-5-5", "medium"),
    "A3": ("claude-haiku-5-5", "medium"),
    "B": ("claude-haiku-5-5", "high"),
    "C": ("claude-opus-5-5", "high"),
}


def dump(path: Path, obj: object) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def source(label: str) -> Path:
    run, trial = SOURCES[label]
    return ROOT / "results/react_lead_form_harbor" / run / "jobs" / run / trial / "artifacts/app"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args()
    docker = os.environ["RLFM_DOCKER"]
    task = ROOT / "analysis/terminal-bench-v4.0.0"
    commit = subprocess.check_output(["git", "-C", str(task), "rev-parse", "HEAD"], text=True).strip()
    if commit != "452bf305c6daa62fc59061d22133a7cbc7c1572e":
        raise RuntimeError("official task commit changed")
    statement = (task / "tasks/react-lead-form/instruction.md").read_text(encoding="utf-8")
    prompt = f"TASK SPECIFICATION:\n{statement}\n\nCOMMON REVIEW INSTRUCTIONS:\n{rp.REVIEW_COMMON}\n\nPERSPECTIVE:\n{rp.A_ROLE}"
    prereg = OUT / "preregistration.md"
    frozen = {label: rp.files(source(label)) for label in SOURCES}
    if any(not files for files in frozen.values()):
        raise RuntimeError("missing source artifact")
    for image in (rp.CLI_IMAGE, rp.REACT_WORKER_IMAGE):
        actual = rp.checked_run([docker, "image", "inspect", image, "--format", "{{.Id}}"]).stdout.strip()
        if actual != image:
            raise RuntimeError("pinned image unavailable")
    config = AgenticConfig(task="parcel_manifest", model_id="claude-haiku-5-5", effort="medium",
                           runs=1, timeout=600, results_dir=OUT, docker_bin=docker,
                           image=rp.CLI_IMAGE, worker_image=rp.REACT_WORKER_IMAGE,
                           auth_volume=rp.AUTH_VOLUME)
    auth = _check_auth(config)
    manifest = {
        "sources": SOURCES, "files": frozen, "task_commit": commit,
        "statement_sha256": sha(statement.encode()), "prompt_sha256": sha(prompt.encode()),
        "preregistration_sha256": sha(prereg.read_bytes()),
        "worker_sha256": rp.sha(ROOT / "benchmarks/react_lead_form_adapter/mcp_worker.mjs"),
        "cli_image": rp.CLI_IMAGE, "worker_image": rp.REACT_WORKER_IMAGE,
        "auth_method": auth.get("auth_method"), "order": ORDER, "settings": SETTINGS,
        "timeout_seconds": 600, "max_turns": 35, "max_budget_usd": 2.0,
    }
    manifest_path = OUT / "frozen-inputs.json"
    if manifest_path.exists():
        if json.loads(manifest_path.read_text(encoding="utf-8")) != json.loads(json.dumps(manifest)):
            raise RuntimeError("frozen inputs changed")
    else:
        dump(manifest_path, manifest)
    if args.preflight:
        print(json.dumps({"preflight": "ok", "source_files": {k: len(v) for k, v in frozen.items()},
                          "auth_method": auth.get("auth_method"), "prompt_sha256": manifest["prompt_sha256"]}))
        return
    if RUNS.exists():
        raise RuntimeError("run directory exists; no rerun")
    RUNS.mkdir(parents=True)
    dump(RUNS / "conditions.json", manifest)
    records: list[dict] = []
    for label, phase in ORDER:
        model, effort = SETTINGS[phase]
        run_id = f"{label.lower()}-{phase.lower()}-{uuid.uuid4().hex[:8]}"
        destination = RUNS / run_id
        destination.mkdir()
        (destination / "prompt.txt").write_text(prompt, encoding="utf-8")
        ipc = "ai-lab-review-" + uuid.uuid4().hex[:12]
        worker = "ai-lab-review-" + uuid.uuid4().hex[:12]
        started = time.perf_counter()
        process = None
        error = None
        try:
            rp.checked_run([docker, "volume", "create", ipc])
            rp.start_worker(docker, "react", source(label),
                            ROOT / "benchmarks/react_lead_form_adapter/mcp_worker.mjs",
                            rp.REACT_WORKER_IMAGE, "node", ipc, worker)
            rp.MODEL, rp.EFFORT = model, effort
            arguments = rp.cli_args(prompt, True) + ["--max-budget-usd", "2.00"]
            dump(destination / "invocation.json", {"arguments": arguments[1:], "model": model, "effort": effort})
            process = claude_cli.invoke(rp.cli_command(docker, ipc), arguments, cwd=None,
                                        env=claude_cli.child_environment(os.environ), timeout=600)
        except Exception as exc:
            error = {"type": type(exc).__name__, "message": str(exc)}
            dump(destination / "error.json", error)
        finally:
            subprocess.run([docker, "rm", "-f", worker], capture_output=True, check=False)
            subprocess.run([docker, "volume", "rm", "-f", ipc], capture_output=True, check=False)
        if process is not None:
            (destination / "stream.jsonl").write_text(process.stdout, encoding="utf-8")
            (destination / "stderr.txt").write_text(process.stderr, encoding="utf-8")
            events, workflow = _events(process.stdout)
            dump(destination / "history.json", {"events": events, "workflow": workflow})
            cli = claude_cli.summarize_run(process)
            tokens, cost = price_trial(cli, model)
            init = next((json.loads(line) for line in process.stdout.splitlines()
                         if line.startswith('{"type":"system","subtype":"init"')), {})
            result_text = cli["result_text"]
            status = cli["status"]
            model_check = check_model(cli, model)
            actual_effort_flag = init.get("per_turn_effort_active")
            cli_version = init.get("claude_code_version")
            stderr = process.stderr[-2000:]
            returncode = process.returncode
            cli_seconds = round(process.wall_seconds, 3)
        else:
            events, workflow = [], {}
            tokens, cost = None, {"api_equivalent_usd": None, "complete": False}
            result_text, status, model_check = None, "setup_error", {"status": "unverified"}
            actual_effort_flag, cli_version, stderr, returncode, cli_seconds = None, None, "", None, None
        record = {
            "label": label, "phase": phase, "run_id": run_id, "model_requested": model,
            "effort_requested": effort, "status": status,
            "wall_seconds": round(time.perf_counter() - started, 3), "cli_seconds": cli_seconds,
            "model_check": model_check, "per_turn_effort_active": actual_effort_flag,
            "cli_version": cli_version, "code_unchanged": rp.files(source(label)) == frozen[label],
            "tokens": tokens, "thinking_tokens": cli["thinking_tokens"] if process else None,
            "cost": cost, "result_text": result_text, "workflow": workflow,
            "stderr": stderr, "returncode": returncode, "error": error,
        }
        dump(destination / "run.json", record)
        records.append({key: value for key, value in record.items() if key not in ("result_text", "stderr")})
        dump(RUNS / "progress.json", records)
        print(json.dumps({"run_id": run_id, "status": status, "seconds": record["wall_seconds"],
                          "cost": cost.get("api_equivalent_usd"), "model": model_check,
                          "code_unchanged": record["code_unchanged"]}), flush=True)
        if not record["code_unchanged"]:
            raise RuntimeError("source artifact changed")


if __name__ == "__main__":
    main()
