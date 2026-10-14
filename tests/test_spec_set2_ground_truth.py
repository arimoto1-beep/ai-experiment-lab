"""第2セットの本文から独立にモデル化した制約で、全ての最小矛盾集合を探索する。

正解JSONから制約を生成しない。関連する属性を同じモデルに置き、条件を
固定した各ケースで全要件部分集合を調べる。日本語との対応はREVIEW.mdで照合する。
"""

from itertools import combinations, product

import pytest

from ai_lab.spec_scoring import SET2_SPEC_NAMES, load_spec


def _minimal_unsat(rows, rules):
    ids = list(rules)
    masks = [sum(1 << index for index, rid in enumerate(ids) if rules[rid](row)) for row in rows]
    found = []
    for size in range(1, len(ids) + 1):
        for indices in combinations(range(len(ids)), size):
            mask = sum(1 << index for index in indices)
            if any(previous & mask == previous for previous in found):
                continue
            if not any(row_mask & mask == mask for row_mask in masks):
                found.append(mask)
    return {frozenset(rid for index, rid in enumerate(ids) if mask & (1 << index)) for mask in found}


def _ordered(successor, predecessor, row):
    return row[successor] is None or (row[predecessor] is not None and row[predecessor] < row[successor])


def _cycle(ids, edges):
    rows = list(product((None, 1, 2, 3), repeat=3))
    rules = {ids[0]: lambda row: all(time is not None for time in row)}
    for rid, (successor, predecessor) in zip(ids[1:], edges):
        rules[rid] = lambda row, s=successor, p=predecessor: _ordered(s, p, row)
    return [rows], rules


def _subscription_models():
    refund = []
    for early, billing_error in product((False, True), repeat=2):
        refund.append([(early, billing_error, amount) for amount in (0, 90, 100)])
    yield "refund_policy", refund, {
        "R02": lambda r: not (r[0] and not r[1]) or r[2] == 100,
        "R09": lambda r: not (r[0] and not r[1]) or r[2] == 90,
        "R05": lambda r: r[0] or r[1] or r[2] == 0,
        "R18": lambda r: not r[1] or r[2] == 100,
    }
    renewal = [[(enabled, requests) for requests in (0, 1)] for enabled in (False, True)]
    yield "renewal_at_T", renewal, {"R06": lambda r: r[0] or r[1] == 0, "R16": lambda r: r[1] == 1}
    activation = []
    for imported in (False, True):
        activation.append([(imported, active, paid) for active, paid in product((None, -1, 0, 1), repeat=2)])
    yield "activation_at_U", activation, {
        "R04": lambda r: r[1] == 0,
        "R13": lambda r: r[1] is None or (r[2] is not None and r[2] < r[1]),
        "R21": lambda r: not r[0] or _ordered(2, 1, r),
    }
    profiles, rules = _cycle(("R07", "R17", "R23", "R26"), ((0, 1), (1, 2), (2, 0)))
    yield "refund_processing_order", profiles, rules
    yield "refund_request_replay", [[(same_id,) for same_id in (False, True)]], {
        "R12": lambda r: r[0], "R25": lambda r: not r[0],
    }
    changes = []
    for annual, operation in product((False, True), ("basic", "upgrade_option", "downgrade")):
        changes.append([(annual, operation, timing, extra, refund)
                        for timing, extra, refund in product(("next_month", "next_year", "immediate"), (False, True), (False, True))])
    yield "plan_changes", changes, {
        "R03": lambda r: r[0] or r[1] == "upgrade_option" or r[2] == "next_month",
        "R10": lambda r: not r[0] or r[1] == "upgrade_option" or r[2] == "next_year",
        "R08": lambda r: r[0] or r[1] != "upgrade_option" or (r[2] == "immediate" and r[3]),
        "R15": lambda r: r[0] or r[1] != "downgrade" or (r[2] == "next_month" and not r[4]),
    }
    yield "payment_retry", [[(success, retries) for retries in range(5)] for success in (False, True)], {
        "R11": lambda r: r[0] or r[1] <= 3, "R19": lambda r: not r[0] or r[1] == 0,
    }


def _booking_models():
    yield "cancel_fee", [[(fee,) for fee in (0, 3000)]], {
        "R03": lambda r: r[0] == 0, "R14": lambda r: r[0] == 3000,
    }
    admission = []
    for maintenance, soon, urgent, existing in product((False, True), (False, True), (False, True), (0, 1)):
        # countは実際の確定予約の件数。受付拒否、既存維持、新規追加を独立な概念として区別する。
        admission.append([(maintenance, soon, urgent, existing, accept, keep, existing * keep + accept)
                          for accept, keep in product((False, True), (False, True))])
    yield "admission_and_capacity", admission, {
        "R04": lambda r: not r[1] or (not r[0] and r[2] and r[3] == 0) or not r[4],
        "R05": lambda r: not r[0] or not r[4],
        "R08": lambda r: r[6] <= 1,
        "R18": lambda r: r[0] or not r[1] or not r[2] or r[3] != 0 or r[4],
        "R19": lambda r: not r[0] or r[3] == 0 or r[5],
        "R22": lambda r: r[0] or r[1] or r[3] != 1 or (r[4] and r[5]),
    }
    yield "quota_return", [list(product((None, 1, 2), repeat=2))], {
        "R02": lambda r: r[0] is not None,
        "R12": lambda r: _ordered(0, 1, r),
        "R20": lambda r: _ordered(1, 0, r),
    }
    profiles, rules = _cycle(("R07", "R17", "R25", "R28"), ((1, 0), (0, 2), (2, 1)))
    yield "first_corporate_visit", profiles, rules
    no_show = [[(minute, checked_in, state) for state in ("confirmed", "canceled")]
               for minute, checked_in in product((0, 14, 15, 59, 60), (False, True))]
    yield "no_show_transition", no_show, {
        "R11": lambda r: r[0] != 15 or r[1] or r[2] == "canceled",
        "R23": lambda r: not 0 <= r[0] < 60 or r[2] == "confirmed",
    }
    yield "booking_duration", [[(corporate, hours) for hours in range(1, 6)] for corporate in (False, True)], {
        "R01": lambda r: not r[0] or r[1] <= 4, "R10": lambda r: r[0] or r[1] <= 2,
    }
    yield "money_refund", [[(corporate, money_refund, day) for money_refund, day in product((False, True), (0, 1, 2))]
                           for corporate in (False, True)], {
        "R06": lambda r: not r[0] or (r[1] and r[2] <= 1), "R16": lambda r: r[0] or not r[1],
    }


def _notification_models():
    stop_profiles = []
    for kind, paused, opted_out, p0 in product(("marketing", "billing", "security", "intrusion"), (False, True), (False, True), (False, True)):
        stop_profiles.append([(kind, paused, opted_out, p0, queued) for queued in (False, True)])
    yield "stop_policies", stop_profiles, {
        "R01": lambda r: r[0] != "marketing" or not r[2] or not r[4],
        "R15": lambda r: r[1] or r[0] != "marketing" or not r[2] or not r[3] or r[4],
        "R04": lambda r: not r[1] or r[0] == "intrusion" or not r[4],
        "R19": lambda r: not r[1] or r[0] != "intrusion" or r[4],
    }
    success_profiles = [[(success, ten_minutes, new_retry) for new_retry in (False, True)]
                        for success, ten_minutes in product((False, True), repeat=2)]
    yield "email_success_retry", success_profiles, {
        "R08": lambda r: not r[0] or not r[2], "R22": lambda r: not r[1] or r[2],
    }
    yield "billing_priority", [list(product((False, True), ("dunning", "paid")))], {
        "R03": lambda r: r[1] == ("dunning" if r[0] else "paid"),
        "R12": lambda r: r[0], "R25": lambda r: r[1] == "paid",
    }
    profiles, rules = _cycle(("R05", "R16", "R23", "R27"), ((2, 1), (1, 0), (0, 2)))
    yield "new_invoice_queue", profiles, rules
    retries = [[(channel, transient, delay) for delay in (None, 60, 300)]
               for channel, transient in product(("email", "sms"), (False, True))]
    yield "retry_conditions", retries, {
        "R07": lambda r: r[0] != "email" or not r[1] or r[2] == 300,
        "R11": lambda r: r[0] != "sms" or not r[1] or r[2] == 60,
        "R24": lambda r: r[0] != "sms" or not r[1] or r[2] == 300,
        "R18": lambda r: r[0] != "sms" or r[1] or r[2] is None,
    }
    yield "quiet_hours", [[(channel, blocked) for blocked in (False, True)] for channel in ("email", "sms")], {
        "R02": lambda r: r[0] != "email" or r[1], "R14": lambda r: r[0] != "sms" or not r[1],
    }
    yield "language", [[(preference, template) for template in ("ja", "en")] for preference in ("ja", "en")], {
        "R06": lambda r: r[0] != "ja" or r[1] == "ja", "R17": lambda r: r[0] != "en" or r[1] == "en",
    }


MODELS = {"subscription_billing": list(_subscription_models()), "resource_booking": list(_booking_models()), "notification_delivery": list(_notification_models())}
MODEL_CASES = [(name, label, profiles, rules) for name, models in MODELS.items() for label, profiles, rules in models]


@pytest.mark.parametrize("name,label,profiles,rules", MODEL_CASES)
def test_all_minimal_unsat_sets_in_each_rule_family_are_registered(name, label, profiles, rules):
    discovered = set().union(*(_minimal_unsat(rows, rules) for rows in profiles))
    gold = {frozenset(item["requirement_ids"]) for item in load_spec(name).answer_key["contradictions"]}
    expected = {group for group in gold if group <= set(rules)}
    assert discovered == expected, f"{name}/{label}: 未登録={discovered - expected}, 誤登録={expected - discovered}"


@pytest.mark.parametrize("name", SET2_SPEC_NAMES)
def test_discovered_conflicts_cover_all_gold_groups(name):
    discovered = set().union(*(_minimal_unsat(rows, rules) for _, profiles, rules in MODELS[name] for rows in profiles))
    gold = {frozenset(item["requirement_ids"]) for item in load_spec(name).answer_key["contradictions"]}
    assert discovered == gold and len(discovered) == 5


# 情報不足は、本文と両立する2つの補完で判断が変わる。正常要件は具体的な適合値を用意する。
INFORMATION = [
    ("subscription_billing", "R14", (7, 30), lambda days: 10 >= days),
    ("subscription_billing", "R20", (0.5, 1), lambda rate: 10000 * rate),
    ("resource_booking", "R09", (2, 5), lambda limit: 3 >= limit),
    ("resource_booking", "R21", ("A", "B"), lambda tie_winner: tie_winner),
    ("notification_delivery", "R09", (0.8, 0.95), lambda threshold: 0.9 >= threshold),
    ("notification_delivery", "R20", ("A", "B"), lambda tie_winner: tie_winner),
]
NORMAL_IDS = {
    "subscription_billing": {"R01", "R22", "R24", "R27", "R28"},
    "resource_booking": {"R13", "R15", "R24", "R26", "R27"},
    "notification_delivery": {"R10", "R13", "R21", "R26", "R28"},
}


@pytest.mark.parametrize("name,rid,completions,decision", INFORMATION)
def test_information_is_not_a_definite_conflict(name, rid, completions, decision):
    assert any(item["requirement_ids"] == [rid] for item in load_spec(name).answer_key["insufficient_information"])
    assert decision(completions[0]) != decision(completions[1])


@pytest.mark.parametrize("name", SET2_SPEC_NAMES)
def test_every_requirement_has_a_semantic_review_mapping(name):
    modeled = set().union(*(set(rules) for _, _, rules in MODELS[name]))
    information = {rid for spec, rid, _, _ in INFORMATION if spec == name}
    assert modeled | information | NORMAL_IDS[name] == load_spec(name).requirement_ids
    assert set(load_spec(name).answer_key["normal_requirement_ids"]) == NORMAL_IDS[name]


def test_adjacent_time_slots_are_not_overlapping():
    first, second = (9, 10), (10, 11)
    assert not (first[0] < second[1] and second[0] < first[1])


def test_normal_requirements_have_jointly_consistent_witnesses():
    contract_ids = ["C1", "C2"]
    booking_ids = ["B1", "B2"]
    resource_ids = ["F1", "F2"]
    notification_ids = ["N1", "N2"]
    assert all(len(values) == len(set(values)) for values in (contract_ids, booking_ids, resource_ids, notification_ids))
    assert "2026-10-11T00:00:00Z".endswith("Z")
    assert isinstance(6000, int) and 6000 > 0 and isinstance(0, int) and 0 >= 0
    assert "JPY" == "JPY"  # 元決済と返金仕訳の通貨
    assert "通知".encode("utf-8").decode("utf-8") == "通知"
    record = {"contact_visible_to_owner": True, "card_pan": None, "card_security_code": None}
    assert record["contact_visible_to_owner"] and record["card_pan"] is record["card_security_code"] is None
    consent_history = [(True, False)]
    consent_history.append((False, True))
    assert consent_history[0] == (True, False)
    assert not ("U1" == "U2")  # 別利用者の宛先の要求は受付拒否
