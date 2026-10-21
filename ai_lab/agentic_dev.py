"""小規模な複数ファイル開発ベンチマーク。実モデルは隔離コンテナ内だけで起動する。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from ai_lab import claude_cli
from ai_lab.experiment import check_model, price_trial


ROOT = Path(__file__).resolve().parent.parent
BUNDLES = ROOT / "benchmarks" / "agentic_dev"
TASKS = ("parcel_manifest", "room_booking")
MAX_TURNS = 20
PUBLIC_COMMAND = "python -m pytest -q public_tests -p no:cacheprovider"


@dataclass(frozen=True)
class AgenticConfig:
    task: str
    model_id: str
    effort: str
    runs: int
    timeout: float
    results_dir: Path
    image: str = "ai-lab-agent:1"
    worker_image: str = "ai-lab-agent-worker:1"
    docker_bin: str = "docker"
    auth_volume: str = "ai-lab-claude-auth"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _files(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): _sha(p) for p in sorted(root.rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"}


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def validate_bundle(task: str, bundles: Path = BUNDLES) -> tuple[Path, dict[str, str]]:
    if task not in TASKS:
        raise ValueError(f"未知の開発課題です: {task!r}（指定可能: {', '.join(TASKS)}）")
    root = bundles / task
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    expected = manifest["sha256"]
    actual = _files(root)
    actual.pop("manifest.json", None)
    if actual != expected:
        missing = sorted(set(expected) - set(actual))
        added = sorted(set(actual) - set(expected))
        changed = sorted(k for k in expected.keys() & actual.keys() if expected[k] != actual[k])
        raise ValueError(f"課題の固定ファイルが変わっています: missing={missing}, added={added}, changed={changed}")
    for required in ("problem.md", "starter", "public_tests", "hidden_tests"):
        if not (root / required).exists():
            raise ValueError(f"課題ファイルがありません: {root / required}")
    return root, actual


def build_prompt(root: Path) -> str:
    statement = (root / "problem.md").read_text(encoding="utf-8").strip()
    return (
        "次の既存Pythonプロジェクトを調査し、仕様を満たすまで修正してください。\n"
        "作業前に関連ファイルを読み、変更後は公開テストを実行してください。失敗したら原因を調べて再修正できます。\n"
        f"公開テストは run_public_tests ツールで実行してください（内部コマンド: {PUBLIC_COMMAND}）。\n"
        "非公開テストは作業環境にありません。公開テストやテスト設定は変更しないでください。\n"
        "編集対象は src/ 以下だけです。外部ネットワークから解答を探す必要はありません。\n"
        "終了時に、変更内容と実行した確認を簡潔に報告してください。\n\n"
        f"===== 仕様 =====\n{statement}\n"
    )


def agent_args(model_id: str, effort: str, prompt: str) -> list[str]:
    effort = claude_cli.resolve_effort(model_id, effort)
    return [
        "-p", prompt, "--model", model_id,
        *([] if effort == "default" else ["--effort", effort]),
        "--output-format", "stream-json", "--verbose",
        "--restricted", "--no-session-persistence", "--disable-slash-commands",
        "--strict-mcp-config",
        "--mcp-config", json.dumps({"mcpServers": {"lab": {"command": "python",
                                                    "args": ["/opt/ai-lab/mcp_bridge.py"]}}}),
        "--tools", "",
        "--permission-mode", "dontAsk", "--permission-prompts", "none",
        "--allowedTools", "mcp__lab__list_files,mcp__lab__read_file,mcp__lab__write_file,mcp__lab__run_public_tests",
        "--max-turns", str(MAX_TURNS),
    ]


def _docker_prefix(config: AgenticConfig, workspace: Path, name: str, *, role: str = "cli",
                   ipc: str | None = None, grader: bool = False,
                   hidden: Path | None = None, output: Path | None = None) -> list[str]:
    # ホストのリポジトリ全体は決してマウントしない。
    command = [config.docker_bin, "run", "--rm", "--name", name,
               "--workdir", "/work", "--user", "1000:1000", "--read-only",
               "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
               "--tmpfs", "/tmp:rw,nosuid,size=256m",
               "--cpus", "2", "--memory", "4g", "--memory-swap", "4g", "--pids-limit", "256"]
    if grader:
        assert hidden is not None and output is not None
        command += ["--network", "none",
                    "--mount", f"type=bind,source={workspace},target=/work,readonly",
                    "--mount", f"type=bind,source={hidden},target=/hidden,readonly",
                    "--mount", f"type=bind,source={output},target=/out",
                    "--env", "PYTHONPATH=/work/src", "--env", "PYTHONDONTWRITEBYTECODE=1"]
        return command + [config.worker_image]
    if role == "worker":
        assert ipc is not None
        command += ["--network", "none",
                    "--mount", f"type=bind,source={workspace},target=/work",
                    "--mount", f"type=bind,source={workspace / 'public_tests'},target=/work/public_tests,readonly",
                    "--mount", f"type=volume,source={ipc},target=/ipc",
                    "--env", "PYTHONPATH=/work/src", "--env", "PYTHONDONTWRITEBYTECODE=1"]
        return command + [config.worker_image]
    if role != "cli" or ipc is None:
        raise ValueError("invalid container role")
    command += ["--network", "bridge",
                "--mount", f"type=volume,source={ipc},target=/ipc",
                "--mount", f"type=volume,source={config.auth_volume},target=/home/lab/.claude",
                "--tmpfs", "/home/lab/.cache:rw,nosuid,size=128m"]
    return command + [config.image]


def _check_runtime(config: AgenticConfig) -> tuple[str, str]:
    if shutil.which(config.docker_bin) is None:
        raise RuntimeError("隔離コンテナのDockerが見つかりません。実モデル試行は開始しません。")
    ids = []
    for image in (config.image, config.worker_image):
        proc = subprocess.run([config.docker_bin, "image", "inspect", image, "--format", "{{.Id}}"],
                              capture_output=True, text=True, timeout=30, check=False)
        if proc.returncode != 0 or not proc.stdout.strip():
            raise RuntimeError(f"Docker image unavailable: {image}")
        ids.append(proc.stdout.strip())
    return ids[0], ids[1]


def _check_auth(config: AgenticConfig) -> dict[str, str]:
    # 課題ファイルは認証確認に不要。モデル呼び出し前にサブスクリプションを確認する。
    command = [config.docker_bin, "run", "--rm", "--workdir", "/tmp", "--user", "1000:1000",
               "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
               "--cpus", "2", "--memory", "4g", "--memory-swap", "4g", "--pids-limit", "256",
               "--tmpfs", "/tmp:rw,nosuid,size=64m",
               "--tmpfs", "/home/lab/.cache:rw,nosuid,size=64m",
               "--mount", f"type=volume,source={config.auth_volume},target=/home/lab/.claude",
               config.image, "claude"]
    return claude_cli.preflight(command, claude_cli.child_environment(os.environ))


def _stop_container(config: AgenticConfig, name: str) -> None:
    subprocess.run([config.docker_bin, "rm", "-f", name], capture_output=True, timeout=20, check=False)


def _start_worker(config: AgenticConfig, workspace: Path, name: str, ipc: str) -> None:
    volume = subprocess.run([config.docker_bin, "volume", "create", ipc],
                            capture_output=True, text=True, timeout=30, check=False)
    if volume.returncode != 0:
        raise RuntimeError("Cannot create trial IPC volume")
    command = _docker_prefix(config, workspace, name, role="worker", ipc=ipc)
    started = subprocess.run(command[:2] + ["-d"] + command[2:], capture_output=True,
                             text=True, timeout=30, check=False)
    if started.returncode != 0:
        raise RuntimeError("Cannot start trial work container")
    for _ in range(50):
        ready = subprocess.run([config.docker_bin, "exec", name, "test", "-S", "/ipc/mcp.sock"],
                               capture_output=True, timeout=5, check=False)
        if ready.returncode == 0:
            return
        time.sleep(0.1)
    raise RuntimeError("Trial work server did not become ready")


def _remove_ipc(config: AgenticConfig, ipc: str) -> None:
    subprocess.run([config.docker_bin, "volume", "rm", ipc], capture_output=True,
                   timeout=20, check=False)


def _events(stream: str) -> tuple[list[dict[str, Any]], dict[str, int]]:
    events: list[dict[str, Any]] = []
    pending: dict[str, str] = {}
    failed_test = False
    counts = {"reads": 0, "edits": 0, "test_runs": 0, "failed_test_runs": 0,
              "edits_after_failed_test": 0}
    for line in stream.splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = row.get("message", row)
        if not isinstance(message, dict):
            continue
        content = message.get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                tool = str(block.get("name", ""))
                tool_id = str(block.get("id", ""))
                detail = block.get("input", {})
                pending[tool_id] = tool
                if tool in ("Read", "Glob", "Grep", "mcp__lab__list_files", "mcp__lab__read_file"):
                    counts["reads"] += 1
                if tool in ("Write", "Edit", "mcp__lab__write_file"):
                    counts["edits"] += 1
                    if failed_test:
                        counts["edits_after_failed_test"] += 1
                if tool == "mcp__lab__run_public_tests" or (tool in ("Bash", "PowerShell") and isinstance(detail, dict) and PUBLIC_COMMAND in str(detail.get("command", ""))):
                    counts["test_runs"] += 1
                events.append({"kind": "tool_use", "tool": tool, "id": tool_id, "input": detail})
            elif block.get("type") == "tool_result":
                tool_id = str(block.get("tool_use_id", ""))
                tool = pending.get(tool_id, "")
                value = block.get("content", "")
                output = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
                failed_count = re.search(r"\b([1-9][0-9]*) failed\b", output.lower())
                if tool in ("Bash", "PowerShell", "mcp__lab__run_public_tests") and (failed_count or block.get("is_error") or re.search(r"exit_code=[1-9]", output)):
                    failed_test = True
                    counts["failed_test_runs"] += 1
                events.append({"kind": "tool_result", "tool": tool, "id": tool_id,
                               "is_error": bool(block.get("is_error")), "output": output[:12000]})
    return events, counts


def _grade(config: AgenticConfig, workspace: Path, hidden: Path, trial_dir: Path) -> dict[str, Any]:
    name = "ai-lab-grade-" + uuid.uuid4().hex[:12]
    command = _docker_prefix(config, workspace, name, grader=True, hidden=hidden, output=trial_dir)
    command += ["python", "-m", "pytest", "/hidden", "-q", "-p", "no:cacheprovider",
                "--junitxml=/out/hidden_junit.xml"]
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        _stop_container(config, name)
        proc = None
        timed_out = True
        output = claude_cli._text(exc.stdout) + claude_cli._text(exc.stderr)
        (trial_dir / "hidden_output.txt").write_text(output, encoding="utf-8")
    if proc is not None:
        (trial_dir / "hidden_output.txt").write_text(proc.stdout + proc.stderr, encoding="utf-8")
    junit = trial_dir / "hidden_junit.xml"
    tests = failures = errors = skipped = 0
    if junit.exists():
        for suite in ET.parse(junit).getroot().iter("testsuite"):
            tests += int(suite.get("tests", "0"))
            failures += int(suite.get("failures", "0"))
            errors += int(suite.get("errors", "0"))
            skipped += int(suite.get("skipped", "0"))
    return {"passed": not timed_out and proc is not None and proc.returncode == 0 and tests > 0
            and failures == 0 and errors == 0, "tests": tests, "failures": failures,
            "errors": errors, "skipped": skipped, "timed_out": timed_out,
            "returncode": None if proc is None else proc.returncode}


def dry_run(config: AgenticConfig) -> str:
    root, hashes = validate_bundle(config.task)
    prompt = build_prompt(root)
    sample = config.results_dir / "<experiment>" / "trial_01" / "workspace"
    ipc = "ai-lab-ipc-example"
    worker_command = _docker_prefix(config, sample, "ai-lab-work-example", role="worker", ipc=ipc)
    command = _docker_prefix(config, sample, "ai-lab-trial-example", ipc=ipc) + ["claude", *agent_args(config.model_id, config.effort, "<課題文>")]
    return "\n".join([
        "[dry-run] 実モデル・Docker・認証は呼び出しません。",
        f"課題: {config.task} / 固定ファイル: {len(hashes)} / prompt_sha256: {hashlib.sha256(prompt.encode()).hexdigest()}",
        f"モデル: {config.model_id} / effort: {config.effort} / runs: {config.runs}",
        f"timeout: {config.timeout} 秒 / max-turns: {MAX_TURNS} / image: {config.image}",
        "CLIコンテナ: 認証ボリュームとIPCのみをマウント。作業コピーはマウントしません。",
        "作業コンテナ: 作業コピーとIPCのみをマウント。ネットワーク・認証情報はありません。",
        "採点用コンテナ: 作業コピーと非公開テストを読み取り専用でマウントし、ネットワークを遮断します。",
        "コマンド（課題文と実験ディレクトリ名を省略）:",
        "  worker: " + " ".join(worker_command),
        "  cli: " + " ".join(command),
    ])


def run(config: AgenticConfig, log: Callable[[str], None] = print) -> Path:
    if config.runs < 1 or config.timeout <= 0:
        raise ValueError("runs と timeout は正の値を指定してください")
    root, hashes = validate_bundle(config.task)
    image_id, worker_image_id = _check_runtime(config)  # コンテナがなければ結果ディレクトリも作らない
    requested_image = config.image
    requested_worker_image = config.worker_image
    config = replace(config, image=image_id, worker_image=worker_image_id)
    auth = _check_auth(config)
    prompt = build_prompt(root)
    config.results_dir.mkdir(parents=True, exist_ok=True)
    exp_dir = config.results_dir / (datetime.now().strftime("%Y%m%d-%H%M%S") + f"_{config.task}_{config.model_id}_{config.effort}_{uuid.uuid4().hex[:6]}")
    exp_dir.mkdir()
    meta = {"task": config.task, "model": config.model_id, "effort": config.effort,
            "comparison_basis": "model_and_effort", "runs": config.runs,
            "timeout_seconds": config.timeout, "max_turns": MAX_TURNS,
            "image": requested_image, "image_id": image_id,
            "worker_image": requested_worker_image, "worker_image_id": worker_image_id,
            "bundle_sha256": hashes,
            "claude_version": auth["version"], "auth_method": auth["auth_method"],
            "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "started_at": datetime.now().astimezone().isoformat()}
    _write_json(exp_dir / "experiment.json", meta)
    records: list[dict[str, Any]] = []
    for index in range(1, config.runs + 1):
        trial_dir = exp_dir / f"trial_{index:02d}"
        workspace = trial_dir / "workspace"
        trial_dir.mkdir()
        shutil.copytree(root / "starter", workspace, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copytree(root / "public_tests", workspace / "public_tests",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        initial = _files(workspace)
        name = "ai-lab-agent-" + uuid.uuid4().hex[:12]
        worker = "ai-lab-work-" + uuid.uuid4().hex[:12]
        ipc = "ai-lab-ipc-" + uuid.uuid4().hex[:12]
        command = _docker_prefix(config, workspace, name, ipc=ipc) + ["claude"]
        started = time.perf_counter()
        try:
            _start_worker(config, workspace, worker, ipc)
            process = claude_cli.invoke(command, agent_args(config.model_id, config.effort, prompt),
                                        cwd=str(workspace), env=claude_cli.child_environment(os.environ), timeout=config.timeout)
        finally:
            _stop_container(config, name)
            _stop_container(config, worker)
            _remove_ipc(config, ipc)
        (trial_dir / "claude_stream.jsonl").write_text(process.stdout, encoding="utf-8")
        (trial_dir / "claude_stderr.txt").write_text(process.stderr, encoding="utf-8")
        history, workflow = _events(process.stdout)
        _write_json(trial_dir / "history.json", {"events": history, "workflow": workflow})
        final = _files(workspace)
        public_before = {k: v for k, v in initial.items() if k.startswith("public_tests/")}
        public_after = {k: v for k, v in final.items() if k.startswith("public_tests/")}
        integrity = public_before == public_after and all(k.startswith(("src/", "public_tests/")) for k in final)
        evaluation = _grade(config, workspace, root / "hidden_tests", trial_dir)
        cli = claude_cli.summarize_run(process)
        tokens, cost = price_trial(cli, config.model_id)
        success = evaluation["passed"] and integrity
        failure_kind = (None if success else
                        "workspace_tamper" if not integrity else
                        "timeout" if process.timed_out else
                        "grader_error" if evaluation["tests"] == 0 else
                        "hidden_test_failure")
        record = {"trial": index, "task": config.task, "effort": config.effort,
                  "outcome": "pass" if success else "fail", "failure_kind": failure_kind,
                  "workflow_complete": workflow["test_runs"] > workflow["failed_test_runs"],
                  "wall_seconds": round(process.wall_seconds, 3),
                  "total_wall_seconds": round(time.perf_counter() - started, 3),
                  "model_check": check_model(cli, config.model_id), "claude": cli,
                  "workflow": workflow, "initial_files": initial, "final_files": final,
                  "workspace_integrity": integrity, "evaluation": evaluation,
                  "tokens": tokens, "cost": cost}
        _write_json(trial_dir / "trial.json", record)
        records.append(record)
        completed = len(records)
        passed = sum(r["outcome"] == "pass" for r in records)
        prices = [r["cost"]["api_equivalent_usd"] for r in records]
        priced = all(x is not None and r["cost"]["complete"] for x, r in zip(prices, records))
        summary = {"task": config.task, "model": config.model_id, "effort": config.effort,
                   "comparison_basis": "model_and_effort", "requested_runs": config.runs,
                   "completed_runs": completed, "passed": passed, "pass_rate": passed / completed,
                   "any_passed": bool(passed), "cli_not_ok": sum(r["claude"]["status"] != "ok" for r in records),
                   "mean_wall_seconds": sum(r["wall_seconds"] for r in records) / completed,
                   "tokens": {key: sum((r["tokens"] or {}).get(key, 0) for r in records)
                              for key in ("input", "output", "cache_read", "cache_write")},
                   "api_equivalent_usd_total": round(sum(x or 0 for x in prices), 6) if priced else None,
                   "api_equivalent_usd_mean": round(sum(x or 0 for x in prices) / completed, 6) if priced else None,
                   "api_equivalent_usd_per_pass": round(sum(x or 0 for x in prices) / passed, 6) if priced and passed else None,
                   "cost_complete": priced,
                   "workflow_complete_runs": sum(r["workflow_complete"] for r in records),
                   "cli_reported_usd_total": round(sum(r["claude"]["cli_total_cost_usd"] or 0 for r in records), 6),
                   "actual_model_ids": sorted({m for r in records for m in r["model_check"]["actual_model_ids"]}),
                   "model_mismatch_trials": sum(r["model_check"]["status"] == "mismatch" for r in records),
                   "model_unverified_trials": sum(r["model_check"]["status"] == "unverified" for r in records),
                   "failure_kinds": {kind: sum(r["failure_kind"] == kind for r in records)
                                     for kind in sorted({r["failure_kind"] for r in records if r["failure_kind"]})}}
        _write_json(exp_dir / "summary.json", summary)
        log(f"[{index}/{config.runs}] {record['outcome']} / {record['wall_seconds']} 秒 / CLI={cli['status']}")
    return exp_dir
