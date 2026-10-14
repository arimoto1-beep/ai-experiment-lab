"""仕様書の矛盾検出専用の小さな実行・レポートCLI。コード課題のpytest採点は使わない。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from ai_lab import claude_cli
from ai_lab.cli import EFFORT_LEVELS, _resolve_model
from ai_lab.experiment import _now, _write_json, check_model, price_trial
from ai_lab.pricing import PRICES_PER_MTOK, PRICING_CHECKED_ON, PRICING_SOURCE_URL
from ai_lab.problems import PROJECT_ROOT
from ai_lab.report import _cell, _table
from ai_lab.spec_scoring import ALL_SPEC_NAMES, PROMPT_VARIANTS, SPEC_SETS, SpecCase, build_prompt, load_spec, metrics, score_response


def build_args(model_id: str, effort: str, prompt: str) -> list[str]:
    args = claude_cli.build_args(model_id, effort, prompt)
    args[args.index("--tools") + 1] = ""
    # --tools だけではMCPツールを消せないため、MCPも明示的に拒否する。
    args.extend(["--disallowedTools", "*"])
    return args


def summarize(trials: list[dict[str, Any]]) -> dict[str, Any]:
    totals = {key: sum(t["scoring"]["metrics"][key] for t in trials) for key in ("tp", "fp", "fn")}
    summary = metrics(**totals)
    count = len(trials)
    costs = [t["cost"]["api_equivalent_usd"] for t in trials if t["cost"]["api_equivalent_usd"] is not None]
    complete = all(t["cost"]["complete"] for t in trials)
    thinking = [t["claude"].get("thinking_tokens") for t in trials]
    summary.update({
        "completed_trials": count,
        "invalid_responses": sum(t["scoring"]["status"] != "ok" for t in trials),
        "missed_critical": sum(t["scoring"]["missed_critical"] for t in trials),
        "mean_f1": sum(t["scoring"]["metrics"]["f1"] for t in trials) / count if count else None,
        "mean_wall_seconds": sum(t["wall_seconds"] for t in trials) / count if count else None,
        "api_equivalent_usd_total": round(sum(costs), 6) if costs else None,
        "api_equivalent_usd_mean": round(sum(costs) / count, 6) if count and complete and len(costs) == count else None,
        "cost_complete": complete,
        "cli_reported_usd_total": sum(t["claude"]["cli_total_cost_usd"] or 0 for t in trials)
            if any(t["claude"]["cli_total_cost_usd"] is not None for t in trials) else None,
        "tokens": {key: sum((t["tokens"] or {}).get(key, 0) for t in trials) for key in ("input", "output", "cache_read", "cache_write")},
        "model_mismatch_trials": sum(t["model_check"]["status"] == "mismatch" for t in trials),
        "model_unverified_trials": sum(t["model_check"]["status"] == "unverified" for t in trials),
        "actual_model_ids": sorted({name for t in trials for name in t["model_check"]["actual_model_ids"]}),
        "thinking_tokens": sum(thinking) if count and all(value is not None for value in thinking) else None,
    })
    return summary


def run_benchmark(
    cases: list[SpecCase], *, model_id: str, model_label: str, effort: str, runs: int,
    timeout: float, results_dir: Path, claude_command: list[str], prompt_variant: str = "baseline",
    log: Callable[[str], None] = print,
) -> Path:
    if not cases or runs < 1 or timeout <= 0:
        raise ValueError("仕様書、1以上の試行回数、正のタイムアウトが必要です")
    effort = claude_cli.resolve_effort(model_id, effort)
    reason = claude_cli.nested_run_reason(os.environ)
    if reason:
        raise RuntimeError(f"入れ子実行は拒否します（{reason}）。独立したターミナルで実行してください。")
    prompts = {case.name: build_prompt(case, prompt_variant) for case in cases}
    env = claude_cli.child_environment(os.environ)
    preflight = claude_cli.preflight(claude_command, env)
    results_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    exp_dir = Path(tempfile.mkdtemp(prefix=f"{stamp}_spec_{model_label}_{effort}_{prompt_variant}_x{runs}_", dir=results_dir))
    # 以後はロード済みの本文と正解を使い続ける。原本の再読込や書換えは行わない。
    meta = {
        "benchmark": "spec_contradictions", "dataset_version": 1,
        "model": model_id, "effort": effort, "comparison_basis": "model_and_effort",
        "prompt_variant": prompt_variant,
        "runs_per_spec": runs, "requested_trials": len(cases) * runs,
        "specs": [case.name for case in cases], "timeout_seconds": timeout,
        "spec_sets": {case.name: case.dataset_set for case in cases},
        "started_at": _now(), "claude_version": preflight["version"], "auth_method": preflight["auth_method"],
        "pricing_source": PRICING_SOURCE_URL, "pricing_checked_on": PRICING_CHECKED_ON,
        "rates_per_mtok": PRICES_PER_MTOK,
        "input_hashes": {case.name: case.hashes for case in cases},
        "prompt_sha256": {name: hashlib.sha256(prompt.encode("utf-8")).hexdigest() for name, prompt in prompts.items()},
        "tool_policy": "no_builtin_or_mcp_tools",
    }
    if effort == "default":
        meta["reasoning_settings"] = {
            "mode": "cli_default", "effort_flag": None, "thinking_budget_override": None,
            "effective_thinking_budget": None,
            "environment": {name: env.get(name) for name in (
                "MAX_THINKING_TOKENS", "CLAUDE_CODE_EFFORT_LEVEL", "CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING",
            )},
        }
    _write_json(exp_dir / "experiment.json", meta)
    snapshots = exp_dir / "snapshots"
    snapshots.mkdir()
    for case in cases:
        # 元のJSON書式とLF改行を保ち、スナップショットも固定ハッシュと一致させる。
        (snapshots / f"{case.name}.md").write_bytes(case.statement.encode("utf-8"))
        (snapshots / f"{case.name}.answer_key.json").write_bytes(case.answer_key_text.encode("utf-8"))
    log(f"結果の保存先: {exp_dir}")
    trials = []
    for case in cases:
        prompt = prompts[case.name]
        for index in range(1, runs + 1):
            trial_dir = exp_dir / f"trial_{len(trials) + 1:03d}"
            trial_dir.mkdir()
            started_at = _now()
            # 採点結果や正解スナップショットのある場所を作業ディレクトリにしない。
            with tempfile.TemporaryDirectory(prefix="ai-lab-spec-") as isolated:
                run = claude_cli.invoke(claude_command, build_args(model_id, effort, prompt), cwd=isolated, env=env, timeout=timeout)
            (trial_dir / "claude_stdout.txt").write_text(run.stdout, encoding="utf-8")
            (trial_dir / "claude_stderr.txt").write_text(run.stderr, encoding="utf-8")
            cli = claude_cli.summarize_run(run)
            response = cli.get("result_text")
            (trial_dir / "answer.txt").write_text(response if isinstance(response, str) else "", encoding="utf-8")
            failure = f"CLI status={cli['status']}" if cli["status"] != "ok" else None
            scoring = score_response(response, case, execution_error=failure)
            tokens, cost = price_trial(cli, model_id)
            record = {
                "spec": case.name, "trial": index, "model": model_id, "effort": effort,
                "dataset_set": case.dataset_set,
                "prompt_variant": prompt_variant,
                "model_check": check_model(cli, model_id),
                "started_at": started_at, "finished_at": _now(), "wall_seconds": round(run.wall_seconds, 3),
                "claude": cli, "tokens": tokens, "cost": cost, "scoring": scoring,
            }
            if "reasoning_settings" in meta:
                record["reasoning_settings"] = meta["reasoning_settings"]
            _write_json(trial_dir / "trial.json", record)
            _write_json(trial_dir / "reason_review.json", {"contradictions": scoring["reason_review"], "insufficient_information": scoring["information_findings"]})
            trials.append(record)
            summary = {**meta, **summarize(trials), "by_spec": {
                item.name: summarize([trial for trial in trials if trial["spec"] == item.name])
                for item in cases if any(trial["spec"] == item.name for trial in trials)
            }, "by_set": {
                set_name: summarize([trial for trial in trials if trial["dataset_set"] == set_name])
                for set_name in sorted({trial["dataset_set"] for trial in trials})
            }}
            _write_json(exp_dir / "summary.json", summary)
            log(f"{case.name} [{index}/{runs}] prompt={prompt_variant} status={scoring['status']} F1={scoring['metrics']['f1']:.3f} モデル照合={record['model_check']['status']}")
    return exp_dir


def build_report(exp_dirs: list[Path]) -> str:
    rows = []
    seen_hashes = {}
    for path in exp_dirs:
        summary = json.loads((path / "summary.json").read_text(encoding="utf-8"))
        if summary.get("benchmark") != "spec_contradictions":
            raise ValueError(f"仕様書ベンチマークの結果ではありません: {path}")
        for name, hashes in summary["input_hashes"].items():
            if name in seen_hashes and seen_hashes[name] != hashes:
                raise ValueError(f"異なる固定データの結果は同じ比較に使えません: {name}")
            seen_hashes[name] = hashes
        for name, scores in [("ALL", summary), *summary["by_spec"].items()]:
            # 過去の結果にセット情報がなくても、既存の課題名から分類できる。
            spec_sets = summary.get("spec_sets", {
                spec: next((set_name for set_name, names in SPEC_SETS.items() if spec in names), "unknown")
                for spec in summary["by_spec"]
            })
            set_label = ",".join(sorted(set(spec_sets.values()))) if name == "ALL" else spec_sets[name]
            rows.append([
                path.name, summary["model"], summary["effort"], summary.get("prompt_variant", "baseline"),
                set_label, name, str(scores["completed_trials"]),
                *(str(scores[key]) for key in ("tp", "fp", "fn")),
                *(_cell(scores[key], "rate") for key in ("precision", "recall", "f1", "mean_f1")),
                str(scores["missed_critical"]), str(scores["invalid_responses"]),
                str(scores["model_mismatch_trials"]), str(scores["model_unverified_trials"]),
                _cell(scores["mean_wall_seconds"], "sec"), _cell(scores["api_equivalent_usd_mean"], "usd"),
                _cell(scores["cli_reported_usd_total"], "usd"),
                _cell(scores.get("thinking_tokens")),
            ])
    table = _table([
        "experiment", "model", "effort", "prompt_variant", "set", "spec", "runs", "TP", "FP", "FN", "precision", "recall", "F1", "mean_F1",
        "critical_missed", "invalid", "model_mismatch", "model_unverified", "mean_sec", "mean_api_usd", "cli_usd", "thinking_tokens",
    ], rows)
    return table + (
        "\n\nモデルとEffortの組み合わせによる比較です。モデル能力だけの比較とは区別してください。"
        "\nprompt_variantでプロンプト条件を区別します。項目のない旧結果はbaselineとして表示します。"
        "\neffort=defaultはCLIの--effort省略です。特定のEffortやThinking予算への換算は行いません。"
        "\nthinking_tokensは出力トークンの内訳で、料金に再加算しません。未報告または旧結果は - です。"
        "\nTP/FP/FN・F1はID集合による採点です。理由は reason_review.json で別に確認してください。"
        "\nprecision/recall/F1は合計TP/FP/FNからのmicro集計、mean_F1は形式不正を0点として含む試行平均です。"
        "\ninvalid はJSON・スキーマ不正またはCLI異常の試行数です。モデル不一致・未確認も別に確認してください。"
        "\nAPI換算は既存の料金計算を使用します。TTL・長文料金の仮定は trial.json の cost.notes を参照してください。"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ai_lab.spec_benchmark")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="固定データのハッシュと正解データの構造を確認する")
    validate.add_argument("--set", choices=SPEC_SETS, default="set1")
    run = commands.add_parser("run", help="仕様書の矛盾検出を実行する")
    run.add_argument("--spec", choices=("all", *ALL_SPEC_NAMES), default="all")
    run.add_argument("--set", choices=SPEC_SETS, help="allの対象セット（省略時は従来のset1）")
    run.add_argument("--model", default="haiku")
    run.add_argument("--effort", choices=EFFORT_LEVELS, help="省略時はHaiku 4.5のみdefault、他はmedium。defaultはCLIの--effortを省略")
    run.add_argument("--prompt-variant", choices=PROMPT_VARIANTS, default="baseline")
    run.add_argument("--runs", type=int, default=1, help="仕様書ごとの独立試行回数")
    run.add_argument("--timeout", type=float, default=1200)
    run.add_argument("--results-dir", type=Path, default=PROJECT_ROOT / "results")
    run.add_argument("--claude-bin")
    run.add_argument("--dry-run", action="store_true")
    report = commands.add_parser("report", help="仕様書ベンチマークの結果を比較する")
    report.add_argument("dirs", nargs="+", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "report":
            print(build_report(args.dirs))
            return 0
        if args.command == "validate":
            for name in SPEC_SETS[args.set]:
                case = load_spec(name)
                print(f"{name}: {len(case.requirement_ids)}要件 / 正解構造・SHA256一致")
            return 0
        model_id, label = _resolve_model(args.model)
        args.effort = claude_cli.resolve_effort(model_id, args.effort)
        if args.runs < 1 or args.timeout <= 0:
            raise ValueError("--runs は1以上、--timeout は正の値を指定してください")
        if args.spec != "all" and args.set and args.spec not in SPEC_SETS[args.set]:
            raise ValueError("--spec と --set の所属が一致しません")
        selected = SPEC_SETS[args.set or "set1"] if args.spec == "all" else (args.spec,)
        cases = [load_spec(name) for name in selected]
        if args.dry_run:
            print(f"[dry-run] モデルは呼び出しません。model={model_id} effort={args.effort} specs={len(cases)} runs_per_spec={args.runs} prompt_variant={args.prompt_variant}")
            print("対象仕様書: " + ", ".join(case.name for case in cases))
            print('ツール: --tools "" --disallowedTools "*" --safe-mode --no-session-persistence')
            print("仕様書と正解データのSHA256を確認済み。正解データはプロンプトに含めません。")
            return 0
        reason = claude_cli.nested_run_reason(os.environ)
        if reason:
            raise RuntimeError(f"入れ子実行は拒否します（{reason}）。独立したターミナルで実行してください。")
        command = [args.claude_bin] if args.claude_bin else claude_cli.find_claude_command()
        claude_cli.check_native_executable(command[0])
        path = run_benchmark(cases, model_id=model_id, model_label=label, effort=args.effort,
                             runs=args.runs, timeout=args.timeout, results_dir=args.results_dir.resolve(), claude_command=command,
                             prompt_variant=args.prompt_variant)
        print(build_report([path]))
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("中断しました。保存済みの試行と集計は残っています。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
