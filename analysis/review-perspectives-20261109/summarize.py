"""Print read-only trial metrics and the reviewers' finding locations."""

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "results" / "review_perspectives_20261109"
AGGREGATE = {}
PUBLIC_REVIEWS = []


def report_object(text):
    decoder = json.JSONDecoder()
    for offset, character in enumerate(text):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[offset:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and "findings" in value:
            return value
    return None


for task in ("react", "parcel"):
    rows = [json.loads(p.read_text(encoding="utf-8")) for p in (ROOT / task).glob("*/run.json")]
    sessions = []
    tools_used = set()
    for path in (ROOT / task).glob("*/run.json"):
        result = json.loads(path.read_text(encoding="utf-8"))
        PUBLIC_REVIEWS.append({key: result[key] for key in
                               ("task", "phase", "index", "run_id", "result_text")})
        stream = path.with_name("stream.jsonl").read_text(encoding="utf-8")
        for line in reversed(stream.splitlines()):
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "result":
                if event.get("session_id"):
                    sessions.append(event["session_id"])
                break
        history = json.loads(path.with_name("history.json").read_text(encoding="utf-8"))
        tools_used.update(e["tool"] for e in history["events"] if e["kind"] == "tool_use")
    print(task, "runs", len(rows))
    shutil.copyfile(ROOT / task / "generated-perspectives.json",
                    Path(__file__).parent / f"perspectives-{task}.json")
    shutil.copyfile(ROOT / task / "frozen-inputs.json",
                    Path(__file__).parent / f"inputs-{task}.json")
    AGGREGATE[task] = {"runs": len(rows), "sessions": len(sessions),
                       "unique_sessions": len(set(sessions)),
                       "tools_used": sorted(tools_used), "methods": {}}
    for method in ("A", "B", "C", "C_design"):
        selected = sorted((x for x in rows if x["phase"] == method), key=lambda x: x["index"])
        tokens = {key: sum((x["tokens"] or {}).get(key, 0) for x in selected)
                  for key in ("input", "output", "cache_read", "cache_write")}
        print(method, "runs", len(selected), "USD", round(sum(x["cost"]["api_equivalent_usd"] for x in selected), 8),
              "CLI seconds", round(sum(x["cli_seconds"] for x in selected), 3),
              "tokens", tokens, "thinking", sum(x["thinking_tokens"] or 0 for x in selected))
        AGGREGATE[task]["methods"][method] = {
            "runs": len(selected),
            "api_equivalent_usd": round(sum(x["cost"]["api_equivalent_usd"] for x in selected), 8),
            "cli_seconds": round(sum(x["cli_seconds"] for x in selected), 3),
            "wall_seconds": round(sum(x["wall_seconds"] for x in selected), 3),
            "tokens": tokens,
            "thinking_tokens": sum(x["thinking_tokens"] or 0 for x in selected),
            "statuses": [x["status"] for x in selected],
            "model_checks": [x["model_check"]["status"] for x in selected],
            "code_unchanged": all(x["code_unchanged"] for x in selected),
        }
        for x in selected:
            result = report_object(x["result_text"] or "")
            print("  ", x["run_id"], x["status"], x["model_check"]["status"],
                  "unchanged", x["code_unchanged"], "findings",
                  [f.get("location", "")[:100] for f in result["findings"]] if result else "designer")

(Path(__file__).parent / "metrics.json").write_text(
    json.dumps(AGGREGATE, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
(Path(__file__).parent / "reviews.json").write_text(
    json.dumps(sorted(PUBLIC_REVIEWS, key=lambda x: (x["task"], x["phase"], x["index"])),
               ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
