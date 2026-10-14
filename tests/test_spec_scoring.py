import copy
import hashlib
import json
import shutil
from dataclasses import replace

import pytest

from ai_lab.spec_scoring import DATASET_ROOT, SPEC_NAMES, build_prompt, load_spec, score_response


def _answer(case, groups=None):
    return {
        "contradictions": [
            {"requirement_ids": item["requirement_ids"], "reason": item["reason"]}
            for item in (case.answer_key["contradictions"] if groups is None else groups)
        ]
    }


@pytest.mark.parametrize("name", SPEC_NAMES)
def test_fixed_dataset_is_complete_and_prompt_contains_only_public_text(name):
    case = load_spec(name)
    assert case.requirement_ids == frozenset(f"R{index:02d}" for index in range(1, 21))
    assert len(case.answer_key["contradictions"]) == 4
    assert len(case.answer_key["insufficient_information"]) == 2
    assert all(len(item["requirement_ids"]) in (2, 3) for item in case.answer_key["contradictions"])
    assert sum(len(item["requirement_ids"]) == 3 for item in case.answer_key["contradictions"]) == 1
    prompt = build_prompt(case)
    assert case.statement.strip() in prompt
    assert "answer_keys" not in prompt and "snapshots" not in prompt
    assert "4件" not in prompt and "critical" not in prompt
    for item in case.answer_key["contradictions"]:
        assert item["reason"] not in prompt


@pytest.mark.parametrize("name", SPEC_NAMES)
def test_all_gold_groups_score_perfectly_without_approving_reasons(name):
    case = load_spec(name)
    answer = _answer(case)
    for finding in answer["contradictions"]:
        finding["requirement_ids"] = list(reversed(finding["requirement_ids"]))
        finding["reason"] = "理由の正しさは別途レビューするテスト用の文字列"
    score = score_response(json.dumps(answer), case)
    assert score["status"] == "ok"
    assert score["metrics"] == {"tp": 4, "fp": 0, "fn": 0, "precision": 1, "recall": 1, "f1": 1}
    assert score["missed_critical"] == 0
    assert all(item["reason_verdict"] is None for item in score["reason_review"])
    assert all(item["expected_reason"] for item in score["reason_review"])


def test_missing_critical_contradiction_reduces_recall_and_f1():
    case = load_spec("order_fulfillment")
    remaining = [item for item in case.answer_key["contradictions"] if item["severity"] != "critical"]
    score = score_response(json.dumps(_answer(case, remaining)), case)
    assert score["metrics"]["tp"] == 3 and score["metrics"]["fn"] == 1
    assert score["metrics"]["precision"] == 1
    assert score["metrics"]["recall"] == 0.75
    assert score["metrics"]["f1"] == pytest.approx(6 / 7)
    assert score["missed_critical"] == 1


@pytest.mark.parametrize("name", SPEC_NAMES)
def test_false_positive_controls_reduce_precision_and_f1(name):
    case = load_spec(name)
    answer = _answer(case)
    answer["contradictions"].extend(case.answer_key["non_contradictions"][:2])
    score = score_response(json.dumps(answer), case)
    assert score["metrics"]["tp"] == 4 and score["metrics"]["fp"] == 2
    assert score["metrics"]["precision"] == pytest.approx(2 / 3)
    assert score["metrics"]["recall"] == 1
    assert score["metrics"]["f1"] == pytest.approx(0.8)


@pytest.mark.parametrize("ids", [["R05", "R06"], ["R05", "R06", "R07", "R20"]])
def test_partial_or_superfluous_groups_do_not_match_three_requirement_conflict(ids):
    case = load_spec("order_fulfillment")
    answer = _answer(case)
    answer["contradictions"][2]["requirement_ids"] = ids
    score = score_response(json.dumps(answer), case)
    assert score["metrics"]["tp"] == 3
    assert score["metrics"]["fp"] == score["metrics"]["fn"] == 1
    assert score["missed_critical"] == 1


def test_duplicate_group_does_not_inflate_true_positives():
    case = load_spec("order_fulfillment")
    answer = _answer(case)
    duplicate = copy.deepcopy(answer["contradictions"][0])
    duplicate["requirement_ids"].reverse()
    answer["contradictions"].append(duplicate)
    score = score_response(json.dumps(answer), case)
    assert score["metrics"]["tp"] == 4
    assert score["duplicate_findings"] == 1


def test_information_shortage_is_separate_from_contradictions():
    case = load_spec("order_fulfillment")
    answer = _answer(case)
    answer["insufficient_information"] = [{"requirement_ids": ["R16"], "reason": "日数が未指定"}]
    score = score_response(json.dumps(answer), case)
    assert score["metrics"]["f1"] == 1
    assert score["information_findings"] == answer["insufficient_information"]
    answer["contradictions"].append({"requirement_ids": ["R16", "R17"], "reason": "情報不足を矛盾と誤認"})
    assert score_response(json.dumps(answer), case)["metrics"]["fp"] == 1


@pytest.mark.parametrize("answer, expected", [
    ({"contradictions": []}, (0, 0, 0, 1, 1, 1)),
    ({"contradictions": [{"requirement_ids": ["R01", "R02"], "reason": "存在しない矛盾"}]}, (0, 1, 0, 0, 1, 0)),
])
def test_empty_gold_is_scored_explicitly(answer, expected):
    case = load_spec("order_fulfillment")
    key = {**case.answer_key, "contradictions": []}
    score = score_response(json.dumps(answer), replace(case, answer_key=key))
    assert tuple(score["metrics"][key] for key in ("tp", "fp", "fn", "precision", "recall", "f1")) == expected
    assert score["missed_critical"] == 0


@pytest.mark.parametrize("text, status", [
    ("not JSON", "invalid_json"),
    ('```json\n{"contradictions": []}\n```', "invalid_json"),
    ('{"contradictions": [], "contradictions": []}', "invalid_json"),
    ('{"contradictions": [], "value": NaN}', "invalid_json"),
    ("[]", "invalid_schema"),
    ("{}", "invalid_schema"),
    ('{"contradictions": "none"}', "invalid_schema"),
    ('{"contradictions": [{"requirement_ids": ["R01", "R99"], "reason": "unknown"}]}', "invalid_schema"),
    ('{"contradictions": [{"requirement_ids": ["R01", "R01"], "reason": "duplicate"}]}', "invalid_schema"),
    ('{"contradictions": [{"requirement_ids": ["R01", "R02"], "reason": " "}]}', "invalid_schema"),
    ('{"contradictions": [{"requirement_ids": ["R01", "R02"]}]}', "invalid_schema"),
])
def test_invalid_responses_are_recorded_and_never_scored_as_correct(text, status):
    case = load_spec("access_control")
    score = score_response(text, case)
    assert score["status"] == status and score["error"]
    assert score["metrics"]["tp"] == 0 and score["metrics"]["fn"] == 4
    assert score["metrics"]["f1"] == 0
    assert score["missed_critical"] == 3
    empty = replace(case, answer_key={**case.answer_key, "contradictions": []})
    assert score_response(text, empty)["metrics"]["f1"] == 0


def test_cli_error_overrides_an_otherwise_correct_json_answer():
    case = load_spec("order_fulfillment")
    score = score_response(json.dumps(_answer(case)), case, execution_error="CLI status=timeout")
    assert score["status"] == "execution_error"
    assert score["metrics"]["f1"] == 0
    assert score["error"] == "CLI status=timeout"


@pytest.mark.parametrize("relative", ["specs/order_fulfillment.md", "answer_keys/order_fulfillment.json"])
def test_changed_fixed_input_is_rejected_before_execution(tmp_path, relative):
    root = tmp_path / "dataset"
    shutil.copytree(DATASET_ROOT, root)
    target = root / relative
    target.write_bytes(target.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="SHA256"):
        load_spec("order_fulfillment", root)


def test_semantically_invalid_answer_key_is_rejected_even_with_a_matching_hash(tmp_path):
    root = tmp_path / "dataset"
    shutil.copytree(DATASET_ROOT, root)
    relative = "answer_keys/order_fulfillment.json"
    target = root / relative
    key = json.loads(target.read_text(encoding="utf-8"))
    key["contradictions"][0]["requirement_ids"] = ["R01", "R99"]
    target.write_text(json.dumps(key), encoding="utf-8")
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["sha256"][relative] = hashlib.sha256(target.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="存在しないID"):
        load_spec("order_fulfillment", root)
