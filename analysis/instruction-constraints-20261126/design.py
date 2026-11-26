"""Fixed B45 prompt, scoring, scheduling, and pilot decision."""
import hashlib
import json
import re
from collections import Counter
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LEVELS = {8: 2, 11: 3, 14: 4}
OTHER = ("pool", "first", "last", "anchor", "initial", "forbidden", "unique")
EMPHASIS = "【絶対に守ってください】"
MODEL = "claude-haiku-5-5"
EFFORT = "medium"
BUDGET = "0.05"
TRIAL_SECONDS = 90
DEADLINE = {"pilot": 480, "main": 1200}
FROZEN = ("protocol.md", "cases.json", "design.py", "run.py", "analyze.py",
          "../../ai_lab/claude_cli.py", "../../ai_lab/review_perspectives.py",
          "../../ai_lab/experiment.py", "../../ai_lab/pricing.py")


def sha(data):
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path, value):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    tmp.replace(path)


def fingerprints():
    # Git checkout line endings may differ. The recorded hashes use UTF-8 text with LF.
    return {name: sha((HERE / name).read_text(encoding="utf-8")) for name in FROZEN}


def prompt(case, level, condition):
    emphasis = EMPHASIS if condition == "B" else ""
    lines = [
        "展示の4区画に置くキーワード列を作ってください。自然な文章にする必要はありません。",
        "回答は 1: から 4: の順に各1行、コロンと各単語の間は半角スペース1つ。説明やコードブロックは書かないでください。次の8指示をすべて満たしてください。",
        f"1. {emphasis}どの行も、行番号を除いてちょうど {level} 語にしてください。",
        "2. 各単語は下の候補に完全一致する英小文字の単語を使ってください。",
        "3. 各行の最初に指定した先頭語を置いてください。",
        "4. 各行の最後に指定した末尾語を置いてください。",
        "5. 各行の指定位置に指定語を置いてください。位置は先頭語を1語目として数えます。",
        f"6. 各行で指定の文字から始まる単語をちょうど {LEVELS[level]} 語入れてください。",
        "7. 各行では禁止文字を含む単語を使わないでください。",
        "8. 全4行を通して、同じ単語は2回以上使わないでください。",
        "",
        "行 | 先頭語 | 末尾語 | 指定位置と指定語 | 頭文字 | 禁止文字",
    ]
    for i, rule in enumerate(case["lines"], 1):
        lines.append(f'{i} | {rule["first"]} | {rule["last"]} | {rule["position"]}={rule["anchor"]} | {rule["initial"]} | {rule["forbidden"]}')
    return "\n".join(lines + ["", "候補: " + " ".join(case["pool"])])


def score(response, case, level):
    text_lines = (response or "").strip().splitlines()
    matches = [re.fullmatch(r"([1-4]):[ \t]*(.*)", line.strip()) for line in text_lines]
    labels = Counter(m[1] for m in matches if m)
    rows = {int(m[1]): m[2].split() for m in matches if m and labels[m[1]] == 1}
    nonempty = all(rows.get(i) for i in range(1, 5))
    if not nonempty:
        return dict.fromkeys(("length", *OTHER, "format"), False)
    words = [word for i in range(1, 5) for word in rows[i]]
    pool = set(case["pool"])
    checks = {"length": all(len(rows[i]) == level for i in rows),
              "pool": all(word in pool for word in words),
              "unique": len(set(words)) == len(words),
              "format": text_lines == [f"{i}: " + " ".join(rows[i]) for i in range(1, 5)]
              and all(re.fullmatch(r"[a-z]+", word) for word in words)}
    for key in ("first", "last", "anchor", "initial", "forbidden"):
        checks[key] = True
    for i, rule in enumerate(case["lines"], 1):
        row = rows[i]
        checks["first"] &= row[0] == rule["first"]
        checks["last"] &= row[-1] == rule["last"]
        pos = rule["position"] - 1
        checks["anchor"] &= len(row) > pos and row[pos] == rule["anchor"]
        checks["initial"] &= sum(w.startswith(rule["initial"]) for w in row) == LEVELS[level]
        checks["forbidden"] &= all(rule["forbidden"] not in w for w in row)
    return checks


def schedule(phase, cases, level=None):
    plan = []
    for index, case in enumerate(cases[phase]):
        if phase == "pilot":
            for offset in range(3):
                plan.append((case["id"], list(LEVELS)[(offset + index) % 3], 1, "A"))
        else:
            for rep in (1, 2):
                order = "AB" if (index + rep) % 2 else "BA"
                plan.extend((case["id"], level, rep, cond) for cond in order)
    return [dict(trial=i, case=case, level=level, rep=rep, condition=cond)
            for i, (case, level, rep, cond) in enumerate(plan, 1)]


def select(pilot, stop_reason):
    by_level = {}
    for level in LEVELS:
        valid = [row for row in pilot if row["level"] == level and row["valid"]]
        by_level[level] = dict(valid=len(valid), passed=sum(sum(r["scores"][k] for k in OTHER) for r in valid),
                               possible=len(OTHER) * len(valid))
    eligible = {level: Fraction(row["passed"], row["possible"])
                for level, row in by_level.items() if row["valid"] >= 2}
    in_range = {level: rate for level, rate in eligible.items() if Fraction(35, 100) <= rate <= Fraction(90, 100)}
    options = in_range or eligible
    allow = stop_reason not in {"authentication", "model_mismatch", "isolation", "session_missing"}
    level = min(options, key=lambda n: (abs(options[n] - Fraction(7, 10)), (11, 8, 14).index(n))) if allow and options else None
    return {"level": level, "target_range_met": level in in_range, "pilot_by_level": by_level}
