"""実験の実行。

試行ごとに新しい作業ディレクトリ（starter/ のコピー）を作り、Claude Code CLI を1回呼び出して、
成果物（solution.py など）を隠しテストで評価し、結果を results/<実験名>/trial_NN/ に保存します。
試行どうしは作業ディレクトリも会話セッションも共有しません。
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from ai_lab import claude_cli
from ai_lab.evaluate import evaluate
from ai_lab.pricing import (
    DEFAULT_CACHE_WRITE_TTL,
    LONG_PROMPT_THRESHOLD_TOKENS,
    TokenCounts,
    cost_usd,
    price_key,
)
from ai_lab.problems import Problem, build_prompt, load_problem

EVAL_TIMEOUT_SECONDS = 120.0


@dataclass(frozen=True)
class ExperimentConfig:
    problem: str
    model_id: str
    model_label: str  # 結果ディレクトリ名に入れる短い名前（例: haiku）
    effort: str
    runs: int
    timeout: float
    results_dir: Path  # 絶対パスで渡すこと（pytest の junit 出力先は作業ディレクトリ基準になるため）
    problems_root: Path


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _int(value: Any) -> int:
    return int(value or 0)


def tokens_by_model(cli: dict[str, Any], requested_model_id: str) -> dict[str, TokenCounts]:
    """使用量をモデルごとに取り出す。modelUsage があればそれを使い、無ければ usage を要求したモデルに割り当てる。"""
    model_usage = cli.get("model_usage")
    if isinstance(model_usage, dict) and model_usage:
        return {
            name: TokenCounts(
                input=_int(entry.get("inputTokens")),
                output=_int(entry.get("outputTokens")),
                cache_read=_int(entry.get("cacheReadInputTokens")),
                cache_write=_int(entry.get("cacheCreationInputTokens")),
            )
            for name, entry in model_usage.items()
        }
    usage = cli.get("usage")
    if isinstance(usage, dict) and usage:
        return {
            requested_model_id: TokenCounts(
                input=_int(usage.get("input_tokens")),
                output=_int(usage.get("output_tokens")),
                cache_read=_int(usage.get("cache_read_input_tokens")),
                cache_write=_int(usage.get("cache_creation_input_tokens")),
            )
        }
    return {}


def price_trial(cli: dict[str, Any], requested_model_id: str) -> tuple[dict[str, int] | None, dict[str, Any]]:
    """1試行のトークン数と API 換算コストを求める。使用量が得られなければ (None, 計算不能の記録) を返す。"""
    per_model = tokens_by_model(cli, requested_model_id)
    if not per_model:
        return None, {
            "api_equivalent_usd": None,
            "complete": False,
            "cache_write_ttl_assumed": DEFAULT_CACHE_WRITE_TTL,
            "notes": ["使用量が取得できなかったため、コストは計算していません。"],
        }
    notes: list[str] = []
    complete = True
    priced = False
    total_cost = 0.0
    total = TokenCounts()
    turns = _int(cli.get("num_turns"))
    for name, tokens in per_model.items():
        total = total + tokens
        key = price_key(name)
        if key is None:
            complete = False
            notes.append(f"価格表にないモデルの使用量は含めていません: {name}")
            continue
        priced = True
        total_cost += cost_usd(key, tokens)
        threshold = LONG_PROMPT_THRESHOLD_TOKENS.get(key)
        if threshold and turns and tokens.prompt_tokens / turns > threshold:
            notes.append(
                f"{key}: 1ターンあたりの平均プロンプトが {threshold} トークンを超えています。"
                "高価格帯が適用された可能性があり、このコストは過小評価です。"
            )
    tokens_record = {
        "input": total.input,
        "output": total.output,
        "cache_read": total.cache_read,
        "cache_write": total.cache_write,
    }
    cost_record = {
        "api_equivalent_usd": round(total_cost, 6) if priced else None,
        "complete": complete,
        "cache_write_ttl_assumed": DEFAULT_CACHE_WRITE_TTL,
        "notes": notes,
    }
    return tokens_record, cost_record


def run_trial(
    index: int,
    exp_dir: Path,
    problem: Problem,
    config: ExperimentConfig,
    prompt: str,
    claude_command: list[str],
    env: dict[str, str],
) -> dict[str, Any]:
    trial_dir = exp_dir / f"trial_{index:02d}"
    workspace = trial_dir / "workspace"
    shutil.copytree(problem.starter_dir, workspace)

    started_at = _now()
    run = claude_cli.invoke(
        claude_command,
        claude_cli.build_args(config.model_id, config.effort, prompt),
        cwd=str(workspace),
        env=env,
        timeout=config.timeout,
    )
    (trial_dir / "claude_stdout.txt").write_text(run.stdout, encoding="utf-8")
    (trial_dir / "claude_stderr.txt").write_text(run.stderr, encoding="utf-8")
    cli = claude_cli.summarize_run(run)

    # CLI の状態にかかわらず、作業ディレクトリに残った成果物を評価する。
    evaluation = evaluate(
        workspace,
        problem.tests_path,
        output_path=trial_dir / "pytest_output.txt",
        junit_path=trial_dir / "junit.xml",
        timeout=EVAL_TIMEOUT_SECONDS,
    )
    tokens, cost = price_trial(cli, config.model_id)
    record = {
        "trial": index,
        "outcome": "pass" if evaluation.passed else "fail",
        "started_at": started_at,
        "finished_at": _now(),
        "wall_seconds": round(run.wall_seconds, 3),
        "claude": cli,
        "evaluation": asdict(evaluation),
        "tokens": tokens,
        "cost": cost,
    }
    _write_json(trial_dir / "trial.json", record)
    return record


def summarize(trials: list[dict[str, Any]], meta: dict[str, Any]) -> dict[str, Any]:
    completed = len(trials)
    passed = sum(1 for trial in trials if trial["outcome"] == "pass")
    priced = [t["cost"]["api_equivalent_usd"] for t in trials if t["cost"]["api_equivalent_usd"] is not None]
    usd_total = round(sum(priced), 6) if priced else None
    cli_costs = [t["claude"]["cli_total_cost_usd"] for t in trials if t["claude"]["cli_total_cost_usd"] is not None]
    token_totals = {
        key: sum(t["tokens"][key] for t in trials if t["tokens"])
        for key in ("input", "output", "cache_read", "cache_write")
    }
    return {
        "problem": meta["problem"],
        "model": meta["model"],
        "effort": meta["effort"],
        "requested_runs": meta["runs"],
        "completed_runs": completed,
        "passed": passed,
        "pass_rate": round(passed / completed, 4) if completed else None,
        "any_passed": passed > 0,
        "cli_not_ok": sum(1 for t in trials if t["claude"]["status"] != "ok"),
        "mean_wall_seconds": round(sum(t["wall_seconds"] for t in trials) / completed, 3) if completed else None,
        "tokens": token_totals,
        "api_equivalent_usd_total": usd_total,
        "api_equivalent_usd_per_pass": round(usd_total / passed, 6) if (usd_total is not None and passed) else None,
        "cost_complete": all(t["cost"]["complete"] for t in trials),
        "cli_reported_usd_total": round(sum(cli_costs), 6) if cli_costs else None,
        "updated_at": _now(),
    }


def _new_experiment_dir(config: ExperimentConfig) -> Path:
    config.results_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = config.results_dir / f"{stamp}_{config.problem}_{config.model_label}_{config.effort}_x{config.runs}"
    path.mkdir()
    return path


def run_experiment(
    config: ExperimentConfig,
    claude_command: list[str],
    log: Callable[[str], None] = print,
) -> Path:
    problem = load_problem(config.problem, config.problems_root)
    prompt = build_prompt(problem)
    env = claude_cli.child_environment(os.environ)
    # 認証を確認してから結果ディレクトリを作る。サブスクリプションでなければ RuntimeError で止まる。
    preflight = claude_cli.preflight(claude_command, env)
    exp_dir = _new_experiment_dir(config)
    meta = {
        "problem": config.problem,
        "model": config.model_id,
        "effort": config.effort,
        "runs": config.runs,
        "timeout_seconds": config.timeout,
        "max_turns": claude_cli.MAX_TURNS,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "claude_command": claude_command,
        "claude_version": preflight["version"],
        "auth_method": preflight["auth_method"],
        "started_at": _now(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
    }
    _write_json(exp_dir / "experiment.json", meta)
    log(f"結果の保存先: {exp_dir}")

    trials: list[dict[str, Any]] = []
    for index in range(1, config.runs + 1):
        log(f"[{index}/{config.runs}] 試行を開始（{config.model_id}, effort={config.effort}）")
        record = run_trial(index, exp_dir, problem, config, prompt, claude_command, env)
        trials.append(record)
        log(
            f"[{index}/{config.runs}] 結果={record['outcome']} / CLI={record['claude']['status']} / "
            f"{record['wall_seconds']} 秒"
        )
        # 途中で止まっても、そこまでの結果が残るように毎回集計を書き直す。
        _write_json(exp_dir / "summary.json", summarize(trials, meta))
    return exp_dir
