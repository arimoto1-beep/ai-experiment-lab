"""Run one frozen B45 phase in the existing isolated Docker CLI environment."""
import argparse
import json
import os
import subprocess
import sys
import time

from design import BUDGET, DEADLINE, EFFORT, HERE, MODEL, ROOT, TRIAL_SECONDS
from design import dump, fingerprints, prompt, read, schedule, select, sha

sys.path.insert(0, str(ROOT))
from ai_lab import claude_cli
from ai_lab.experiment import check_model, price_trial
from ai_lab import review_perspectives as rp

OUT = ROOT / "results" / "instruction_constraints_20261126"


def preflight(docker):
    for kind, value, field in (("image", rp.CLI_IMAGE, "Id"), ("volume", rp.AUTH_VOLUME, "Name")):
        output = subprocess.run([docker, kind, "inspect", value, "--format", "{{." + field + "}}"],
                                capture_output=True, text=True, check=True, timeout=30)
        if output.stdout.strip() != value:
            raise RuntimeError(f"Fixed Docker {kind} mismatch")
    auth = claude_cli.preflight(rp.cli_command(docker, None), claude_cli.child_environment(os.environ))
    if auth["auth_method"] != "claude.ai":
        raise RuntimeError("Expected claude.ai subscription authentication")
    return {"image": rp.CLI_IMAGE, "cli": auth["version"], "auth": auth["auth_method"],
            "model": MODEL, "effort": EFFORT}


def args_for(text):
    return ["-p", text, "--model", MODEL, "--effort", EFFORT,
            "--output-format", "stream-json", "--verbose", "--restricted", "--safe-mode",
            "--no-session-persistence", "--disable-slash-commands",
            "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--tools", "",
            "--permission-mode", "dontAsk", "--permission-prompts", "none",
            "--max-turns", "1", "--max-budget-usd", BUDGET]


def inspect(result):
    cli = claude_cli.summarize_run(result)
    tools = 0
    for line in result.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        tools += event.get("type") == "tool_use"
        message = event.get("message")
        blocks = message.get("content") if isinstance(message, dict) else None
        if isinstance(blocks, list):
            tools += sum(isinstance(b, dict) and b.get("type") == "tool_use" for b in blocks)
    model = check_model(cli, MODEL)
    tokens, cost = price_trial(cli, MODEL)
    session = cli["session_id"]
    normal = cli["status"] == "ok" and model["status"] == "match"
    return {
        "status": cli["status"], "model_check": model["status"],
        "valid": normal and bool(session) and tools == 0 and cli["permission_denials"] == 0,
        "response": cli["result_text"], "session_sha256": sha(session) if session else None,
        "tool_calls": tools, "permission_denials": cli["permission_denials"],
        "tokens": tokens, "thinking_tokens": cli["thinking_tokens"],
        "api_equivalent_usd": cost["api_equivalent_usd"], "cli_reported_usd": cli["cli_total_cost_usd"],
        "raw_sha256": sha(result.stdout), "wall_seconds": round(result.wall_seconds, 3),
        "returncode": result.returncode, "timeout": result.timed_out,
    }


def expected_lock():
    pilot = read(HERE / "pilot-runs.json")
    audit = read(HERE / "pilot-audit.json")
    selection = select(pilot, audit["stop_reason"])
    level = selection["level"]
    if level is None or audit["fingerprints"] != fingerprints():
        raise RuntimeError("Main design differs from the fixed pilot selection or no level is eligible")
    return {
        "selection": selection, "level": level, "model": MODEL, "effort": EFFORT,
        "schedule": schedule("main", read(HERE / "cases.json"), level),
        "trial_seconds": TRIAL_SECONDS, "phase_seconds": DEADLINE["main"], "trial_cli_budget_usd": BUDGET,
        "fingerprints": audit["fingerprints"],
        "pilot_runs_sha256": sha((HERE / "pilot-runs.json").read_text(encoding="utf-8")),
    }


def main_lock():
    lock = read(HERE / "main-lock.json")
    if lock != json.loads(json.dumps(expected_lock())):
        raise RuntimeError("Main lock does not match the fixed pilot selection")
    return lock


def run(phase, docker):
    dest = OUT / phase
    if dest.exists():
        raise RuntimeError("Phase directory already exists. Duplicate attempts are disabled.")
    cases = read(HERE / "cases.json")
    by_id = {c["id"]: c for c in cases[phase]}
    level = main_lock()["level"] if phase == "main" else None
    plan = schedule(phase, cases, level)
    check = preflight(docker)
    dest.mkdir(parents=True)
    dump(dest / "frozen.json", {"plan": plan, "fingerprints": fingerprints(), "preflight": check})
    command = rp.cli_command(docker, None)
    env = claude_cli.child_environment(os.environ)
    records, seen = [], set()
    started = time.monotonic()
    timeouts = 0
    reason = None
    for item in plan:
        if time.monotonic() - started >= DEADLINE[phase]:
            reason = "time_limit"
            break
        case = by_id[item["case"]]
        text = prompt(case, item["level"], item["condition"])
        result = claude_cli.invoke(command, args_for(text), cwd=None, env=env, timeout=TRIAL_SECONDS)
        trial = dest / f'trial_{item["trial"]:02}'
        trial.mkdir()
        for name, value in (("prompt.txt", text), ("stream.jsonl", result.stdout), ("stderr.txt", result.stderr)):
            (trial / name).write_text(value, encoding="utf-8", newline="\n")
        record = {**item, **inspect(result), "prompt_sha256": sha(text)}
        session = record["session_sha256"]
        if record["tool_calls"] or record["permission_denials"] or (session and session in seen):
            record["valid"] = False
            reason = "isolation"
        elif record["model_check"] == "mismatch":
            reason = "model_mismatch"
        elif record["status"] == "ok" and not session:
            reason = "session_missing"
        elif record["status"] == "error" and any(s in (result.stdout + result.stderr).lower()
                                                  for s in ("authentication", "oauth", "not logged in", "unauthorized")):
            reason = "authentication"
        timeouts = timeouts + 1 if result.timed_out else 0
        if timeouts >= 2 and reason is None:
            reason = "two_timeouts"
        seen.add(session)
        records.append(record)
        dump(dest / "progress.json", {"records": records, "stop_reason": reason, "finished": False})
        print(json.dumps({**item, "status": record["status"], "valid": record["valid"],
                          "seconds": record["wall_seconds"]}), flush=True)
        if reason:
            break
    dump(dest / "progress.json", {"records": records, "stop_reason": reason, "finished": True})
    print(json.dumps({"phase": phase, "attempted": len(records), "planned": len(plan), "stop_reason": reason}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("preflight", "pilot", "main"))
    parser.add_argument("--docker", default="docker")
    args = parser.parse_args()
    if args.phase == "preflight":
        print(json.dumps(preflight(args.docker)))
    else:
        run(args.phase, args.docker)
