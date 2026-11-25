"""Run B27 with the existing isolated Claude CLI image; raw output stays in results/."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ai_lab import claude_cli, review_perspectives as rp
from ai_lab.experiment import check_model, price_trial


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OUT = ROOT / "results" / "hurry_phrase_20261125"
MODEL = "claude-haiku-5-5"
EFFORT = "medium"
PER_TRIAL_SECONDS = 60
TOTAL_SECONDS = 20 * 60
PER_TRIAL_CLI_BUDGET_USD = "0.01"
PREFIX = "整数だけで答えてください。"
EXTRA = "急いで答えて。"


def digest(data: bytes | str) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


def dump(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def cases() -> list[dict]:
    data = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))
    assert len(data) == 10
    assert len({row["id"] for row in data}) == 10
    assert all(type(row["answer"]) is int for row in data)
    return data


def schedule(rows: list[dict]) -> list[dict]:
    plan = []
    for row in rows:
        number = int(row["id"][1:])
        for repetition in (1, 2):
            first = "A" if (number + repetition) % 2 == 0 else "B"
            for condition in (first, "B" if first == "A" else "A"):
                plan.append({"case_id": row["id"], "repetition": repetition, "condition": condition})
    assert len(plan) == 40
    return plan


def prompt(row: dict, condition: str) -> str:
    result = row["question"] + "\n" + PREFIX
    if condition == "B":
        result += "\n" + EXTRA
    return result


def preflight(docker: str) -> dict:
    if shutil.which(docker) is None:
        raise RuntimeError("Docker executable unavailable")
    image = subprocess.run(
        [docker, "image", "inspect", rp.CLI_IMAGE, "--format", "{{.Id}}"],
        capture_output=True, text=True, timeout=30, check=True,
    ).stdout.strip()
    if image != rp.CLI_IMAGE:
        raise RuntimeError("pinned CLI image mismatch")
    volume = subprocess.run(
        [docker, "volume", "inspect", rp.AUTH_VOLUME, "--format", "{{.Name}}"],
        capture_output=True, text=True, timeout=30, check=True,
    ).stdout.strip()
    if volume != rp.AUTH_VOLUME:
        raise RuntimeError("isolated auth volume unavailable")
    auth = claude_cli.preflight(rp.cli_command(docker, None), claude_cli.child_environment(os.environ))
    return {"cli_image": image, "auth_volume": volume,
            "auth_method": auth["auth_method"], "cli_version": auth["version"]}


def args_for(one_prompt: str) -> list[str]:
    return [
        "-p", one_prompt, "--model", MODEL, "--effort", EFFORT,
        "--output-format", "stream-json", "--verbose", "--restricted", "--safe-mode",
        "--no-session-persistence", "--disable-slash-commands",
        "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
        "--tools", "", "--permission-mode", "dontAsk", "--permission-prompts", "none",
        "--max-turns", "1", "--max-budget-usd", PER_TRIAL_CLI_BUDGET_USD,
    ]


def run(docker: str) -> None:
    if OUT.exists():
        raise RuntimeError("Result directory already exists; refusing duplicate model attempts")
    rows = cases()
    plan = schedule(rows)
    check = preflight(docker)
    OUT.mkdir(parents=True)
    dump(OUT / "preflight.json", check)
    dump(OUT / "frozen.json", {
        "cases_sha256": digest((HERE / "cases.json").read_bytes()),
        "preregistration_sha256": digest((HERE / "preregistration.md").read_bytes()),
        "runner_sha256": digest(Path(__file__).read_bytes()),
        "model": MODEL, "effort": EFFORT, "schedule": plan,
        "per_trial_seconds": PER_TRIAL_SECONDS,
        "total_seconds": TOTAL_SECONDS,
        "per_trial_cli_budget_usd": PER_TRIAL_CLI_BUDGET_USD,
    })
    by_id = {row["id"]: row for row in rows}
    records = []
    started = time.perf_counter()
    consecutive_timeouts = 0
    stop_reason = None
    for index, item in enumerate(plan, 1):
        if time.perf_counter() - started >= TOTAL_SECONDS:
            stop_reason = "global_time_limit"
            break
        row = by_id[item["case_id"]]
        one_prompt = prompt(row, item["condition"])
        trial_dir = OUT / f"trial_{index:02d}"
        trial_dir.mkdir()
        (trial_dir / "prompt.txt").write_text(one_prompt, encoding="utf-8")
        result = claude_cli.invoke(
            rp.cli_command(docker, None), args_for(one_prompt), cwd=None,
            env=claude_cli.child_environment(os.environ), timeout=PER_TRIAL_SECONDS,
        )
        (trial_dir / "stream.jsonl").write_text(result.stdout, encoding="utf-8")
        (trial_dir / "stderr.txt").write_text(result.stderr, encoding="utf-8")
        cli = claude_cli.summarize_run(result)
        tokens, cost = price_trial(cli, MODEL)
        model_check = check_model(cli, MODEL)
        record = {
            **item, "trial": index, "prompt_sha256": digest(one_prompt),
            "status": cli["status"], "returncode": result.returncode,
            "wall_seconds": round(result.wall_seconds, 3),
            "cli_duration_ms": cli["duration_ms"],
            "session_sha256": digest(cli["session_id"]) if cli["session_id"] else None,
            "model_check": model_check,
            "tokens": tokens, "thinking_tokens": cli["thinking_tokens"],
            "cost": cost, "cli_reported_usd": cli["cli_total_cost_usd"],
            "result_text": cli["result_text"],
            "raw_sha256": digest(result.stdout),
        }
        records.append(record)
        dump(OUT / "progress.json", {"records": records, "stop_reason": None})
        print(json.dumps({"trial": index, "case": item["case_id"],
                          "condition": item["condition"], "status": record["status"],
                          "model": model_check["status"],
                          "seconds": record["wall_seconds"]}), flush=True)
        consecutive_timeouts = consecutive_timeouts + 1 if result.timed_out else 0
        if consecutive_timeouts >= 2:
            stop_reason = "two_consecutive_timeouts"
            break
        if model_check["status"] == "mismatch":
            stop_reason = "model_mismatch"
            break
        if cli["status"] == "error" and (
            "authentication" in (result.stdout + result.stderr).lower()
            or "oauth" in (result.stdout + result.stderr).lower()
        ):
            stop_reason = "authentication_error"
            break
    dump(OUT / "progress.json", {"records": records, "stop_reason": stop_reason,
                                 "planned": len(plan), "completed": len(records)})
    print(json.dumps({"completed": len(records), "planned": len(plan),
                      "stop_reason": stop_reason}), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("preflight", "run"))
    parser.add_argument("--docker", default="docker")
    opts = parser.parse_args()
    if opts.mode == "preflight":
        print(json.dumps(preflight(opts.docker), ensure_ascii=False))
    else:
        run(opts.docker)


if __name__ == "__main__":
    main()
