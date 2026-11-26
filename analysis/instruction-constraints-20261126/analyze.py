"""Check private streams and summarize or verify the public B45 records."""
import argparse
import json
from collections import Counter
from statistics import mean

from design import HERE, LEVELS, OTHER, dump, fingerprints, prompt, read, schedule, score, select, sha
from run import OUT, claude_cli, expected_lock, inspect, main_lock


def metric(rows):
    valid = [row for row in rows if row["valid"]]
    return {
        "attempted": len(rows), "valid": len(valid),
        "checks": {key: sum(r["scores"][key] for r in valid) for key in ("length", *OTHER, "format")},
        "other_passed": sum(sum(r["scores"][key] for key in OTHER) for r in valid),
        "other_possible": len(OTHER) * len(valid),
        "all_eight": sum(all(r["scores"][key] for key in ("length", *OTHER)) for r in valid),
        "all_eight_and_format": sum(all(r["scores"].values()) for r in valid),
        "wall_seconds_mean": round(mean(r["wall_seconds"] for r in rows), 3) if rows else None,
        "wall_seconds_total": round(sum(r["wall_seconds"] for r in rows), 3),
        "usage": {key: measured([r["tokens"].get(key) if r["tokens"] else None for r in rows])
                  for key in ("input", "output", "cache_read", "cache_write")},
        "thinking_tokens": measured([r["thinking_tokens"] for r in rows]),
        "api_equivalent_usd": measured([r["api_equivalent_usd"] for r in rows], 6),
        "cli_reported_usd": measured([r["cli_reported_usd"] for r in rows], 6),
    }


def measured(values, digits=None):
    known = [value for value in values if value is not None]
    total = sum(known)
    return {"known": len(known), "total": (round(total, digits) if digits is not None else total) if known else None}


def summarize(phase, rows, audit):
    result = {key: audit[key] for key in ("planned", "attempted", "invalid", "unrun", "stop_reason")}
    if phase == "pilot":
        result["levels"] = {str(level): metric([r for r in rows if r["level"] == level]) for level in LEVELS}
        result["selection"] = select(rows, audit["stop_reason"])
        return result
    result["conditions"] = {c: metric([r for r in rows if r["condition"] == c]) for c in "AB"}
    pairs = []
    for index in range(0, len(rows) - 1, 2):
        a, b = sorted(rows[index:index + 2], key=lambda r: r["condition"])
        if not (a["valid"] and b["valid"]):
            continue
        points = {r["condition"]: sum(r["scores"][key] for key in OTHER) for r in (a, b)}
        pairs.append({"case": a["case"], "rep": a["rep"], **points, "B_minus_A": points["B"] - points["A"]})
    count = Counter("B_higher" if p["B_minus_A"] > 0 else "A_higher" if p["B_minus_A"] < 0 else "equal" for p in pairs)
    result["pairs"] = pairs
    result["pair_counts"] = {key: count[key] for key in ("A_higher", "B_higher", "equal")}
    result["paired_B_minus_A_total"] = sum(p["B_minus_A"] for p in pairs)
    return result


def audit_private(phase, by_id, plan):
    dest = OUT / phase
    frozen = read(dest / "frozen.json")
    progress = read(dest / "progress.json")
    assert frozen["fingerprints"] == fingerprints() and frozen["plan"] == plan
    assert progress["finished"] and frozen["preflight"]["auth"] == "claude.ai"
    rows, sessions = [], set()
    duplicates = 0
    for record, item in zip(progress["records"], plan):
        trial = dest / f'trial_{item["trial"]:02}'
        text, raw, err = [(trial / name).read_text(encoding="utf-8") for name in
                          ("prompt.txt", "stream.jsonl", "stderr.txt")]
        case = by_id[item["case"]]
        assert text == prompt(case, item["level"], item["condition"])
        run = claude_cli.CliRun(returncode=record["returncode"], stdout=raw, stderr=err,
                                wall_seconds=record["wall_seconds"], timed_out=record["timeout"])
        checked = inspect(run)
        session = checked["session_sha256"]
        if session:
            if session in sessions:
                checked["valid"] = False
                duplicates += 1
            sessions.add(session)
        assert record == {**item, **checked, "prompt_sha256": sha(text)}
        if record["valid"]:
            scores = score(record["response"], case, item["level"])
        else:
            scores = None
        public = {**record, "scores": scores}
        if not record["valid"]:
            public["response"] = None
        rows.append(public)
    assert len(rows) == len(progress["records"])
    audit = {
        "fingerprints": frozen["fingerprints"], "preflight": frozen["preflight"],
        "planned": len(plan), "attempted": len(rows), "invalid": sum(not r["valid"] for r in rows),
        "unrun": len(plan) - len(rows), "stop_reason": progress["stop_reason"],
        "unique_sessions": len(sessions), "duplicate_sessions": duplicates,
        "tool_calls": sum(r["tool_calls"] for r in rows),
        "permission_denials": sum(r["permission_denials"] for r in rows),
        "model_matches": sum(r["model_check"] == "match" for r in rows),
    }
    return rows, audit


def verify_cases(cases):
    all_cases = cases["pilot"] + cases["main"]
    assert len(cases["pilot"]) == 3 and len(cases["main"]) == 10
    assert len({c["id"] for c in all_cases}) == len(all_cases)
    for case in all_cases:
        assert len(set(case["pool"])) == len(case["pool"]) == 108
        for level in LEVELS:
            text = case["witnesses"][str(level)]
            assert all(score(text, case, level).values())
            # Independently check a full construction against the position and letter constraints.
            words = []
            for i, (line, rule) in enumerate(zip(text.splitlines(), case["lines"], strict=True), 1):
                label, payload = line.split(": ")
                row = payload.split(" ")
                assert label == str(i) and len(row) == level
                assert row[0] == rule["first"] and row[-1] == rule["last"]
                assert row[rule["position"] - 1] == rule["anchor"]
                assert len([w for w in row if w[0] == rule["initial"]]) == LEVELS[level]
                assert rule["forbidden"] not in payload
                words.extend(row)
            assert len(set(words)) == len(words) and set(words) <= set(case["pool"])


def execute(mode, phase):
    cases = read(HERE / "cases.json")
    verify_cases(cases)
    if mode == "cases":
        print("Verified 39 constructive witnesses.")
        return
    if mode == "lock":
        dump(HERE / "main-lock.json", expected_lock())
        print("Main design locked from pilot results.")
        return
    by_id = {c["id"]: c for c in cases[phase]}
    level = main_lock()["level"] if phase == "main" else None
    plan = schedule(phase, cases, level)
    if mode == "audit":
        rows, audit = audit_private(phase, by_id, plan)
        dump(HERE / f"{phase}-runs.json", rows)
        dump(HERE / f"{phase}-audit.json", audit)
        dump(HERE / f"{phase}-summary.json", summarize(phase, rows, audit))
    else:
        rows = read(HERE / f"{phase}-runs.json")
        audit = read(HERE / f"{phase}-audit.json")
        assert audit["fingerprints"] == fingerprints()
        assert audit["planned"] == len(plan) and audit["attempted"] == len(rows)
        assert audit["unrun"] == len(plan) - len(rows) and audit["invalid"] == sum(not r["valid"] for r in rows)
        for row, item in zip(rows, plan):
            assert all(row[key] == value for key, value in item.items())
            case = by_id[row["case"]]
            assert row["prompt_sha256"] == sha(prompt(case, row["level"], row["condition"]))
            if row["valid"]:
                assert row["scores"] == score(row["response"], case, row["level"])
            else:
                assert row["scores"] is None and row["response"] is None
        assert read(HERE / f"{phase}-summary.json") == json.loads(json.dumps(summarize(phase, rows, audit)))
    print(phase, audit["attempted"], "attempted,", audit["invalid"], "invalid,", audit["unrun"], "unrun")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("cases", "audit", "verify", "lock"))
    parser.add_argument("phase", nargs="?", choices=("pilot", "main"), default="pilot")
    args = parser.parse_args()
    execute(args.mode, args.phase)
