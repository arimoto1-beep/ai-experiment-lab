"""Recompute the published B26 score and key totals without private raw streams."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from analyze import score
from run import cases, schedule


HERE = Path(__file__).resolve().parent


def main() -> None:
    answer = {row["id"]: row["answer"] for row in cases()}
    records = json.loads((HERE / "public-runs.json").read_text(encoding="utf-8"))
    summary = json.loads((HERE / "summary.json").read_text(encoding="utf-8"))
    assert len(records) == 40
    for index, (planned, row) in enumerate(zip(schedule(cases()), records, strict=True), 1):
        assert row["trial"] == index
        assert all(row[key] == value for key, value in planned.items())
        correct, valid, integer = score(row["response_text"], answer[row["case_id"]])
        assert (correct, valid, integer) == (row["correct"], row["format_valid"], row["parsed_integer"])
    for condition in ("A", "B"):
        selected = [row for row in records if row["condition"] == condition]
        totals = summary["conditions"][condition]
        assert len(selected) == totals["valid_trials"] == 20
        assert sum(row["correct"] for row in selected) == totals["correct"]
        assert sum(not row["format_valid"] for row in selected) == totals["format_invalid"]
        assert round(sum(row["wall_seconds"] for row in selected), 3) == totals["wall_seconds_total"]
        assert round(sum(row["api_equivalent_usd"] for row in selected), 6) == totals["api_equivalent_usd"]
        for key, value in totals["tokens"].items():
            assert sum(row["tokens"][key] for row in selected) == value
        assert sum(row["thinking_tokens"] or 0 for row in selected) == totals["thinking_tokens"]
    paired = Counter()
    for item in cases():
        for repetition in (1, 2):
            pair = {row["condition"]: row["correct"] for row in records
                    if row["case_id"] == item["id"] and row["repetition"] == repetition}
            assert set(pair) == {"A", "B"}
            paired["both_correct" if pair["A"] and pair["B"] else
                   "A_only" if pair["A"] else "B_only" if pair["B"] else "both_incorrect"] += 1
    assert dict(paired) == {key: value for key, value in summary["paired_outcomes"].items() if value}
    print(json.dumps({"verified_trials": 40, "correct_A": summary["conditions"]["A"]["correct"],
                      "correct_B": summary["conditions"]["B"]["correct"]}))


if __name__ == "__main__":
    main()
