"""第2セットの保存回答を、外側の単一フェンスだけ除去して別ファイルに再採点する。"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from ai_lab.problems import PROJECT_ROOT
from ai_lab.spec_scoring import SET2_SPEC_NAMES, SpecCase, _json, load_spec, metrics, score_response

CONDITIONS = (
    ("claude-haiku-5-5", "medium"),
    ("claude-haiku-5-5", "max"),
    ("claude-sonnet-4-6", "high"),
    ("claude-opus-4-8", "high"),
)
RUNS_PER_SPEC = 5
HAIKU45_CONDITION = ("claude-haiku-4-5", "default")


def normalize_answer(text: str) -> dict[str, Any]:
    """JSON自体は変更しない。既存と同じJSON解析器で形式の復旧だけを判定する。"""
    result = {"text": text, "original_json_valid": False, "fence_removed": False,
              "fence_recovered": False, "normalized_unparseable": True, "json_error": None}
    try:
        _json(text)
        result.update(original_json_valid=True, normalized_unparseable=False)
        return result
    except (ValueError, TypeError) as exc:
        result["json_error"] = str(exc)
    lines = text.strip().splitlines(keepends=True)
    opening = re.fullmatch(r"(?P<fence>`{3,}|~{3,})(?:json)?[ \t]*", lines[0].rstrip("\r\n")) if lines else None
    if opening is None or len(lines) < 3:
        return result
    fence = opening["fence"]
    closing = re.fullmatch(re.escape(fence[0]) + "{" + str(len(fence)) + r",}[ \t]*", lines[-1].strip())
    if closing is None or any(re.match(r"[ \t]*(?:`{3,}|~{3,})", line) for line in lines[1:-1]):
        return result
    # 外側以外の文章・ブロックを抽出せず、内側の全内容をそのまま渡す。
    result.update(text="".join(lines[1:-1]), fence_removed=True)
    try:
        _json(result["text"])
        result.update(fence_recovered=True, normalized_unparseable=False, json_error=None)
    except (ValueError, TypeError) as exc:
        result["json_error"] = str(exc)
    return result


def information_score(score: dict[str, Any], case: SpecCase) -> dict[str, Any]:
    gold = {tuple(sorted(item["requirement_ids"])) for item in case.answer_key["insufficient_information"]}
    predicted = {tuple(sorted(item["requirement_ids"])) for item in score["information_findings"]}
    result = metrics(len(gold & predicted), len(predicted - gold), len(gold - predicted))
    if score["status"] != "ok":
        result.update(precision=0.0, recall=0.0, f1=0.0)
    return {"metrics": result, "matched_groups": [list(group) for group in sorted(gold & predicted)],
            "false_positive_groups": [list(group) for group in sorted(predicted - gold)],
            "missed_groups": [list(group) for group in sorted(gold - predicted)]}


def _perfect(score: dict[str, Any]) -> bool:
    return score["status"] == "ok" and score["metrics"]["fp"] == score["metrics"]["fn"] == 0


def _directories(root: Path) -> list[Path]:
    # Path.globは読み取り拒否を黙って省くため、60件の発見に使わない。
    with os.scandir(root) as entries:
        return sorted(Path(entry.path) for entry in entries if entry.is_dir())


def read_saved_trials(results_dir: Path, *, haiku45_dir: Path | None = None) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    cases = {name: load_spec(name) for name in SET2_SPEC_NAMES}
    records = []
    unreadable = []
    selected_haiku45 = haiku45_dir.resolve() if haiku45_dir is not None else None
    conditions = CONDITIONS + (HAIKU45_CONDITION,) if selected_haiku45 is not None else CONDITIONS
    exp_dirs = _directories(results_dir.resolve())
    if selected_haiku45 is not None and selected_haiku45 not in exp_dirs:
        exp_dirs.append(selected_haiku45)
    for exp_dir in sorted(exp_dirs):
        try:
            with os.scandir(exp_dir) as entries:
                paths = {entry.name: Path(entry.path) for entry in entries}
            if "experiment.json" not in paths:
                continue
            meta = _json(paths["experiment.json"].read_text(encoding="utf-8"))
        except PermissionError as exc:
            unreadable.append({"path": str(exp_dir), "error": str(exc)})
            continue
        condition = (meta.get("model"), meta.get("effort"))
        if exp_dir.resolve() == selected_haiku45 and (
                condition != HAIKU45_CONDITION or meta.get("benchmark") != "spec_contradictions"
                or meta.get("prompt_variant", "baseline") != "baseline"):
            raise ValueError(f"指定したフォルダはHaiku 4.5/default/baselineの仕様書実験ではありません: {exp_dir}")
        if condition == HAIKU45_CONDITION and exp_dir.resolve() != selected_haiku45:
            continue
        if (meta.get("benchmark") != "spec_contradictions" or condition not in conditions
                or meta.get("prompt_variant", "baseline") != "baseline"):
            continue
        selected = [name for name in meta["specs"] if name in cases]
        if not selected:
            continue
        for name in selected:
            if meta.get("spec_sets", {}).get(name, cases[name].dataset_set) != "set2":
                raise ValueError(f"セット情報が一致しません: {exp_dir} / {name}")
            if meta.get("input_hashes", {}).get(name) != cases[name].hashes:
                raise ValueError(f"固定データのSHA256が一致しません: {exp_dir} / {name}")
        trial_dirs = sorted(path for name, path in paths.items() if re.fullmatch(r"trial_\d+", name))
        for trial_dir in trial_dirs:
            trial_path = trial_dir / "trial.json"
            raw_trial = trial_path.read_bytes()
            trial = _json(raw_trial.decode("utf-8"))
            if trial["spec"] not in selected:
                continue
            case = cases[trial["spec"]]
            if ((trial["model"], trial["effort"]) != condition
                    or trial.get("dataset_set", case.dataset_set) != "set2"
                    or trial.get("prompt_variant", meta.get("prompt_variant", "baseline")) != "baseline"):
                raise ValueError(f"実験と試行の条件が一致しません: {trial_path}")
            answer_path = trial_dir / "answer.txt"
            raw_answer = answer_path.read_bytes()
            normalization = normalize_answer(raw_answer.decode("utf-8"))
            cli_status = trial.get("claude", {}).get("status")
            execution_error = f"CLI status={cli_status}" if cli_status is not None and cli_status != "ok" else None
            if trial["scoring"]["status"] == "execution_error":
                execution_error = trial["scoring"]["error"] or "保存済みの実行エラー"
            normalized = score_response(normalization.pop("text"), case, execution_error=execution_error)
            records.append({
                "model": trial["model"], "effort": trial["effort"], "dataset_set": "set2",
                "prompt_variant": "baseline", "spec": trial["spec"], "trial": trial["trial"],
                "experiment_id": exp_dir.name, "experiment_dir": str(exp_dir),
                "answer_file": str(answer_path), "answer_sha256": hashlib.sha256(raw_answer).hexdigest(),
                "trial_file": str(trial_path), "trial_sha256": hashlib.sha256(raw_trial).hexdigest(),
                "strict": trial["scoring"], "normalized": normalized, **normalization,
                "information": information_score(normalized, case),
                "model_check": trial.get("model_check", {}),
                "wall_seconds": trial["wall_seconds"], "cost": trial["cost"],
                "api_equivalent_usd": trial["cost"]["api_equivalent_usd"],
            })
    counts = Counter((record["model"], record["effort"], record["spec"]) for record in records)
    expected = {(model, effort, name): RUNS_PER_SPEC for model, effort in conditions for name in SET2_SPEC_NAMES}
    if counts != expected:
        details = "; ".join(f"{model}/{effort}/{name}: {counts[model, effort, name]}/{runs}"
                            for (model, effort, name), runs in expected.items() if counts[model, effort, name] != runs)
        raise ValueError(f"各条件・仕様書5回（計{sum(expected.values())}試行）が必要です。重複や不足を確認してください: {details}")
    return records, unreadable


def aggregate(records: list[dict[str, Any]], model: str, effort: str, spec: str) -> dict[str, Any]:
    count = len(records)
    raw_valid = sum(record["original_json_valid"] for record in records)
    recovered = sum(record["fence_recovered"] for record in records)
    result = {
        "model": model, "effort": effort, "spec": spec, "trials": count,
        "original_json_valid": raw_valid, "strict_json_valid_rate": raw_valid / count,
        "fence_recovered": recovered,
        "fence_recovery_rate": recovered / (count - raw_valid) if count > raw_valid else None,
        "fence_recovery_rate_all": recovered / count,
        "normalized_unparseable": sum(record["normalized_unparseable"] for record in records),
        "normalized_invalid_schema": sum(record["normalized"]["status"] == "invalid_schema" for record in records),
        "model_mismatch": sum(record["model_check"].get("status") == "mismatch" for record in records),
        "model_unverified": sum(record["model_check"].get("status", "unverified") == "unverified" for record in records),
        "mean_wall_seconds": sum(record["wall_seconds"] for record in records) / count,
        "mean_api_equivalent_usd": sum(record["api_equivalent_usd"] for record in records) / count
            if all(record["cost"].get("complete") and record["api_equivalent_usd"] is not None for record in records) else None,
    }
    for mode in ("strict", "normalized"):
        scores = [record[mode] for record in records]
        micro = metrics(**{key: sum(score["metrics"][key] for score in scores) for key in ("tp", "fp", "fn")})
        result.update({f"{mode}_{key}": value for key, value in micro.items()})
        result[f"{mode}_valid"] = sum(score["status"] == "ok" for score in scores)
        result[f"{mode}_format_compliance_rate"] = result[f"{mode}_valid"] / count
        result[f"{mode}_perfect"] = sum(_perfect(score) for score in scores)
        result[f"{mode}_missed_critical"] = sum(score["missed_critical"] for score in scores)
    information = metrics(**{key: sum(record["information"]["metrics"][key] for record in records) for key in ("tp", "fp", "fn")})
    result.update({f"information_{key}": value for key, value in information.items()})
    return result


def requirement_count_scores(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """正解の最小ID集合の大きさ別に、正解機会数と厳密一致したTPを数える。"""
    gold_sizes = {name: Counter(len(item["requirement_ids"]) for item in load_spec(name).answer_key["contradictions"])
                  for name in SET2_SPEC_NAMES}
    rows = []
    for model, effort in dict.fromkeys((record["model"], record["effort"]) for record in records):
        selected = [record for record in records if (record["model"], record["effort"]) == (model, effort)]
        for size in sorted({size for sizes in gold_sizes.values() for size in sizes}):
            opportunities = sum(gold_sizes[record["spec"]][size] for record in selected)
            counts = {mode: sum(len(group) == size for record in selected for group in record[mode]["matched_groups"])
                      for mode in ("strict", "normalized")}
            rows.append({"model": model, "effort": effort, "requirement_count": size,
                         "gold_occurrences": opportunities, "strict_tp": counts["strict"],
                         "normalized_tp": counts["normalized"], "normalized_fn": opportunities - counts["normalized"],
                         "normalized_recall": counts["normalized"] / opportunities if opportunities else None})
    return rows


def analyze_saved(results_dir: Path, *, haiku45_dir: Path | None = None) -> dict[str, Any]:
    records, unreadable = read_saved_trials(results_dir, haiku45_dir=haiku45_dir)
    summaries = []
    conditions = CONDITIONS + (HAIKU45_CONDITION,) if haiku45_dir is not None else CONDITIONS
    for model, effort in conditions:
        selected = [record for record in records if (record["model"], record["effort"]) == (model, effort)]
        summaries.append(aggregate(selected, model, effort, "ALL"))
        summaries.extend(aggregate([record for record in selected if record["spec"] == name], model, effort, name)
                         for name in SET2_SPEC_NAMES)
    analysis = {"analysis": "spec_set2_json_fence_normalization", "created_at": datetime.now().astimezone().isoformat(),
            "dataset_set": "set2", "prompt_variant": "baseline", "trial_count": len(records),
            "input_hashes": {name: load_spec(name).hashes for name in SET2_SPEC_NAMES},
            "scorer_sha256": hashlib.sha256((PROJECT_ROOT / "ai_lab" / "spec_scoring.py").read_bytes()).hexdigest(),
            "trials": records, "summary": summaries, "unreadable_directories": unreadable}
    if haiku45_dir is not None:
        analysis["haiku45_experiment"] = str(haiku45_dir.resolve())
        analysis["by_requirement_count"] = requirement_count_scores(records)
    return analysis


def trial_rows(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for record in analysis["trials"]:
        row = {key: value for key, value in record.items() if key not in {"strict", "normalized", "information", "cost", "model_check"}}
        row.update(model_check_status=record["model_check"].get("status", "unverified"),
                   actual_model_ids=";".join(record["model_check"].get("actual_model_ids", [])),
                   cost_complete=record["cost"].get("complete", False))
        for mode in ("strict", "normalized"):
            score = record[mode]
            row.update({f"{mode}_{key}": value for key, value in score["metrics"].items()})
            row.update({f"{mode}_status": score["status"], f"{mode}_error": score["error"],
                        f"{mode}_missed_critical": score["missed_critical"], f"{mode}_perfect": _perfect(score)})
        row.update({f"information_{key}": value for key, value in record["information"]["metrics"].items()})
        rows.append(row)
    return rows


def format_report(analysis: dict[str, Any]) -> str:
    columns = ("model", "effort", "spec", "trials", "strict_json_valid_rate", "strict_format_compliance_rate",
               "fence_recovered", "fence_recovery_rate", "strict_f1", "normalized_f1", "normalized_perfect",
               "normalized_missed_critical", "normalized_unparseable", "normalized_invalid_schema",
               "mean_wall_seconds", "mean_api_equivalent_usd", "information_f1")

    def cell(key: str, value: Any) -> str:
        if value is None:
            return "—"
        if key.endswith("rate"):
            return f"{value:.1%}"
        if key.endswith("f1") or key.startswith("mean_"):
            return f"{value:.6f}"
        return str(value)

    lines = ["# 第2セット baseline：保存回答のJSON形式補正・再採点", "",
             f"対象: {analysis['trial_count']}試行。strictは保存済み採点、normalizedは外側の単一フェンス除去後の既存採点です。", "",
             "| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    lines.extend("| " + " | ".join(cell(key, row[key]) for key in columns) + " |" for row in analysis["summary"])
    if "by_requirement_count" in analysis:
        lines.extend(["", "矛盾を構成する最小要件ID集合の大きさ別の正解数です。分母は、その大きさの正解が出現する機会数です。", "",
                      "| model | effort | 要件ID数 | normalized TP / 正解機会 | 見落としFN |", "| --- | --- | --- | --- | --- |"])
        lines.extend(f"| {row['model']} | {row['effort']} | {row['requirement_count']} | {row['normalized_tp']} / {row['gold_occurrences']} | {row['normalized_fn']} |"
                     for row in analysis["by_requirement_count"])
        lines.extend(["", "情報不足の指摘は矛盾検出と別に、要件ID集合の一致で採点します。", "",
                      "| model | effort | TP | FP | FN | Precision | Recall | F1 |", "| --- | --- | --- | --- | --- | --- | --- | --- |"])
        lines.extend("| " + " | ".join(cell(key, row[key]) for key in (
            "model", "effort", "information_tp", "information_fp", "information_fn", "information_precision", "information_recall", "information_f1",
        )) + " |" for row in analysis["summary"] if row["spec"] == "ALL")
        lines.extend(["", f"Haiku 4.5はCLIデフォルト設定の指定した15試行だけを使用します: {analysis['haiku45_experiment']}",
                      "他のHaiku 4.5実験は集計に加えません。従来4条件の再採点ルール・対象条件は共通です。"])
    lines.extend(["", "strict_json_valid_rateは元回答のJSON解析成功率、strict_format_compliance_rateは保存済みstatus=okの割合です。",
                  "fence_recovery_rateは元JSON解析失敗試行のうち、外側フェンス除去でJSON解析が成功した割合です（該当なしは—）。スキーマ違反と実行エラーは復旧後も採点失敗です。",
                  "F1は合計TP/FP/FNによるmicro集計です。完全正解はstatus=okかつFP=FN=0の試行数で、理由の妥当性を保証しません。",
                  "information_f1は情報不足の要件ID集合一致を別集計した値で、矛盾検出F1に混ぜていません。",
                  "平均時間・費用は保存値を使用し、費用未確認の試行があれば平均費用は—です。モデル照合の異常はsummary.csvで確認できます。",
                  f"{analysis['trial_count']}試行の詳細はtrials.csv、指摘ID・理由のレビューと元strict採点全体はanalysis.jsonに保存しています。",
                  "元ファイル・課題・正解・採点・プロンプトは変更せず、CLIや実モデルは呼び出していません。", ""])
    if analysis["unreadable_directories"]:
        lines.extend([f"読み取れなかった候補フォルダを以下に記録します。採点対象の各条件・仕様書5件、計{analysis['trial_count']}件の検証は通過しています。", ""])
        lines.extend(f"- {item['path']}: {item['error']}" for item in analysis["unreadable_directories"])
        lines.append("")
    return "\n".join(lines)


def write_analysis(analysis: dict[str, Any], output_dir: Path, results_dir: Path) -> None:
    output_dir = output_dir.resolve()
    protected = (results_dir.resolve(), PROJECT_ROOT / "results", PROJECT_ROOT / "data", PROJECT_ROOT / "benchmarks", PROJECT_ROOT / "problems",
                 *(Path(record["experiment_dir"]) for record in analysis["trials"]))
    if any(output_dir == root.resolve() or output_dir.is_relative_to(root.resolve()) for root in protected):
        raise ValueError("出力先は保存済み結果・仕様書・正解データの外にある新しいディレクトリにしてください")
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "report.md").write_text(format_report(analysis), encoding="utf-8")
    csv_outputs = [("trials.csv", trial_rows(analysis)), ("summary.csv", analysis["summary"])]
    if "by_requirement_count" in analysis:
        csv_outputs.append(("by_requirement_count.csv", analysis["by_requirement_count"]))
    for filename, rows in csv_outputs:
        with (output_dir / filename).open("x", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ai_lab.spec_rescore")
    parser.add_argument("--results-dir", type=Path, default=PROJECT_ROOT / "results")
    parser.add_argument("--output-dir", type=Path, required=True, help="保存済み結果の外にある、未作成の分析用ディレクトリ")
    parser.add_argument("--haiku45-dir", type=Path, help="比較に加えるHaiku 4.5/default/baselineの15試行実験フォルダ。省略時は従来60試行")
    args = parser.parse_args(argv)
    try:
        analysis = analyze_saved(args.results_dir, haiku45_dir=args.haiku45_dir)
        write_analysis(analysis, args.output_dir, args.results_dir)
        print(format_report(analysis))
        print(f"分析ファイル: {args.output_dir.resolve()}")
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"再採点エラー: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
