"""One-shot, isolated test-writing trial for AI実験室 #12."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from ai_lab import claude_cli, review_perspectives as rp
from ai_lab.agentic_dev import AgenticConfig, _check_auth, _events
from ai_lab.experiment import check_model, price_trial

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
RUNS = ROOT / "results/test_driven_review_20261122"
ORIGINAL = ROOT / "results/react_lead_form_harbor/rlfm-0df740e1d9e8/jobs/rlfm-0df740e1d9e8/react-lead-form__YRqsvPJ/artifacts/app"
SOURCE = OUT / "source-app"
TASK = ROOT / "analysis/terminal-bench-v4.0.0"
MODEL = "claude-haiku-5-5"
EFFORT = "high"
IMAGE = "sha256:9324cc278c6c71938d6bb2e8d2354c346677fdeee80b3bcbd8410a8529808059"
WORKER = OUT / "test_worker.mjs"
INSTRUCTION = (
    "Check the supplied specification and program, and create tests that verify specification compliance. "
    "Actually run the tests against the target program. For failed tests, report the expected result, "
    "actual result, relevant specification, and investigate whether the cause is a program defect, "
    "a test mistake, or an environment problem. Record successful test results too. "
    "Do not modify the target program.\n\n"
    "Use list_files/read_file for source and specifications. Save TypeScript tests with write_test. "
    "Use node:test and node:assert/strict; test files run with tsx --test. "
    "Each run uses a fresh disposable copy of the program at /tmp/test-app; import source modules from that path. "
    "You can create fixtures and wrappers inside your test files. The program output directory in the copy is writable. "
    "Use run_tests to execute all saved tests. Report which tests passed, failed, or could not run, "
    "with evidence. You have no tool to edit implementation files."
)


def dump(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def files(directory: Path) -> dict[str, str]:
    return {p.relative_to(directory).as_posix(): sha(p) for p in sorted(directory.rglob("*")) if p.is_file()}


def source_checks() -> dict[str, str]:
    frozen11 = json.loads((ROOT / "analysis/repeated-review-20261116/frozen-inputs.json").read_text(encoding="utf-8"))["files"]["Z"]
    if files(ORIGINAL) != frozen11:
        raise RuntimeError("original saved Z differs from #11 frozen input")
    if not SOURCE.exists():
        shutil.copytree(ORIGINAL, SOURCE)
    if files(SOURCE) != frozen11:
        raise RuntimeError("restored Z differs byte-for-byte from the saved original")
    return frozen11


def prompt() -> str:
    statement = (TASK / "tasks/react-lead-form/instruction.md").read_text(encoding="utf-8")
    return f"TASK SPECIFICATION:\n{statement}\n\nTESTING INSTRUCTIONS:\n{INSTRUCTION}"


def docker_cmd() -> str:
    return os.environ.get("RLFM_DOCKER") or shutil.which("docker") or "docker"


def checked(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace")


def preflight() -> None:
    docker = docker_cmd()
    if checked(["git", "-C", str(TASK), "rev-parse", "HEAD"]).stdout.strip() != "452bf305c6daa62fc59061d22133a7cbc7c1572e":
        raise RuntimeError("official task commit mismatch")
    frozen = source_checks()
    if checked([docker, "image", "inspect", rp.CLI_IMAGE, "--format", "{{.Id}}"]).stdout.strip() != rp.CLI_IMAGE:
        raise RuntimeError("pinned CLI image unavailable")
    if checked([docker, "image", "inspect", IMAGE, "--format", "{{.Id}}"]).stdout.strip() != IMAGE:
        raise RuntimeError("pinned test image unavailable")
    config = AgenticConfig(task="parcel_manifest", model_id=MODEL, effort=EFFORT, runs=1,
                           timeout=600, results_dir=OUT, docker_bin=docker, image=rp.CLI_IMAGE,
                           worker_image=IMAGE, auth_volume=rp.AUTH_VOLUME)
    auth = _check_auth(config)
    # A non-model smoke test checks dependencies and imports in the disposable copy.
    smoke = checked([docker, "run", "--rm", "--network", "none", "--cap-drop", "ALL",
                     "--security-opt", "no-new-privileges", "--read-only",
                     "--tmpfs", "/tmp:rw,nosuid,size=512m",
                     "--mount", f"type=bind,source={SOURCE},target=/source,readonly",
                     "--mount", f"type=bind,source={OUT / 'preflight.test.ts'},target=/preflight.test.ts,readonly",
                     IMAGE, "sh", "-c", "cp -a /source /tmp/test-app && ln -s /app/node_modules /tmp/test-app/node_modules && /app/node_modules/.bin/tsx --test /preflight.test.ts"])
    if "# pass 1" not in smoke.stdout:
        raise RuntimeError("preflight test did not pass")
    value = prompt()
    (OUT / "prompt.txt").write_text(value, encoding="utf-8")
    manifest = {
        "source_files": frozen, "source_original": str(ORIGINAL.relative_to(ROOT)).replace('\\', '/'),
        "task_commit": "452bf305c6daa62fc59061d22133a7cbc7c1572e",
        "statement_sha256": sha(TASK / "tasks/react-lead-form/instruction.md"),
        "preregistration_sha256": sha(OUT / "preregistration.md"), "prompt_sha256": sha(OUT / "prompt.txt"),
        "worker_sha256": sha(WORKER), "model": MODEL, "effort": EFFORT,
        "cli_image": rp.CLI_IMAGE, "test_image": IMAGE,
        "timeout_seconds": 600, "max_turns": 35, "max_budget_usd": 2.0,
    }
    frozen_path = OUT / "frozen-inputs.json"
    if frozen_path.exists() and json.loads(frozen_path.read_text(encoding="utf-8")) != manifest:
        raise RuntimeError("frozen inputs changed")
    if not frozen_path.exists():
        dump(frozen_path, manifest)
    dump(OUT / "preflight.json", {"status": "ok", "auth_method": auth["auth_method"],
                                  "cli_version": auth["version"], "source_file_count": len(frozen),
                                  "source_byte_match": True, "smoke_passed": True})
    print(json.dumps({"preflight": "ok", "files": len(frozen), "auth_method": auth["auth_method"],
                      "cli_version": auth["version"]}))


def run(trial: int = 1) -> None:
    docker = docker_cmd()
    destination = RUNS if trial == 1 else ROOT / "results/test_driven_review_20261122_trial2"
    work = OUT / ("test-work" if trial == 1 else "test-work-trial2")
    manifest = json.loads((OUT / "frozen-inputs.json").read_text(encoding="utf-8"))
    if checked(["git", "-C", str(TASK), "rev-parse", "HEAD"]).stdout.strip() != manifest["task_commit"]:
        raise RuntimeError("official task commit changed after preflight")
    if sha(TASK / "tasks/react-lead-form/instruction.md") != manifest["statement_sha256"]:
        raise RuntimeError("official task statement changed after preflight")
    if files(SOURCE) != manifest["source_files"] or files(ORIGINAL) != manifest["source_files"]:
        raise RuntimeError("source changed after preflight")
    if sha(OUT / "preregistration.md") != manifest["preregistration_sha256"] or sha(OUT / "prompt.txt") != manifest["prompt_sha256"] or sha(WORKER) != manifest["worker_sha256"]:
        raise RuntimeError("pre-registered inputs changed")
    if trial == 2:
        previous = json.loads((RUNS / "run.json").read_text(encoding="utf-8"))
        if previous.get("status") != "error" or "OAuth session expired" not in (previous.get("result_text") or ""):
            raise RuntimeError("trial 1 is not the recorded authentication failure")
        config = AgenticConfig(task="parcel_manifest", model_id=MODEL, effort=EFFORT, runs=1,
                               timeout=600, results_dir=OUT, docker_bin=docker, image=rp.CLI_IMAGE,
                               worker_image=IMAGE, auth_volume=rp.AUTH_VOLUME)
        auth = _check_auth(config)
    else:
        auth = None
    if destination.exists():
        raise RuntimeError("trial directory exists; duplicate model attempt prohibited")
    destination.mkdir(parents=True)
    (work / "tests").mkdir(parents=True, exist_ok=False)
    ipc = "ai-lab-12-" + uuid.uuid4().hex[:12]
    worker_name = "ai-lab-12-" + uuid.uuid4().hex[:12]
    process = None
    error = None
    started = time.perf_counter()
    try:
        checked([docker, "volume", "create", ipc])
        checked([docker, "run", "-d", "--name", worker_name, "--user", "0:0",
                 "--read-only", "--network", "none", "--cap-drop", "ALL",
                 "--security-opt", "no-new-privileges", "--cpus", "2", "--memory", "4g", "--pids-limit", "256",
                 "--tmpfs", "/tmp:rw,nosuid,size=512m",
                 "--mount", f"type=bind,source={SOURCE},target=/source,readonly",
                 "--mount", f"type=bind,source={work},target=/work",
                 "--mount", f"type=bind,source={WORKER},target=/opt/test-worker.mjs,readonly",
                 "--mount", f"type=volume,source={ipc},target=/ipc",
                 IMAGE, "node", "/opt/test-worker.mjs"])
        for _ in range(60):
            if subprocess.run([docker, "exec", worker_name, "test", "-S", "/ipc/mcp.sock"], capture_output=True).returncode == 0:
                break
            time.sleep(0.2)
        else:
            raise RuntimeError("test worker did not become ready")
        args = ["-p", (OUT / "prompt.txt").read_text(encoding="utf-8"),
                "--model", MODEL, "--effort", EFFORT, "--output-format", "stream-json", "--verbose",
                "--restricted", "--no-session-persistence", "--disable-slash-commands", "--tools", "",
                "--permission-mode", "dontAsk", "--permission-prompts", "none", "--max-turns", "35",
                "--max-budget-usd", "2.00", "--strict-mcp-config",
                "--mcp-config", json.dumps({"mcpServers": {"lab": {"command": "python", "args": ["/opt/ai-lab/mcp_bridge.py"]}}}),
                "--allowedTools", "mcp__lab__list_files,mcp__lab__read_file,mcp__lab__write_test,mcp__lab__run_tests"]
        dump(destination / "invocation.json", {"arguments_without_prompt": args[2:], "prompt_sha256": manifest["prompt_sha256"]})
        process = claude_cli.invoke(rp.cli_command(docker, ipc), args, cwd=None,
                                    env=claude_cli.child_environment(os.environ), timeout=600)
    except Exception as exc:
        error = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        subprocess.run([docker, "rm", "-f", worker_name], capture_output=True)
        subprocess.run([docker, "volume", "rm", "-f", ipc], capture_output=True)
    if process is not None:
        (destination / "stream.jsonl").write_text(process.stdout, encoding="utf-8")
        (destination / "stderr.txt").write_text(process.stderr, encoding="utf-8")
        cli = claude_cli.summarize_run(process)
        tokens, cost = price_trial(cli, MODEL)
        events, workflow = _events(process.stdout)
        dump(destination / "history.json", {"events": events, "workflow": workflow})
        init = next((json.loads(line) for line in process.stdout.splitlines() if line.startswith('{"type":"system","subtype":"init"')), {})
        record = {"status": cli["status"], "model_requested": MODEL, "model_check": check_model(cli, MODEL),
                  "effort_requested": EFFORT, "per_turn_effort_active": init.get("per_turn_effort_active"),
                  "cli_version": init.get("claude_code_version"), "wall_seconds": round(time.perf_counter() - started, 3),
                  "cli_seconds": round(process.wall_seconds, 3), "tokens": tokens,
                  "thinking_tokens": cli["thinking_tokens"], "cost": cost,
                  "result_text": cli["result_text"], "returncode": process.returncode,
                  "timed_out": process.timed_out, "workflow": workflow, "error": error}
    else:
        record = {"status": "setup_error", "model_requested": MODEL, "effort_requested": EFFORT,
                  "wall_seconds": round(time.perf_counter() - started, 3), "error": error}
    record["trial_number"] = trial
    record["auth_method_at_start"] = auth["auth_method"] if auth else None
    record["source_unchanged"] = files(SOURCE) == manifest["source_files"] and files(ORIGINAL) == manifest["source_files"]
    dump(destination / "run.json", record)
    print(json.dumps({"status": record["status"], "wall_seconds": record["wall_seconds"],
                      "cost": record.get("cost", {}).get("api_equivalent_usd"),
                      "source_unchanged": record["source_unchanged"], "error": error}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    options = parser.add_mutually_exclusive_group()
    options.add_argument("--preflight", action="store_true")
    options.add_argument("--trial2", action="store_true")
    args = parser.parse_args()
    preflight() if args.preflight else run(2 if args.trial2 else 1)
