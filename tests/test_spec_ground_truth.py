"""正解理由とは別に、仕様書の具体的な条件を有限状態の制約として確認する。

日本語本文を自動翻訳して証明するテストではない。対象・時点・同一属性を
本文から明示的に選び、各最小矛盾の不充足と各部分集合の充足を調べる。
"""

from itertools import product

import pytest

from ai_lab.spec_scoring import SPEC_NAMES, load_spec


def _opposite_values(values):
    return [(value,) for value in values], [lambda row: row[0] == values[0], lambda row: row[0] == values[1]]


def _dependency_chain():
    # 配送対象/出荷可能/支払済、当月対象/当月確定/確認済、保護対象/MFA必須/電話登録。
    # 1:対象→処理、2:処理→前提、3:対象かつ前提を満たせない。
    rows = list(product((False, True), repeat=3))
    return rows, [lambda row: not row[0] or row[1], lambda row: not row[1] or row[2], lambda row: row[0] and not row[2]]


# 各値は本文の同じ対象・同じ時点の同じ属性についての候補状態。
CONFLICT_CASES = [
    ("order_fulfillment", ("R01", "R02"), _opposite_values((True, False))),  # 梱包済み・未出荷・30分以内の受付可否
    ("order_fulfillment", ("R03", "R04"), _opposite_values((500, 0))),  # 国内通常便の送料欄
    ("order_fulfillment", ("R05", "R06", "R07"), _dependency_chain()),
    ("order_fulfillment", ("R08", "R09"), _opposite_values(("TRACK-123", ""))),  # 同一確定処理終了時
    ("expense_approval", ("R01", "R02"), _opposite_values((1, 2))),  # 国内一般経費8000円の必要承認者数
    ("expense_approval", ("R03", "R04"), _opposite_values(("JPY", "USD"))),
    ("expense_approval", ("R05", "R06", "R07"), _dependency_chain()),
    ("expense_approval", ("R08", "R09"), _opposite_values((True, False))),  # 支払日の翌日の監査ログの存在
    ("access_control", ("R01", "R02"), _opposite_values((False, True))),  # 有効サポート担当者の電話番号変更権限
    ("access_control", ("R03", "R04"), _opposite_values((False, True))),  # 退会翌日の同じメールアドレスの存在
    ("access_control", ("R05", "R06", "R07"), _dependency_chain()),
    ("access_control", ("R08", "R09"), _opposite_values((True, False))),  # 発行18時間後・手動取消なし
]


@pytest.mark.parametrize("name, ids, constraints", CONFLICT_CASES)
def test_every_gold_conflict_is_inconsistent_and_minimal(name, ids, constraints):
    rows, predicates = constraints
    gold_groups = {tuple(item["requirement_ids"]) for item in load_spec(name).answer_key["contradictions"]}
    assert ids in gold_groups
    assert not any(all(predicate(row) for predicate in predicates) for row in rows)
    for removed in range(len(predicates)):
        remaining = [predicate for index, predicate in enumerate(predicates) if index != removed]
        assert any(all(predicate(row) for predicate in remaining) for row in rows), f"{name} {ids}: {ids[removed]}は不要"


@pytest.mark.parametrize("name", SPEC_NAMES)
def test_semantic_checks_cover_every_fixed_conflict(name):
    checked = {ids for checked_name, ids, _ in CONFLICT_CASES if checked_name == name}
    gold = {tuple(item["requirement_ids"]) for item in load_spec(name).answer_key["contradictions"]}
    assert checked == gold


SCOPED_CONTROLS = [
    ("order_fulfillment", ("R10", "R11"), ("normal", "express"), (True, False)),
    ("order_fulfillment", ("R03", "R14"), ("normal", "express_member"), (500, 0)),
    ("order_fulfillment", ("R03", "R15"), ("domestic", "overseas"), (500, 1200)),
    ("expense_approval", ("R10", "R11"), ("employee", "part_time"), (30000, 15000)),
    ("expense_approval", ("R14", "R15"), ("season_ticket", "single_trip"), (1, 2)),
    ("access_control", ("R10", "R11"), ("admin", "user"), (True, False)),
    ("access_control", ("R14", "R15"), ("corporate", "personal_free"), (True, False)),
]


@pytest.mark.parametrize("name, ids, scopes, values", SCOPED_CONTROLS)
def test_different_conditions_have_consistent_states(name, ids, scopes, values):
    controls = {tuple(item["requirement_ids"]) for item in load_spec(name).answer_key["non_contradictions"]}
    assert ids in controls
    for scope in scopes:
        first = lambda value: scope != scopes[0] or value == values[0]
        second = lambda value: scope != scopes[1] or value == values[1]
        assert any(first(value) and second(value) for value in values)


@pytest.mark.parametrize("name", SPEC_NAMES)
def test_explicit_exception_is_consistent_for_both_branches(name):
    controls = {tuple(item["requirement_ids"]) for item in load_spec(name).answer_key["non_contradictions"]}
    assert ("R12", "R13") in controls
    # 梱包済み住所変更、低額領収書添付、復旧チケットログインの各例外。
    for exception in (False, True):
        ordinary_value = False if name == "access_control" else True
        exception_value = not ordinary_value
        r12 = lambda value: exception or value == ordinary_value
        r13 = lambda value: not exception or value == exception_value
        assert any(r12(value) and r13(value) for value in (False, True))


@pytest.mark.parametrize("name", SPEC_NAMES)
def test_semantic_checks_cover_every_non_conflict_control(name):
    checked = {ids for checked_name, ids, _, _ in SCOPED_CONTROLS if checked_name == name}
    checked.add(("R12", "R13"))
    expected = {tuple(item["requirement_ids"]) for item in load_spec(name).answer_key["non_contradictions"]}
    assert checked == expected


# 本文が決めていない情報について、両立する2つの補完で具体的判断が変わる。
INCOMPLETE_CASES = [
    ("order_fulfillment", "R16", (7, 30), lambda threshold: 10 > threshold),
    ("order_fulfillment", "R17", ("sat_open", "sat_closed"), lambda calendar: calendar == "sat_open"),
    ("expense_approval", "R16", (5, 60), lambda deadline: 30 <= deadline),
    ("expense_approval", "R17", ("use_date", "apply_date"), lambda date: 150 if date == "use_date" else 155),
    ("access_control", "R16", (3, 10), lambda threshold: 5 >= threshold),
    ("access_control", "R17", ("department_head", "support_lead"), lambda role: role == "department_head"),
]


@pytest.mark.parametrize("name, rid, completions, decision", INCOMPLETE_CASES)
def test_missing_information_allows_different_business_decisions(name, rid, completions, decision):
    entries = load_spec(name).answer_key["insufficient_information"]
    assert any(item["requirement_ids"] == [rid] and item["missing_information"] for item in entries)
    assert decision(completions[0]) != decision(completions[1])


@pytest.mark.parametrize("name", SPEC_NAMES)
def test_normal_requirements_have_a_concrete_consistent_state(name):
    assert load_spec(name).answer_key["normal_requirement_ids"] == ["R18", "R19", "R20"]
    if name == "order_fulfillment":
        ids = ["ORDER-1", "ORDER-2"]
        quantity, inventory_before, inventory_after = 2, 5, 3
        assert len(set(ids)) == len(ids) and 1 <= quantity <= 99 and inventory_after == inventory_before - quantity >= 0
    elif name == "expense_approval":
        initial_id, resubmission_id = "EXP-1", "EXP-2"
        applicant, approver, amount = "Alice", "Bob", 8000
        assert initial_id != resubmission_id and applicant != approver and amount > 0
    else:
        failure_time, active_after_logout, allowed_tenant, record_tenant = "2026-10-11T00:00:00Z", False, "T1", "T1"
        assert failure_time.endswith("Z") and not active_after_logout and allowed_tenant == record_tenant
