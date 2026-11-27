"""Separate the executed turn from CLI modelUsage inherited by each fork."""
import argparse
import json
from decimal import Decimal

from runner import HERE, OUT, initial, read_json

PHASES = ("first", "A", "B")
FIELDS = {"input": "input_tokens", "output": "output_tokens",
          "cache_read": "cache_read_input_tokens", "cache_write": "cache_creation_input_tokens"}
RATES = {key: Decimal(value) for key, value in (
    ("input", "0.10"), ("output", "0.50"), ("cache_read", "0.01"), ("cache_write", "0.20"))}
PATH = HERE / "usage-summary.json"


def precise(value):
    return Decimal(str(value))


def api_cost(counts):
    return sum(counts[key] * RATES[key] for key in FIELDS) / 1_000_000


def compute(audit):
    public = read_json(HERE / "public-runs.json")
    totals = {p: {"calls": 0, **{key: 0 for key in FIELDS}, "thinking": 0,
                  "api_usd": Decimal(0), "cli_usd": Decimal(0)} for p in PHASES}
    for row in public:
        for phase in PHASES:
            record = row[phase]
            if not record or not record["valid"]:
                raise ValueError("This usage audit requires a complete valid run")
            parent = row["first"] if phase != "first" else None
            current = {key: record["tokens"][key] - (parent["tokens"][key] if parent else 0)
                       for key in FIELDS}
            cli_usd = precise(record["cli_reported_usd"]) - (precise(parent["cli_reported_usd"]) if parent else 0)
            assert all(value >= 0 for value in current.values()) and sum(
                current[key] for key in ("input", "cache_read", "cache_write")) <= 100_000
            assert 0 <= record["thinking_tokens"] <= current["output"]
            cost = api_cost(current)
            assert abs(cli_usd - cost) < Decimal("0.000000001")
            if audit:
                raw = (OUT / row["id"] / f"{phase}-stream.jsonl").read_text(encoding="utf-8")
                assert initial.sha(raw) == record["raw_sha256"]
                result = initial.claude_cli.parse_output(raw)
                assert result["num_turns"] == 1
                usage = result["usage"]
                assert all(current[key] == usage[field] for key, field in FIELDS.items())
                assert record["thinking_tokens"] == usage["output_tokens_details"]["thinking_tokens"]
                write = usage["cache_creation"]
                assert write["ephemeral_5m_input_tokens"] == 0
                assert write["ephemeral_1h_input_tokens"] == current["cache_write"]
            phase_total = totals[phase]
            phase_total["calls"] += 1
            phase_total["thinking"] += record["thinking_tokens"]
            for key, value in current.items():
                phase_total[key] += value
            phase_total["api_usd"] += cost
            phase_total["cli_usd"] += cli_usd
    totals["all"] = {key: sum(totals[p][key] for p in PHASES) for key in totals["first"]}
    for total in totals.values():
        for key in ("api_usd", "cli_usd"):
            total[key] = float(round(total[key], 8))
    return {"basis": "first as reported; fork minus its parent, checked against result.usage",
            "cache_write_ttl_verified": "1h",
            "usd_per_million_tokens": {key: float(value) for key, value in RATES.items()},
            "current_turn_totals": totals}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("audit", "verify"))
    mode = parser.parse_args().mode
    computed = compute(mode == "audit")
    if mode == "audit":
        initial.dump(PATH, computed)
    else:
        assert read_json(PATH) == computed
    print(json.dumps(computed, ensure_ascii=False))
