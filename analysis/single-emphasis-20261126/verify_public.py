"""Recompute B36 scores and main totals from published files alone."""

import json
from collections import Counter
from pathlib import Path

from analyze import KEYS, score
from run import cases, schedule

HERE = Path(__file__).resolve().parent


def main() -> None:
    by_id = {row["id"]: row for row in cases()}
    records = json.loads((HERE / "public-runs.json").read_text(encoding="utf-8"))
    summary = json.loads((HERE / "summary.json").read_text(encoding="utf-8"))
    plan = schedule(cases())
    assert len(records) == summary["completed_trials"] <= len(plan) == summary["planned_trials"]
    for index, (expected, row) in enumerate(zip(plan, records), 1):
        assert row["trial"] == index and all(row[k] == value for k, value in expected.items())
        if row["valid"]:
            assert row["status"] == "ok" and row["model_check"] == "match"
            assert (row["scores"], row["exact_format"]) == score(
                row["response_text"], by_id[row["case_id"]]["answers"]
            )
    assert summary["valid_trials"] == sum(r["valid"] for r in records)
    assert summary["invalid_trials"] == sum(not r["valid"] for r in records)
    assert summary["unrun_trials"] == len(plan) - len(records)
    for condition in ("A", "B"):
        selected = [r for r in records if r["condition"] == condition and r["valid"]]
        reported = summary["conditions"][condition]
        assert len(selected) == reported["valid_trials"]
        assert {key: sum(r["scores"][key] for r in selected) for key in KEYS} == reported["instruction_correct"]
        assert sum(sum(r["scores"][key] for key in KEYS[1:]) for r in selected) == reported["other_correct"]
        assert 3 * len(selected) == reported["other_possible"]
        assert sum(all(r["scores"].values()) for r in selected) == reported["all_four_correct"]
        assert sum(r["exact_format"] for r in selected) == reported["exact_format"]
        assert round(sum(r["wall_seconds"] for r in selected), 3) == reported["wall_seconds_total"]
        assert round(sum(r["api_equivalent_usd"] or 0 for r in selected), 6) == reported["api_equivalent_usd"]
        for key in reported["tokens"]:
            assert sum((r["tokens"] or {}).get(key) or 0 for r in selected) == reported["tokens"][key]
    pairs = Counter()
    differences = []
    for item in cases():
        for repetition in (1, 2):
            pair = {r["condition"]: r for r in records if r["case_id"] == item["id"]
                    and r["repetition"] == repetition and r["valid"]}
            if set(pair) != {"A", "B"}:
                continue
            a = sum(pair["A"]["scores"][k] for k in KEYS[1:])
            b = sum(pair["B"]["scores"][k] for k in KEYS[1:])
            pairs["A_higher" if a > b else "B_higher" if b > a else "equal"] += 1
            differences.append(b - a)
    assert len(differences) == summary["complete_pairs"]
    assert sum(differences) == summary["paired_B_minus_A_total"]
    assert pairs == {k: v for k, v in summary["paired_outcomes"].items() if v}
    print(json.dumps({"verified_trials": len(records), "complete_pairs": len(differences),
                      "other_A": summary["conditions"]["A"]["other_correct"],
                      "other_B": summary["conditions"]["B"]["other_correct"]}))


if __name__ == "__main__":
    main()
