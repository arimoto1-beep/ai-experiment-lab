"""AI実験室 #9: two pinned, read-only review comparisons."""

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

from ai_lab import claude_cli
from ai_lab.agentic_dev import _check_auth, _events, AgenticConfig
from ai_lab.experiment import check_model, price_trial


ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "analysis" / "review-perspectives-20261109"
RUNS = ROOT / "results" / "review_perspectives_20261109"
MODEL = "claude-haiku-5-5"
EFFORT = "medium"
CLI_IMAGE = "sha256:02ddedacf8dc79f1402df822f09699fc3be6d18bd93e0140b4d18b39fa57806b"
PY_WORKER_IMAGE = "sha256:df55a0750cec45cda014a9269eb980e76a0fb2e29ea37e6186c39f6af64b59d4"
REACT_WORKER_IMAGE = "sha256:2d3c09ec50df53d21e8651eaed5c8ca296a1954b6395ffd2a8624d1ca69cce2d"
AUTH_VOLUME = "ai-lab-claude-auth"
REVIEW_COMMON = (
    "Review the existing implementation against the supplied task specification. "
    "Use list_files and read_file to inspect the code and local specifications. "
    "Do not edit files or execute code. Report only concrete specification violations. "
    "For each finding give the file and relevant function or line, the violated requirement, "
    "a precise input or state that reproduces it, the observed versus required behavior, "
    "and confidence (high/medium/low). Separate unverified suspicions from confirmed findings. "
    "Return JSON with keys findings (array) and suspicions (array); each finding is an object "
    "with keys location, requirement, reproduction, actual, expected, confidence. "
    "An empty findings array is valid."
)
A_ROLE = "Perform a general, comprehensive review of this implementation for specification violations."
B_ROLES = (
    "Focus on compliance with the written specification and contracts. Trace each required behavior to the implementation, and report concrete violations you find.",
    "Focus on boundary values, missing or unusual but valid inputs, and failure paths. Report concrete specification violations you find.",
    "Focus on data integrity, persisted outputs, transitions between states, and repeated operations. Report concrete specification violations you find.",
)
DESIGN_INSTRUCTION = (
    "You are designing three independent code review perspectives for this task. "
    "You have only the task specification and file names; do not assume any particular bug. "
    "Create three distinct, complementary review perspectives with minimal overlap and good "
    "coverage of the specification. For each, write the exact instruction to give one reviewer. "
    "The reviewer will also receive the task specification, common reporting instruction, "
    "and read-only list_files/read_file tools. Each prompt must tell the reviewer what to inspect "
    "and must not mention tests, grading results, known bugs, or fixes. "
    "Return only JSON: {\"perspectives\": [{\"name\": string, \"prompt\": string}, "
    "{\"name\": string, \"prompt\": string}, {\"name\": string, \"prompt\": string}]}."
)
ORDER = (("A", 1), ("B", 1), ("C_design", 0), ("C", 1),
         ("A", 2), ("B", 2), ("C", 2), ("A", 3), ("B", 3), ("C", 3))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def files(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): sha(p) for p in sorted(root.rglob("*")) if p.is_file()}


def dump(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def task_config(task: str) -> tuple[Path, str, Path, str, str]:
    if task == "react":
        work = ROOT / "analysis/react-lead-form-review-20261102/rlfm-ea7769669b72/app"
        statement = (ROOT / "analysis/terminal-bench-v4.0.0/tasks/react-lead-form/instruction.md").read_text(encoding="utf-8")
        worker = ROOT / "benchmarks/react_lead_form_adapter/mcp_worker.mjs"
        image = REACT_WORKER_IMAGE
        worker_command = "node"
        manifest = json.loads((ROOT / "analysis/react-lead-form-review-20261102/restore-manifest.json").read_text(encoding="utf-8"))
        expected = {x["path"]: x["sha256"] for row in manifest["restorations"]
                    if row["source_run_id"] == "rlfm-ea7769669b72" for x in row["files"]}
        if files(work) != expected:
            raise RuntimeError("React artifact differs from #8 restoration manifest")
    elif task == "parcel":
        work = ROOT / "results/20261021-084022_parcel_manifest_claude-haiku-4-5_default_b7c795/trial_01/workspace"
        statement = (ROOT / "benchmarks/agentic_dev/parcel_manifest/problem.md").read_text(encoding="utf-8")
        worker = ROOT / "benchmarks/agentic_dev/mcp_worker.py"
        image = PY_WORKER_IMAGE
        worker_command = "python"
        original = json.loads((work.parent / "trial.json").read_text(encoding="utf-8"))["final_files"]
        if files(work) != original:
            raise RuntimeError("Parcel artifact differs from #6 trial manifest")
    else:
        raise ValueError(task)
    return work, statement, worker, image, worker_command


def checked_run(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, capture_output=True, text=True, **kwargs)


def start_worker(docker: str, task: str, work: Path, worker: Path, image: str, command: str,
                 ipc: str, name: str) -> None:
    target = "/app" if task == "react" else "/work"
    worker_target = "/opt/review-worker.mjs" if task == "react" else "/opt/review-worker.py"
    cmd = [docker, "run", "-d", "--name", name,
           "--user", "0:0" if task == "react" else "1000:1000", "--read-only", "--network", "none",
           "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
           "--tmpfs", "/tmp:rw,nosuid,size=128m",
           "--mount", f"type=bind,source={work},target={target},readonly",
           "--mount", f"type=bind,source={worker},target={worker_target},readonly",
           "--mount", f"type=volume,source={ipc},target=/ipc",
           "--env", "AI_LAB_REVIEW_READ_ONLY=1", image, command, worker_target]
    checked_run(cmd)
    for _ in range(60):
        ready = subprocess.run([docker, "exec", name, "test", "-S", "/ipc/mcp.sock"],
                               capture_output=True, check=False)
        if ready.returncode == 0:
            return
        time.sleep(0.2)
    logs = subprocess.run([docker, "logs", name], capture_output=True, text=True, check=False)
    raise RuntimeError("read-only MCP worker did not become ready: " + (logs.stdout + logs.stderr)[-2000:])


def cli_command(docker: str, ipc: str | None) -> list[str]:
    cmd = [docker, "run", "--rm", "--user", "1000:1000", "--read-only",
           "--network", "bridge", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
           "--tmpfs", "/tmp:rw,nosuid,size=256m",
           "--tmpfs", "/home/lab/.cache:rw,nosuid,size=128m",
           "--mount", f"type=volume,source={AUTH_VOLUME},target=/home/lab/.claude"]
    if ipc:
        cmd += ["--mount", f"type=volume,source={ipc},target=/ipc"]
    return cmd + [CLI_IMAGE, "claude"]


def cli_args(prompt: str, tools: bool) -> list[str]:
    args = ["-p", prompt, "--model", MODEL, "--effort", EFFORT,
            "--output-format", "stream-json", "--verbose", "--restricted",
            "--no-session-persistence", "--disable-slash-commands", "--tools", "",
            "--permission-mode", "dontAsk", "--permission-prompts", "none",
            "--max-turns", "35"]
    if tools:
        mcp = {"mcpServers": {"lab": {"command": "python", "args": ["/opt/ai-lab/mcp_bridge.py"]}}}
        args += ["--strict-mcp-config", "--mcp-config", json.dumps(mcp),
                 "--allowedTools", "mcp__lab__list_files,mcp__lab__read_file"]
    else:
        args += ["--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}']
    return args


def parse_perspectives(result: str) -> list[dict[str, str]]:
    value = result.strip()
    if value.startswith("```"):
        value = "\n".join(value.splitlines()[1:-1]).strip()
    data = json.loads(value)
    items = data["perspectives"]
    if len(items) != 3 or any(not isinstance(x.get("name"), str) or
                               not isinstance(x.get("prompt"), str) or not x["prompt"].strip()
                               for x in items):
        raise ValueError("designer did not return three nonempty perspectives")
    return items


def run_one(docker: str, task: str, phase: str, index: int, prompt: str,
            work: Path, worker_file: Path, image: str, worker_command: str,
            expected_files: dict[str, str], directory: Path) -> dict:
    run_id = f"{task}-{phase.lower()}-{index}-{uuid.uuid4().hex[:8]}"
    destination = directory / run_id
    destination.mkdir()
    (destination / "prompt.txt").write_text(prompt, encoding="utf-8")
    ipc = "ai-lab-review-" + uuid.uuid4().hex[:12] if phase != "C_design" else None
    worker_name = "ai-lab-review-" + uuid.uuid4().hex[:12]
    started = time.perf_counter()
    try:
        if ipc:
            checked_run([docker, "volume", "create", ipc])
            start_worker(docker, task, work, worker_file, image, worker_command, ipc, worker_name)
        process = claude_cli.invoke(cli_command(docker, ipc), cli_args(prompt, bool(ipc)),
                                    cwd=None, env=claude_cli.child_environment(os.environ), timeout=600)
    finally:
        if ipc:
            subprocess.run([docker, "rm", "-f", worker_name], capture_output=True, check=False)
            subprocess.run([docker, "volume", "rm", "-f", ipc], capture_output=True, check=False)
    (destination / "stream.jsonl").write_text(process.stdout, encoding="utf-8")
    (destination / "stderr.txt").write_text(process.stderr, encoding="utf-8")
    events, workflow = _events(process.stdout)
    dump(destination / "history.json", {"events": events, "workflow": workflow})
    cli = claude_cli.summarize_run(process)
    tokens, cost = price_trial(cli, MODEL)
    after = files(work)
    record = {"task": task, "phase": phase, "index": index, "run_id": run_id,
              "status": cli["status"], "wall_seconds": round(time.perf_counter() - started, 3),
              "cli_seconds": round(process.wall_seconds, 3), "code_unchanged": after == expected_files,
              "model_check": check_model(cli, MODEL), "tokens": tokens,
              "thinking_tokens": cli["thinking_tokens"], "cost": cost,
              "result_text": cli["result_text"], "workflow": workflow,
              "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest()}
    dump(destination / "run.json", record)
    return record


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", choices=("react", "parcel"), required=True)
    parser.add_argument("--docker", required=True)
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args()
    work, statement, worker, image, worker_command = task_config(args.task)
    expected = files(work)
    docker = args.docker
    for pinned in (CLI_IMAGE, image):
        if checked_run([docker, "image", "inspect", pinned, "--format", "{{.Id}}"]).stdout.strip() != pinned:
            raise RuntimeError("pinned Docker image unavailable")
    auth_config = AgenticConfig(task="parcel_manifest", model_id=MODEL, effort=EFFORT,
                                runs=1, timeout=600, results_dir=OUT, docker_bin=docker,
                                image=CLI_IMAGE, worker_image=image, auth_volume=AUTH_VOLUME)
    auth = _check_auth(auth_config)
    if args.preflight:
        probe_ipc = "ai-lab-review-probe-" + uuid.uuid4().hex[:12]
        probe_worker = "ai-lab-review-probe-" + uuid.uuid4().hex[:12]
        checked_run([docker, "volume", "create", probe_ipc])
        try:
            start_worker(docker, args.task, work, worker, image, worker_command, probe_ipc, probe_worker)
        finally:
            subprocess.run([docker, "rm", "-f", probe_worker], capture_output=True, check=False)
            subprocess.run([docker, "volume", "rm", "-f", probe_ipc], capture_output=True, check=False)
        print(json.dumps({"task": args.task, "files": len(expected), "auth": auth,
                          "worker_sha256": sha(worker)}, ensure_ascii=False))
        return
    directory = RUNS / args.task
    directory.mkdir(parents=True, exist_ok=False)
    dump(directory / "frozen-inputs.json", {"task": args.task, "files": expected,
         "statement_sha256": hashlib.sha256(statement.encode()).hexdigest(),
         "worker_sha256": sha(worker), "model": MODEL, "effort": EFFORT,
         "roles": {"A": A_ROLE, "B": B_ROLES}, "common": REVIEW_COMMON,
         "design_instruction": DESIGN_INSTRUCTION, "order": ORDER, "auth": auth})
    tree = "\n".join(expected)
    roles = None
    records = []
    for phase, index in ORDER:
        if phase == "C_design":
            prompt = f"{DESIGN_INSTRUCTION}\n\nTASK SPECIFICATION:\n{statement}\n\nFILE NAMES:\n{tree}"
        elif phase == "C" and roles is None:
            continue
        else:
            role = A_ROLE if phase == "A" else B_ROLES[index - 1] if phase == "B" else roles[index - 1]["prompt"]
            prompt = f"TASK SPECIFICATION:\n{statement}\n\nCOMMON REVIEW INSTRUCTIONS:\n{REVIEW_COMMON}\n\nPERSPECTIVE:\n{role}"
        record = run_one(docker, args.task, phase, index, prompt, work, worker,
                         image, worker_command, expected, directory)
        records.append(record)
        if phase == "C_design":
            try:
                roles = parse_perspectives(record["result_text"] or "") if record["status"] == "ok" else None
                if roles:
                    dump(directory / "generated-perspectives.json", roles)
            except (ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
                dump(directory / "design-error.json", {"error": str(error)})
                roles = None
        dump(directory / "progress.json", [{k: v for k, v in x.items() if k != "result_text"} for x in records])
        print(json.dumps({"phase": phase, "index": index, "status": record["status"],
                          "cost": record["cost"].get("api_equivalent_usd"),
                          "code_unchanged": record["code_unchanged"]}), flush=True)
        if not record["code_unchanged"]:
            raise RuntimeError("source changed during read-only review")


if __name__ == "__main__":
    main()
