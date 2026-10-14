"""固定した仕様書データの読み込みと、要件ID集合による矛盾検出の採点。"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ai_lab.problems import PROJECT_ROOT

DATASET_ROOT = PROJECT_ROOT / "benchmarks" / "spec_contradictions"
SPEC_NAMES = ("order_fulfillment", "expense_approval", "access_control")
SET2_SPEC_NAMES = ("subscription_billing", "resource_booking", "notification_delivery")
SPEC_SETS = {"set1": SPEC_NAMES, "set2": SET2_SPEC_NAMES}
ALL_SPEC_NAMES = SPEC_NAMES + SET2_SPEC_NAMES
SET2_DATASET_ROOT = PROJECT_ROOT / "benchmarks" / "spec_contradictions_set2"
SEVERITIES = ("critical", "major", "minor")
PROMPT_VARIANTS = ("baseline", "minimality")

MINIMALITY_INSTRUCTIONS = """矛盾を報告する前に、各候補について次の点を確認してください。
1. 挙げた要件の適用条件が、同一対象・同一状況で同時に成立し得ること。
2. 挙げた要件IDだけで、同時に満たせないことを説明できること。説明に必要な要件がID集合から抜けていないこと。
3. 挙げたIDを1つずつ取り除いた場合、残りの要件を同時に満たせること。満たせないなら、その集合は最小ではないこと。
4. 必要な条件が不明なだけの場合は、確定的な矛盾と混同しないこと。
以上を踏まえ、矛盾を成立させる最小の要件ID集合だけを報告してください。
検証過程の長文出力は不要です。回答は従来のJSON形式を維持し、要件ID集合と簡潔な理由を記載してください。"""

PROMPT_TEMPLATE = """以下の業務仕様書について、同じ条件で同時に満たせない要件の矛盾を検出してください。
条件が異なる要件や明示された例外は区別してください。情報不足は矛盾と区別してください。
仕様書に書かれていない業務常識・法律・優先順位を補わないでください。

回答は次の構造のJSONオブジェクト1つだけとし、Markdownや前後の文章を付けないでください。
{{"contradictions": [{{"requirement_ids": ["Rxx", "Ryy"], "reason": "両立しない理由"}}],
  "insufficient_information": [{{"requirement_ids": ["Rxx"], "reason": "判断に足りない情報"}}]}}
矛盾がなければ contradictions は空配列にしてください。
各矛盾には、その矛盾に必要な最小の要件ID集合を挙げてください。3要件以上が必要ならすべて含めてください。
同じID集合を重複して報告しないでください。理由は空にしないでください。
insufficient_information は任意です。情報不足を contradictions に入れないでください。
ファイルや外部情報を参照するツールはありません。本文だけを読んで回答してください。

===== 仕様書 =====
{statement}
"""


@dataclass(frozen=True)
class SpecCase:
    name: str
    statement: str
    requirement_ids: frozenset[str]
    answer_key: dict[str, Any]
    hashes: dict[str, str]
    answer_key_text: str
    dataset_set: str = "set1"


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"JSONキーが重複しています: {key}")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ValueError(f"JSONではない数値です: {value}")


def _json(text: str) -> Any:
    return json.loads(text, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)


def _group(value: Any, known_ids: frozenset[str], minimum: int = 2) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) < minimum:
        raise ValueError(f"requirement_ids は{minimum}個以上のIDの配列が必要です")
    if any(not isinstance(item, str) or item not in known_ids for item in value):
        raise ValueError("requirement_ids に仕様書に存在しないIDがあります")
    if len(set(value)) != len(value):
        raise ValueError("requirement_ids 内でIDが重複しています")
    return tuple(sorted(value))


def _findings(value: Any, known_ids: frozenset[str], minimum: int = 2, gold: bool = False) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("指摘は配列で指定してください")
    for finding in value:
        if not isinstance(finding, dict):
            raise ValueError("指摘はオブジェクトで指定してください")
        if not gold and set(finding) - {"requirement_ids", "reason", "severity"}:
            raise ValueError("指摘に未定義のフィールドがあります")
        _group(finding.get("requirement_ids"), known_ids, minimum)
        if not isinstance(finding.get("reason"), str) or not finding["reason"].strip():
            raise ValueError("reason には空でない文字列が必要です")
        if "severity" in finding and finding["severity"] not in SEVERITIES:
            raise ValueError("severity は critical / major / minor のいずれかです")
    return value


def load_spec(name: str, root: Path | None = None) -> SpecCase:
    if name not in ALL_SPEC_NAMES:
        raise ValueError(f"未知の仕様書です: {name}")
    dataset_set = "set2" if name in SET2_SPEC_NAMES else "set1"
    if root is None:
        root = SET2_DATASET_ROOT if dataset_set == "set2" else DATASET_ROOT
    manifest = _json((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("version") != 1:
        raise ValueError("仕様書データのバージョンが未対応です")
    contents = {}
    hashes = {}
    for relative in (f"specs/{name}.md", f"answer_keys/{name}.json"):
        raw = (root / relative).read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != manifest["sha256"].get(relative):
            raise ValueError(f"固定済みデータのSHA256が一致しません: {relative}")
        contents[relative] = raw.decode("utf-8")
        hashes[relative] = digest
    statement = contents[f"specs/{name}.md"]
    ids = re.findall(r"^- (R\d{2}):", statement, re.MULTILINE)
    minimum, maximum = (25, 30) if dataset_set == "set2" else (15, 25)
    if not minimum <= len(ids) <= maximum or len(set(ids)) != len(ids):
        raise ValueError(f"仕様書は{minimum}〜{maximum}個の一意な要件IDが必要です")
    known_ids = frozenset(ids)
    key = _json(contents[f"answer_keys/{name}.json"])
    if key.get("spec") != name or key.get("version") != 1:
        raise ValueError("正解データの課題名またはバージョンが一致しません")
    groups: set[tuple[str, ...]] = set()
    covered: set[str] = set()
    for field, minimum in (("contradictions", 2), ("insufficient_information", 1), ("non_contradictions", 2)):
        entries = _findings(key.get(field), known_ids, minimum, gold=True)
        for entry in entries:
            group = _group(entry["requirement_ids"], known_ids, minimum)
            if group in groups:
                raise ValueError("正解データのID集合が重複・分類競合しています")
            groups.add(group)
            covered.update(group)
            if field == "contradictions" and entry.get("severity") not in SEVERITIES:
                raise ValueError("正解の矛盾には重大度が必要です")
            if field == "contradictions" and dataset_set == "set2":
                if not isinstance(entry.get("condition"), str) or not entry["condition"].strip():
                    raise ValueError("第2セットの正解には矛盾成立の具体的条件が必要です")
            if field == "insufficient_information" and not entry.get("missing_information"):
                raise ValueError("情報不足には不足情報の指定が必要です")
    normal = key.get("normal_requirement_ids")
    if not isinstance(normal, list) or not normal or len(normal) != len(set(normal)) or not set(normal) <= known_ids:
        raise ValueError("正常要件のIDが不正です")
    if covered & set(normal) or covered | set(normal) != known_ids:
        raise ValueError("正解データに未分類または正常要件との重複があります")
    return SpecCase(name, statement, known_ids, key, hashes, contents[f"answer_keys/{name}.json"], dataset_set)


def build_prompt(case: SpecCase, prompt_variant: str = "baseline") -> str:
    if prompt_variant not in PROMPT_VARIANTS:
        raise ValueError(f"未知のプロンプトバリエーションです: {prompt_variant}")
    prompt = PROMPT_TEMPLATE.format(statement=case.statement.strip())
    if prompt_variant == "baseline":
        return prompt
    marker = "\n===== 仕様書 =====\n"
    return prompt.replace(marker, "\n" + MINIMALITY_INSTRUCTIONS + "\n" + marker, 1)


def metrics(tp: int, fp: int, fn: int) -> dict[str, float | int]:
    precision = tp / (tp + fp) if tp + fp else (1.0 if not fn else 0.0)
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1}


def score_response(text: str | None, case: SpecCase, *, execution_error: str | None = None) -> dict[str, Any]:
    gold = {tuple(sorted(item["requirement_ids"])): item for item in case.answer_key["contradictions"]}
    status = "ok"
    error = execution_error
    parsed = None
    predictions = []
    information = []
    try:
        if execution_error:
            status = "execution_error"
            raise ValueError(execution_error)
        status = "invalid_json"
        parsed = _json(text) if isinstance(text, str) else None
        status = "invalid_schema"
        if not isinstance(parsed, dict) or set(parsed) - {"contradictions", "insufficient_information"}:
            raise ValueError("回答は contradictions と任意の insufficient_information を持つJSONオブジェクトが必要です")
        predictions = _findings(parsed.get("contradictions"), case.requirement_ids)
        information = _findings(parsed.get("insufficient_information", []), case.requirement_ids, 1)
        status = "ok"
    except (ValueError, TypeError) as exc:
        error = str(exc)
        predictions = []
        information = []

    predicted_groups = {_group(item["requirement_ids"], case.requirement_ids) for item in predictions}
    matched = set(gold) & predicted_groups
    missed = set(gold) - predicted_groups
    false_positive = predicted_groups - set(gold)
    scores = metrics(len(matched), len(false_positive), len(missed))
    if status != "ok":
        # 正解が空でも、形式不正を「矛盾なしで正解」にしない。
        scores.update(precision=0.0, recall=0.0, f1=0.0)
    non_conflicts = {tuple(sorted(item["requirement_ids"])): item for item in case.answer_key["non_contradictions"]}
    review = []
    for item in predictions:
        group = _group(item["requirement_ids"], case.requirement_ids)
        expected = gold.get(group) or non_conflicts.get(group)
        review.append({
            "requirement_ids": list(group),
            "model_reason": item["reason"],
            "id_classification": "tp" if group in matched else "fp",
            "expected_reason": expected["reason"] if expected else None,
            "expected_severity": gold[group]["severity"] if group in gold else None,
            "reason_verdict": None,
            "review_note": None,
        })
    return {
        "status": status,
        "error": error,
        "metrics": scores,
        "missed_critical": sum(gold[group]["severity"] == "critical" for group in missed),
        "matched_groups": [list(group) for group in sorted(matched)],
        "false_positive_groups": [list(group) for group in sorted(false_positive)],
        "missed_groups": [list(group) for group in sorted(missed)],
        "duplicate_findings": len(predictions) - len(predicted_groups),
        "reason_review": review,
        "information_findings": information,
    }
