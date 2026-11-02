"""Single-task Harbor adapter for Terminal-Bench v4 react-lead-form.

The host-side Harbor agent has Docker access. The task container has neither
Docker access nor Claude credentials; the CLI container receives only auth and
IPC volumes. No model call is made in dummy mode.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import secrets
import subprocess
import sys
import uuid
from pathlib import Path

from harbor.agents.base import BaseAgent
from harbor.agents.capabilities import AgentCapabilities
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext
from harbor.verifier.verifier import Verifier
from harbor.environments.docker.docker import _sanitize_docker_compose_project_name


ROOT = Path(__file__).resolve().parent.parent
TASK = ROOT / "analysis" / "terminal-bench-v4.0.0" / "tasks" / "react-lead-form"
WORKER = ROOT / "benchmarks" / "react_lead_form_adapter" / "mcp_worker.mjs"
CLI_IMAGE = "ai-lab-agent:1"
CLI_IMAGE_ID = "sha256:02ddedacf8dc79f1402df822f09699fc3be6d18bd93e0140b4d18b39fa57806b"
AUTH_SEED_IMAGE = "tb4-react-lead-form-env:v4.0.0"
MODEL_OPTIONS = {("claude-haiku-4-5", "default"), ("claude-haiku-5-5", "medium")}
MAX_TURNS = 100


DUMMY_CLIENT = r'''
import json, os, subprocess, sys
assert os.path.isfile('/home/lab/.claude/dummy-marker')
assert not os.path.exists('/app/src')
assert not os.path.exists('/var/run/docker.sock')
p = subprocess.Popen(['python', '/opt/ai-lab/mcp_bridge.py'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
seq = 0
def request(method, params=None):
    global seq
    seq += 1
    p.stdin.write(json.dumps({'jsonrpc':'2.0','id':seq,'method':method,'params':params or {}})+'\n')
    p.stdin.flush()
    line = p.stdout.readline()
    if not line: raise RuntimeError('MCP bridge closed')
    data = json.loads(line)
    assert data['id'] == seq and 'result' in data, data
    return data['result']
request('initialize', {'protocolVersion':'2025-03-26'})
names = {tool['name'] for tool in request('tools/list')['tools']}
review = 'submit_review' in names
assert names == ({'list_files','read_file','write_file','run_command','submit_review'} if review else {'list_files','read_file','write_file','run_command'}), names
def call(name, args): return request('tools/call', {'name':name,'arguments':args})
assert not call('list_files', {})['isError']
source = call('read_file', {'path':'src/lib/validation.ts'})
assert not source['isError']
original = source['content'][0]['text']
if review:
    assert call('write_file', {'path':'src/lib/validation.ts','content':original})['isError']
    assert call('run_command', {'command':'npm test'})['isError']
    assert not call('submit_review', {'report':'Dummy review gate probe; no model used.'})['isError']
assert not call('write_file', {'path':'src/lib/validation.ts','content':original+'\n// Harbor dummy adapter probe.\n'})['isError']
denials = [
    call('read_file', {'path':'/home/lab/.claude/dummy-marker'}),
    call('write_file', {'path':'src/data/lead_input.json','content':'{}'}),
    call('write_file', {'path':'src/spec/lead_schema.json','content':'{}'}),
    call('write_file', {'path':'tests/test.sh','content':'echo cheat'}),
    call('write_file', {'path':'../../host.txt','content':'cheat'}),
    call('run_command', {'command':'sh -c id'}),
]
assert all(item['isError'] for item in denials), denials
commands = {}
for command in ('npm test','npm run build','npm run submit'):
    result = call('run_command', {'command':command})
    assert not result['isError']
    commands[command] = result['content'][0]['text'].splitlines()[0]
p.stdin.close()
p.wait(timeout=5)
print(json.dumps({'tools':sorted(names),'forbidden_rejected':len(denials),'commands':commands,'source_edited':True}))
'''


def _clean_env() -> dict[str, str]:
    """Do not let host credentials or Docker config reach Harbor by inheritance."""
    return {key: value for key, value in os.environ.items()
            if not any(part in key.upper() for part in
                       ("ANTHROPIC", "CLAUDE", "API_KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL"))}


class ReactLeadFormAgent(BaseAgent):
    """Host-side agent for exactly one pinned task; no generic shell proxy."""

    capabilities = AgentCapabilities(windows=True)

    @staticmethod
    def name() -> str:
        return "react-lead-form-isolated"

    def version(self) -> str:
        return "0.1.0"

    async def setup(self, environment: BaseEnvironment) -> None:
        restored = os.environ.get("RLFM_RESTORE_APP")
        if restored:
            source_root = Path(restored)
            for source in sorted((source_root / "src").rglob("*")):
                if not source.is_file() or source.suffix not in (".ts", ".tsx"):
                    continue
                relative = source.relative_to(source_root).as_posix()
                await environment.upload_file(source, "/app/" + relative)
                actual = await environment.exec("sha256sum /app/" + relative)
                expected = hashlib.sha256(source.read_bytes()).hexdigest()
                if actual.return_code != 0 or actual.stdout.split()[0] != expected:
                    raise RuntimeError("restored source hash mismatch: " + relative)
        await environment.upload_file(WORKER, "/tmp/rlfm_mcp_worker.mjs")
        started = await environment.exec(
            "sh -c 'node /tmp/rlfm_mcp_worker.mjs >/tmp/rlfm-worker.log 2>&1 </dev/null &'")
        if started.return_code != 0:
            raise RuntimeError("MCP worker failed to start")
        for _ in range(50):
            ready = await environment.exec("test -S /ipc/mcp.sock")
            if ready.return_code == 0:
                return
            await asyncio.sleep(0.1)
        raise RuntimeError("MCP worker socket not ready")

    async def run(self, instruction: str, environment: BaseEnvironment,
                  context: AgentContext) -> None:
        mode = os.environ.get("RLFM_MODE", "dummy")
        if mode not in ("dummy", "claude"):
            raise RuntimeError("invalid adapter mode")
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        ipc = os.environ["RLFM_IPC_VOLUME"]
        auth = os.environ["RLFM_AUTH_VOLUME"]
        docker = os.environ.get("RLFM_DOCKER", "docker")
        container = "rlfm-cli-" + uuid.uuid4().hex[:12]
        security = await environment.exec(
            "node -e \"const f=require('fs');const n=require('net');"
            "const bad=Object.keys(process.env).filter(k=>/ANTHROPIC|CLAUDE|API_KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL/i.test(k));"
            "const socket=f.existsSync('/var/run/docker.sock')||f.existsSync('/run/docker.sock');"
            "const auth=f.existsSync('/home/lab/.claude/dummy-marker');"
            "const protectedWritable=['/app/src/data/lead_input.json','/app/src/spec/lead_schema.json','/app/package.json'].filter(p=>{try{const fd=f.openSync(p,'r+');f.closeSync(fd);return true}catch{return false}});"
            "const c=n.connect({host:'1.1.1.1',port:443,timeout:2000});"
            "c.on('connect',()=>{console.log(JSON.stringify({bad,socket,auth,protectedWritable,network:'reachable'}));c.destroy()});"
            "c.on('error',()=>console.log(JSON.stringify({bad,socket,auth,protectedWritable,network:'blocked'})));"
            "c.on('timeout',()=>{console.log(JSON.stringify({bad,socket,auth,protectedWritable,network:'timeout'}));c.destroy()})\"",
            timeout_sec=10,
        )
        if security.return_code != 0:
            raise RuntimeError("task security probe failed")
        (self.logs_dir / "security-probe.json").write_text(security.stdout or "", encoding="utf-8")
        probe = json.loads((security.stdout or "").strip())
        if probe["bad"] or probe["socket"] or probe["auth"] or probe["protectedWritable"] or probe["network"] != "blocked":
            raise RuntimeError("task security boundary failed")

        cmd = [docker, "run", "--rm", "--name", container,
               "--user", "1000:1000", "--read-only", "--cap-drop", "ALL",
               "--security-opt", "no-new-privileges", "--pids-limit", "256",
               "--cpus", "2", "--memory", "4g", "--memory-swap", "4g",
               "--tmpfs", "/tmp:rw,nosuid,size=256m",
               "--tmpfs", "/home/lab/.cache:rw,nosuid,size=128m",
               "--network", "bridge",
               "--mount", f"type=volume,source={ipc},target=/ipc",
               "--mount", f"type=volume,source={auth},target=/home/lab/.claude",
               CLI_IMAGE_ID]
        if mode == "dummy":
            cmd += ["python", "-c", DUMMY_CLIENT]
        else:
            model = os.environ.get("RLFM_MODEL", "")
            effort = os.environ.get("RLFM_EFFORT", "")
            if (model, effort) not in MODEL_OPTIONS or os.environ.get("RLFM_ENABLE_MODEL") != "explicit":
                raise RuntimeError("model execution requires a supported model/effort and explicit enable flag")
            mcp = {"mcpServers": {"lab": {"command": "python", "args": ["/opt/ai-lab/mcp_bridge.py"]}}}
            if os.environ.get("RLFM_RESTORE_APP"):
                instruction += ("\n\nFirst review this program against the task specification. "
                                "Do not change code or run development commands yet. "
                                "Report each problem with its location, triggering condition, and reason; "
                                "if you find none, say so. Submit the complete review using "
                                "mcp__lab__submit_review. Once the tool confirms host-side preservation, "
                                "continue in the same session and fix the problems you found. "
                                "Use only the allowed file and development-command tools.")
                (self.logs_dir / "review-instruction.txt").write_text(instruction, encoding="utf-8")
            cmd += ["claude", "-p", instruction, "--model", model,
                    *([] if effort == "default" else ["--effort", effort]),
                    "--output-format", "stream-json", "--verbose",
                    "--restricted", "--no-session-persistence", "--disable-slash-commands",
                    "--strict-mcp-config", "--mcp-config", json.dumps(mcp),
                    "--tools", "", "--permission-mode", "dontAsk",
                    "--permission-prompts", "none",
                    "--allowedTools", "mcp__lab__list_files,mcp__lab__read_file,mcp__lab__write_file,mcp__lab__run_command"
                    + (",mcp__lab__submit_review" if os.environ.get("RLFM_RESTORE_APP") else ""),
                    "--max-turns", str(MAX_TURNS)]
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                env=_clean_env())
            communication = asyncio.create_task(process.communicate())
            if os.environ.get("RLFM_RESTORE_APP"):
                reviewed = False
                while not communication.done():
                    present = await environment.exec("test -s /tmp/rlfm-review-report.json")
                    if present.return_code == 0:
                        report_path = self.logs_dir / "first-review.json"
                        await environment.download_file("/tmp/rlfm-review-report.json", report_path)
                        report = json.loads(report_path.read_text(encoding="utf-8"))
                        if not isinstance(report.get("report"), str) or not report["report"].strip():
                            raise RuntimeError("empty first review")
                        ack = await environment.exec("touch /ipc/rlfm-review-ack")
                        if ack.return_code != 0:
                            raise RuntimeError("cannot acknowledge preserved review")
                        reviewed = True
                        break
                    await asyncio.sleep(1)
                stdout, stderr = await communication
                if not reviewed:
                    raise RuntimeError("review session ended without a preserved first review")
            else:
                stdout, stderr = await communication
            (self.logs_dir / "cli-stdout.jsonl").write_bytes(stdout)
            (self.logs_dir / "cli-stderr.txt").write_bytes(stderr)
            if mode == "claude":
                from ai_lab.agentic_dev import _events
                events, workflow = _events(stdout.decode("utf-8", errors="replace"))
                (self.logs_dir / "history.json").write_text(
                    json.dumps({"events": events, "workflow": workflow}, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
            if process.returncode != 0:
                raise RuntimeError(f"isolated CLI exited {process.returncode}")
        finally:
            await asyncio.to_thread(subprocess.run, [docker, "rm", "-f", container],
                                    capture_output=True, check=False)
            try:
                await environment.download_file("/tmp/rlfm-operations.jsonl",
                                                self.logs_dir / "worker-operations.jsonl")
            except Exception:
                pass
        if mode == "dummy":
            data = json.loads(stdout.decode("utf-8").strip())
            if not data.get("source_edited") or data.get("forbidden_rejected") != 6:
                raise RuntimeError("dummy assertions incomplete")


class NetworkIsolatedOfficialVerifier(Verifier):
    """Run the official verifier unchanged after disconnecting its Docker network."""

    async def verify(self):
        docker = os.environ.get("RLFM_DOCKER", "docker")
        project = _sanitize_docker_compose_project_name(self.environment.session_id)
        query = await asyncio.to_thread(
            subprocess.run,
            [docker, "ps", "-q", "--filter", f"label=com.docker.compose.project={project}",
             "--filter", "label=com.docker.compose.service=main"],
            capture_output=True, text=True, check=False)
        ids = query.stdout.split()
        if query.returncode != 0 or len(ids) != 1:
            raise RuntimeError("cannot identify separate verifier container")
        container = ids[0]

        def networks() -> dict:
            inspected = subprocess.run(
                [docker, "inspect", container, "--format", "{{json .NetworkSettings.Networks}}"],
                capture_output=True, text=True, check=True)
            return json.loads(inspected.stdout)

        for network in (await asyncio.to_thread(networks)):
            disconnected = await asyncio.to_thread(
                subprocess.run, [docker, "network", "disconnect", "--force", network, container],
                capture_output=True, text=True, check=False)
            if disconnected.returncode != 0:
                raise RuntimeError("cannot isolate verifier network")
        if await asyncio.to_thread(networks):
            raise RuntimeError("verifier still has a Docker network")
        probe = await self.environment.exec(
            "node -e \"const f=require('fs');const n=require('net');"
            "const socket=f.existsSync('/var/run/docker.sock')||f.existsSync('/run/docker.sock');"
            "const auth=f.existsSync('/home/lab/.claude/dummy-marker');"
            "const bad=Object.keys(process.env).filter(k=>/ANTHROPIC|CLAUDE|API_KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL/i.test(k));"
            "const c=n.connect({host:'1.1.1.1',port:443,timeout:2000});"
            "c.on('connect',()=>{console.log(JSON.stringify({socket,auth,bad,network:'reachable'}));c.destroy()});"
            "c.on('error',()=>console.log(JSON.stringify({socket,auth,bad,network:'blocked'})));"
            "c.on('timeout',()=>{console.log(JSON.stringify({socket,auth,bad,network:'timeout'}));c.destroy()})\"",
            timeout_sec=10)
        if probe.return_code != 0:
            raise RuntimeError("verifier security probe failed")
        report = json.loads((probe.stdout or "").strip())
        self.trial_paths.verifier_dir.mkdir(parents=True, exist_ok=True)
        (self.trial_paths.verifier_dir / "security-probe.json").write_text(
            json.dumps(report) + "\n", encoding="utf-8")
        if report["socket"] or report["auth"] or report["bad"] or report["network"] != "blocked":
            raise RuntimeError("verifier security boundary failed")
        return await super().verify()


def _run_checked(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, check=True, **kwargs)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one isolated Harbor react-lead-form trial")
    parser.add_argument("--mode", choices=("dummy", "claude"), default="dummy")
    parser.add_argument("--model", choices=("claude-haiku-4-5", "claude-haiku-5-5"))
    parser.add_argument("--effort", choices=("default", "medium"))
    parser.add_argument("--enable-model", action="store_true")
    parser.add_argument("--auth-volume", help="Existing CLI-only Claude volume; required for model mode")
    parser.add_argument("--review-source", choices=("rlfm-1170a1288c0a", "rlfm-0df740e1d9e8", "rlfm-ea7769669b72"),
                        help="Restore one saved #7 Haiku 5.5 artifact for a two-stage review")
    args = parser.parse_args()
    if args.mode == "claude" and (not args.enable_model or not args.auth_volume or (args.model, args.effort) not in MODEL_OPTIONS):
        parser.error("model mode requires --enable-model, --auth-volume and a supported model/effort pair")
    if args.mode == "dummy" and (args.model or args.effort or args.enable_model or args.auth_volume):
        parser.error("dummy mode does not accept model options")
    if args.review_source and args.mode == "claude" and (args.model, args.effort) != ("claude-haiku-5-5", "medium"):
        parser.error("review source requires Haiku 5.5 medium model mode")
    restored = ROOT / "analysis" / "react-lead-form-review-20261102" / args.review_source / "app" if args.review_source else None
    if restored and not restored.is_dir():
        parser.error("restored source unavailable")
    if restored:
        manifest = json.loads((restored.parent.parent / "restore-manifest.json").read_text(encoding="utf-8"))
        entry = next((item for item in manifest["restorations"]
                      if item["source_run_id"] == args.review_source), None)
        if entry is None or not entry["all_files_match_saved_artifact"]:
            parser.error("saved final artifact manifest unavailable")
        patch = ROOT / "analysis" / "react-lead-form-replication-20261031" / "patches" / (args.review_source + ".patch")
        if hashlib.sha256(patch.read_bytes()).hexdigest() != entry["source_patch_sha256"]:
            parser.error("saved source patch hash mismatch")
        expected = {Path(item["path"]): item["sha256"] for item in entry["files"]}
        actual = {p.relative_to(restored): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in restored.rglob("*") if p.is_file()}
        if actual != expected or len(actual) != entry["file_count"]:
            parser.error("restored source no longer matches saved final artifact hashes")
    if not TASK.exists() or not WORKER.exists():
        parser.error("pinned task or MCP worker unavailable")
    docker = os.environ.get("RLFM_DOCKER", "docker")
    harbor = Path(sys.executable).with_name("harbor.exe")
    if not harbor.exists():
        parser.error("Harbor 0.25.0 executable not found in this Python environment")
    from importlib.metadata import version
    if version("harbor") != "0.25.0":
        parser.error("this adapter requires Harbor 0.25.0")
    image_id = _run_checked([docker, "image", "inspect", CLI_IMAGE, "--format", "{{.Id}}"],
                            capture_output=True).stdout.strip()
    if image_id != CLI_IMAGE_ID:
        parser.error("#6 CLI image ID changed; revalidate isolation before running")
    commit = _run_checked(["git", "-C", str(TASK.parents[1]), "rev-parse", "HEAD"], capture_output=True).stdout.strip()
    if commit != "452bf305c6daa62fc59061d22133a7cbc7c1572e":
        parser.error("Terminal-Bench checkout is not v4.0.0")
    tracked = _run_checked(["git", "-C", str(TASK.parents[1]), "ls-files", "-z", "tasks/react-lead-form"],
                           capture_output=True).stdout.split("\0")
    if len([name for name in tracked if name]) != 40:
        parser.error("pinned task file count changed")
    for name in tracked:
        if name:
            original = subprocess.check_output(["git", "-C", str(TASK.parents[1]), "show", "HEAD:" + name])
            if (TASK.parents[1] / name).read_bytes() != original:
                parser.error("pinned task contents changed: " + name)
    run_id = "rlfm-" + uuid.uuid4().hex[:12]
    root = ROOT / "results" / "react_lead_form_harbor" / run_id
    root.mkdir(parents=True)
    (root / "adapter-metadata.json").write_text(json.dumps({
        "run_id": run_id, "mode": args.mode, "model": args.model, "effort": args.effort,
        "terminal_bench_commit": commit, "harbor_version": "0.25.0",
        "cli_image_id": CLI_IMAGE_ID,
        "worker_sha256": hashlib.sha256(WORKER.read_bytes()).hexdigest(),
        "task_files_verified": 40,
        "agent_timeout_sec": 28800, "verifier_timeout_sec": 900,
        "max_turns": MAX_TURNS,
        "review_source": args.review_source,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ipc = run_id + "-ipc"
    auth = run_id + "-dummy-auth" if args.mode == "dummy" else args.auth_volume
    overlay = root / "agent-compose.yaml"
    readonly = [
        (TASK / "environment" / "app" / "src" / "spec", "/app/src/spec"),
        (TASK / "environment" / "app" / "src" / "data", "/app/src/data"),
        *[(TASK / "environment" / "app" / filename, f"/app/{filename}")
          for filename in ("package.json", "package-lock.json", "index.html", "tsconfig.json", "vite.config.ts")],
    ]
    mounts = "".join(
        f"      - type: bind\n        source: {json.dumps(str(source))}\n"
        f"        target: {target}\n        read_only: true\n"
        for source, target in readonly
    )
    overlay.write_text(
        f"services:\n  main:\n    network_mode: none\n"
        + ("    environment:\n      RLFM_REVIEW_MODE: '1'\n" if restored else "")
        + "    volumes:\n"
        f"      - type: volume\n        source: trial_ipc\n        target: /ipc\n"
        + mounts +
        f"volumes:\n  trial_ipc:\n    external: true\n    name: {ipc}\n", encoding="utf-8")
    env = _clean_env()
    env.update({"RLFM_MODE": args.mode, "RLFM_IPC_VOLUME": ipc,
                "RLFM_AUTH_VOLUME": auth, "RLFM_DOCKER": docker,
                "PYTHONPATH": str(ROOT), "PYTHONUTF8": "1"})
    if args.mode == "claude":
        env.update({"RLFM_MODEL": args.model, "RLFM_EFFORT": args.effort,
                    "RLFM_ENABLE_MODEL": "explicit"})
    if restored:
        env["RLFM_RESTORE_APP"] = str(restored)
    _run_checked([docker, "volume", "create", ipc], capture_output=True, env=env)
    try:
        if args.mode == "dummy":
            _run_checked([docker, "volume", "create", auth], capture_output=True, env=env)
            marker = secrets.token_hex(24)
            _run_checked([docker, "run", "--rm", "--pull=never", "--mount", f"type=volume,source={auth},target=/auth",
                          AUTH_SEED_IMAGE, "sh", "-c",
                          f"printf %s {marker} > /auth/dummy-marker && chown 1000:1000 /auth/dummy-marker"],
                         capture_output=True, env=env)
        command = [str(harbor), "run", "-p", str(TASK),
                   "-a", "ai_lab.react_lead_form_harbor:ReactLeadFormAgent",
                   "--verifier", "ai_lab.react_lead_form_harbor:NetworkIsolatedOfficialVerifier",
                   "-e", "docker", "-k", "1", "-n", "1", "-o", str(root / "jobs"),
                   "--job-name", run_id, "--extra-docker-compose", str(overlay), "--yes"]
        result = subprocess.run(command, text=True, capture_output=True, env=env)
        (root / "harbor-stdout.txt").write_text(result.stdout, encoding="utf-8")
        (root / "harbor-stderr.txt").write_text(result.stderr, encoding="utf-8")
        if result.returncode == 0:
            from ai_lab.react_lead_form_analysis import analyze_job
            analyze_job(root / "jobs" / run_id)
        print(json.dumps({"run_id": run_id, "directory": str(root), "harbor_exit": result.returncode}))
        if result.returncode != 0:
            print(result.stderr[-2000:], file=sys.stderr)
            raise SystemExit(result.returncode)
    finally:
        subprocess.run([docker, "volume", "rm", "-f", ipc], capture_output=True, env=env)
        if args.mode == "dummy":
            subprocess.run([docker, "volume", "rm", "-f", auth], capture_output=True, env=env)


if __name__ == "__main__":
    main()
