"""保存済みの実験結果（summary.json）を比較表にまとめる。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_summary(exp_dir: Path) -> dict[str, Any]:
    path = exp_dir / "summary.json"
    if not path.exists():
        raise FileNotFoundError(f"summary.json がありません（実験が途中で止まった可能性があります）: {exp_dir}")
    return json.loads(path.read_text(encoding="utf-8"))


def _cell(value: Any, kind: str = "text") -> str:
    if value is None:
        return "-"
    if kind == "rate":
        return f"{value:.1%}"
    if kind == "usd":
        return f"{value:.6f}"
    if kind == "sec":
        return f"{value:.1f}"
    if kind == "bool":
        return "yes" if value else "no"
    return str(value)


def _table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))

    def line(cells: list[str]) -> str:
        return "  ".join(cell.ljust(widths[index]) for index, cell in enumerate(cells)).rstrip()

    lines = [line(headers), line(["-" * width for width in widths])]
    lines.extend(line(row) for row in rows)
    return "\n".join(lines)


def format_report(entries: list[tuple[str, dict[str, Any]]]) -> str:
    result_rows: list[list[str]] = []
    cost_rows: list[list[str]] = []
    for name, summary in entries:
        result_rows.append(
            [
                name,
                summary["model"],
                summary["effort"],
                f"{summary['completed_runs']}/{summary['requested_runs']}",
                str(summary["passed"]),
                _cell(summary["pass_rate"], "rate"),
                _cell(summary["any_passed"], "bool"),
                str(summary["cli_not_ok"]),
                _cell(summary["mean_wall_seconds"], "sec"),
            ]
        )
        tokens = summary["tokens"]
        cost_rows.append(
            [
                name,
                str(tokens["input"]),
                str(tokens["output"]),
                str(tokens["cache_read"]),
                str(tokens["cache_write"]),
                _cell(summary["api_equivalent_usd_total"], "usd"),
                _cell(summary["api_equivalent_usd_per_pass"], "usd"),
                _cell(summary["cost_complete"], "bool"),
                _cell(summary["cli_reported_usd_total"], "usd"),
            ]
        )
    results = _table(
        ["experiment", "model", "effort", "runs", "passed", "pass_rate", "any_passed", "cli_not_ok", "mean_sec"],
        result_rows,
    )
    costs = _table(
        ["experiment", "input", "output", "cache_read", "cache_write", "api_usd", "usd_per_pass", "cost_complete", "cli_usd"],
        cost_rows,
    )
    notes = (
        "注: api_usd は公式単価からトークン数を基に計算した API 換算の推定値です（キャッシュ書き込みは1時間TTLの単価と仮定）。\n"
        "    cli_usd は Claude Code が報告した total_cost_usd の合計で、参考値です。Haiku 5.5 では CLI が単価を認識できず\n"
        "    Opus 5.5 相当の単価で計算するため、実際より大きく出ます（第1回の実機確認で確認済み。api_usd を使ってください）。\n"
        "    cost_complete が no の場合、一部の使用量が計算に含まれていません（trial.json の cost.notes を参照）。"
    )
    return "\n\n".join(["[結果と時間]\n" + results, "[トークンと API 換算コスト]\n" + costs, notes])


def build_report(exp_dirs: list[Path]) -> str:
    return format_report([(path.name, load_summary(path)) for path in exp_dirs])
