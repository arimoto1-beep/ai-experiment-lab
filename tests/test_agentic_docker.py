"""Docker smoke tests; opt in with AI_LAB_DOCKER_BIN."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from dataclasses import replace
from pathlib import Path

import pytest

from ai_lab import agentic_dev, claude_cli
from ai_lab.pricing import MODEL_IDS


DOCKER = os.environ.get("AI_LAB_DOCKER_BIN")
REFERENCE = Path(__file__).resolve().parent / "fixtures" / "agentic_reference"
pytestmark = pytest.mark.skipif(not DOCKER, reason="AI_LAB_DOCKER_BIN is not set")


def docker(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    assert DOCKER
    return subprocess.run([DOCKER, *args], input=stdin, capture_output=True,
                          text=True, timeout=120, check=False)


def rpc(config: agentic_dev.AgenticConfig, ipc: str, secret: str, requests: list[dict]) -> list[dict]:
    command = agentic_dev._docker_prefix(config, Path("/unused"),
                                          "ai-lab-probe-" + uuid.uuid4().hex[:12], ipc=ipc)
    proc = subprocess.run([*command[:2], "-i", *command[2:], "python", "/opt/ai-lab/mcp_bridge.py"],
                          input="\n".join(json.dumps(row) for row in requests) + "\n",
                          capture_output=True, text=True, timeout=30, check=False)
    assert proc.returncode == 0, proc.stderr
    assert secret not in proc.stdout + proc.stderr
    return [json.loads(line) for line in proc.stdout.splitlines()]


def call(i: int, name: str, **args) -> dict:
    return {"jsonrpc": "2.0", "id": i, "method": "tools/call",
            "params": {"name": name, "arguments": args}}


@pytest.mark.parametrize("task", agentic_dev.TASKS)
@pytest.mark.parametrize("model", ("haiku45", "haiku"))
def test_container_dry_run_and_grading(task: str, model: str, tmp_path: Path):
    assert DOCKER
    root, _ = agentic_dev.validate_bundle(task)
    model_id = MODEL_IDS[model]
    effort = claude_cli.resolve_effort(model_id, None)
    config = agentic_dev.AgenticConfig(task, model_id, effort, 1, 900, tmp_path,
                                       docker_bin=DOCKER, auth_volume="ai-lab-auth-" + uuid.uuid4().hex[:12])
    args = agentic_dev.agent_args(model_id, effort, "<smoke>")
    assert args[args.index("--max-turns") + 1] == str(agentic_dev.MAX_TURNS)
    assert args[args.index("--tools") + 1] == ""
    assert "--strict-mcp-config" in args and "--safe-mode" not in args
    assert ("--effort" in args) == (model == "haiku")
    assert task in agentic_dev.dry_run(config)
    cli_image, worker_image = agentic_dev._check_runtime(config)
    config = replace(config, image=cli_image, worker_image=worker_image)
    cli_command = agentic_dev._docker_prefix(config, tmp_path / "unused", "cli-check", ipc="check-ipc")
    worker_command = agentic_dev._docker_prefix(config, tmp_path / "unused", "work-check",
                                                role="worker", ipc="check-ipc")
    assert not any("target=/work" in item for item in cli_command)
    assert not any("target=/home/lab/.claude" in item for item in worker_command)
    assert not any("docker.sock" in item for item in cli_command + worker_command)
    assert cli_command[cli_command.index("--network") + 1] == "bridge"
    assert worker_command[worker_command.index("--network") + 1] == "none"
    for command in (cli_command, worker_command):
        assert command[command.index("--user") + 1] == "1000:1000"
        assert command[command.index("--memory-swap") + 1] == "4g"
        assert command[command.index("--pids-limit") + 1] == "256"
        assert "--read-only" in command and "--cap-drop" in command
    assert docker("run", "--rm", cli_image, "claude", "--version").returncode == 0
    workspace = tmp_path / "workspace"
    shutil.copytree(root / "starter", workspace)
    shutil.copytree(root / "public_tests", workspace / "public_tests")
    worker = "ai-lab-work-" + uuid.uuid4().hex[:12]
    ipc = "ai-lab-ipc-" + uuid.uuid4().hex[:12]
    secret = "DUMMY_CREDENTIAL_" + uuid.uuid4().hex
    try:
        assert docker("volume", "create", config.auth_volume).returncode == 0
        seed = docker("run", "--rm", "-i", "--user", "1000:1000", "--mount",
                      f"type=volume,source={config.auth_volume},target=/home/lab/.claude",
                      config.image, "python", "-c",
                      "from pathlib import Path; import sys; Path('/home/lab/.claude/sentinel').write_text(sys.stdin.read())",
                      stdin=secret)
        assert seed.returncode == 0, seed.stderr
        auth_probe = docker("run", "--rm", "--mount",
                            f"type=volume,source={config.auth_volume},target=/home/lab/.claude",
                            config.image, "python", "-c",
                            "from pathlib import Path; print(Path('/home/lab/.claude/sentinel').exists())")
        assert auth_probe.stdout.strip() == "True"
        agentic_dev._start_worker(config, workspace, worker, ipc)
        worker_probe = docker("exec", worker, "python", "-c",
                              "import os,socket,pathlib,shutil; p=pathlib.Path; "
                              "assert os.getuid()==1000; "
                              "assert shutil.which('claude') is None; "
                              "assert not p('/home/lab/.claude/sentinel').exists(); "
                              "assert not p('/var/run/docker.sock').exists(); "
                              "assert not p('/hidden').exists(); "
                              "assert not p('/work/.git').exists(); "
                              "assert p('/sys/fs/cgroup/memory.max').read_text().strip()=='4294967296'; "
                              "assert p('/sys/fs/cgroup/pids.max').read_text().strip()=='256'; "
                              "assert not os.access('/opt/ai-lab/mcp_worker.py',os.W_OK); "
                              "assert socket.socket().connect_ex(('1.1.1.1',443)) != 0; "
                              "print('isolated')")
        assert worker_probe.returncode == 0, worker_probe.stderr
        assert worker_probe.stdout.strip() == "isolated"
        observed = rpc(config, ipc, secret, [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            call(3, "read_file", path="/home/lab/.claude/sentinel"),
            call(4, "read_file", path="../hidden/test.py"),
            call(5, "write_file", path="public_tests/evil.py", content="x"),
            call(6, "run_public_tests"),
        ])
        assert [tool["name"] for tool in observed[1]["result"]["tools"]] == [
            "list_files", "read_file", "write_file", "run_public_tests"]
        assert all(observed[i]["result"]["isError"] for i in (2, 3, 4))
        synthetic = "\n".join(json.dumps(row) for row in (
            {"message": {"content": [{"type": "tool_use", "id": "deny", "name": "mcp__lab__read_file",
                                       "input": {"path": "/home/lab/.claude/sentinel"}}]}},
            {"message": {"content": [{"type": "tool_result", "tool_use_id": "deny",
                                       "content": observed[2]["result"]["content"]}]}}))
        history, workflow = agentic_dev._events(synthetic)
        assert workflow["reads"] == 1 and secret not in json.dumps(history)
        initial_test = observed[5]["result"]["content"][0]["text"]
        assert "exit_code=1" in initial_test and "failed" in initial_test
        assert not (workspace / "public_tests" / "evil.py").exists()
        starter_grade = agentic_dev._grade(config, workspace, root / "hidden_tests", tmp_path)
        assert not starter_grade["passed"] and starter_grade["tests"] > 0
        (tmp_path / "hidden_junit.xml").unlink()
        shutil.copytree(REFERENCE / task / task, workspace / "src" / task, dirs_exist_ok=True)
        final_test = rpc(config, ipc, secret, [call(7, "run_public_tests")])[0]
        assert "exit_code=0" in final_test["result"]["content"][0]["text"]
        final_grade = agentic_dev._grade(config, workspace, root / "hidden_tests", tmp_path)
        assert final_grade["passed"] and final_grade["tests"] > 0
    finally:
        agentic_dev._stop_container(config, worker)
        agentic_dev._remove_ipc(config, ipc)
        docker("volume", "rm", config.auth_volume)
