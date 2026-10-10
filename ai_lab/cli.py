"""コマンドラインの入口。

使い方（独立したターミナルで実行してください）:
  python -m ai_lab run --problem duration_parse --model haiku --effort medium --runs 3
  python -m ai_lab run --problem duration_parse --model opus --effort medium --runs 1
  python -m ai_lab report results/<実験1> results/<実験2>

--dry-run を付けると、モデルを呼ばずに実行内容だけを表示します。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from ai_lab import claude_cli
from ai_lab.experiment import ExperimentConfig, run_experiment
from ai_lab.pricing import MODEL_IDS, PRICES_PER_MTOK
from ai_lab.problems import PROJECT_ROOT, build_prompt, load_problem
from ai_lab.report import build_report

EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")


def _resolve_model(value: str) -> tuple[str, str]:
    """(モデルID, 結果ディレクトリ名に使う短い名前) を返す。"""
    if value in MODEL_IDS:
        return MODEL_IDS[value], value
    if value in PRICES_PER_MTOK:
        return value, value
    known = ", ".join([*MODEL_IDS, *PRICES_PER_MTOK])
    raise ValueError(f"未知のモデルです: {value!r}（指定可能: {known}）")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m ai_lab",
        description="安価なAIを複数回実行する方法と、高性能AIを1回実行する方法を比較する実験ツール",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="課題をモデルに解かせて、結果を保存する")
    run.add_argument("--problem", default="duration_parse", help="problems/ 以下の課題名（既定: duration_parse）")
    run.add_argument("--model", default="haiku", help="haiku / opus、またはモデルID（例: claude-haiku-5-5）")
    run.add_argument("--effort", default="medium", choices=EFFORT_LEVELS, help="effort（既定: medium）")
    run.add_argument("--runs", type=int, default=1, help="独立した試行の回数（既定: 1）")
    run.add_argument("--timeout", type=float, default=1200, help="1試行の上限秒数（既定: 1200）")
    run.add_argument("--results-dir", type=Path, default=PROJECT_ROOT / "results", help="結果の保存先（既定: results/）")
    run.add_argument("--claude-bin", help="claude の実行ファイル（既定: PATH 上の claude）")
    run.add_argument("--dry-run", action="store_true", help="モデルを呼ばず、実行内容だけを表示する")

    report = commands.add_parser("report", help="保存済みの実験結果を比較表で表示する")
    report.add_argument("dirs", nargs="+", type=Path, help="実験の結果ディレクトリ（results/ 以下）")
    return parser


def _dry_run(config: ExperimentConfig) -> int:
    problem = load_problem(config.problem, config.problems_root)
    prompt_preview = "<課題文>"
    command = ["claude", *claude_cli.build_args(config.model_id, config.effort, prompt_preview)]
    print("[dry-run] モデルは呼び出しません。")
    print(f"課題: {problem.name}（課題文 {len(build_prompt(problem))} 文字）")
    print(f"モデル: {config.model_id} / effort: {config.effort} / 試行数: {config.runs}")
    print(f"結果の保存先: {config.results_dir}")
    print("1試行で実行されるコマンド（課題文は省略）:")
    print("  " + " ".join(command))
    removed = [name for name in claude_cli.BILLING_ENV_VARS if name in os.environ]
    print("子プロセスから取り除く環境変数（この端末で設定されているもの）: " + (", ".join(removed) or "なし"))
    reason = claude_cli.nested_run_reason(os.environ)
    if reason:
        print(f"注意: この端末は Claude Code の内部です（{reason}）。本実行は拒否されます。独立したターミナルで実行してください。")
    else:
        print("この端末は Claude Code の内部ではないため、本実行できます。")
    return 0


def _run(args: argparse.Namespace) -> int:
    model_id, model_label = _resolve_model(args.model)
    if args.runs < 1:
        raise ValueError("--runs は1以上を指定してください")
    config = ExperimentConfig(
        problem=args.problem,
        model_id=model_id,
        model_label=model_label,
        effort=args.effort,
        runs=args.runs,
        timeout=args.timeout,
        results_dir=args.results_dir.resolve(),
        problems_root=(PROJECT_ROOT / "problems").resolve(),
    )
    if args.dry_run:
        return _dry_run(config)

    # Claude Code の内部からモデルを呼ぶと入れ子実行になるため、拒否する。
    reason = claude_cli.nested_run_reason(os.environ)
    if reason:
        print(
            f"エラー: Claude Code のセッション内から実行されています（環境変数 {reason}）。"
            "入れ子実行を避けるため、独立したターミナルで実行してください。",
            file=sys.stderr,
        )
        return 2

    if args.claude_bin:
        claude_cli.check_native_executable(args.claude_bin)
        command = [args.claude_bin]
    else:
        command = claude_cli.find_claude_command()
    exp_dir = run_experiment(config, command)
    print()
    print(build_report([exp_dir]))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "report":
            print(build_report([path.resolve() for path in args.dirs]))
            return 0
        return _run(args)
    except (RuntimeError, FileNotFoundError, ValueError) as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("中断しました。", file=sys.stderr)
        return 130
