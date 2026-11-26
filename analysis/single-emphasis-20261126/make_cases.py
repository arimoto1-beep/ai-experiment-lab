"""Create the fixed synthetic tables for experiment 15. Run only before preregistration."""

import json
import random
from pathlib import Path


def main() -> None:
    rng = random.Random(15036)
    cases = []
    colors = ["赤", "青", "緑", "黄"]
    for number in range(1, 9):
        while True:
            rows = [
                {"id": f"{chr(65 + i)}{number}", "color": rng.choice(colors), "quantity": rng.randint(1, 19)}
                for i in range(12)
            ]
            if (any(r["color"] == "赤" for r in rows)
                    and any(r["color"] == "青" and r["quantity"] >= 5 for r in rows)
                    and any(r["color"] == "緑" and r["quantity"] % 2 == 0 for r in rows)
                    and any(r["color"] == "黄" for r in rows)):
                break
        answers = {
            "R": sum(r["quantity"] for r in rows if r["color"] == "赤"),
            "B": sum(r["color"] == "青" and r["quantity"] >= 5 for r in rows),
            "G": ",".join(sorted(r["id"] for r in rows if r["color"] == "緑" and r["quantity"] % 2 == 0)),
            "Y": max(r["quantity"] for r in rows if r["color"] == "黄"),
        }
        cases.append({"id": f"Q{number:02d}", "rows": rows, "answers": answers})
    Path(__file__).with_name("cases.json").write_text(
        json.dumps(cases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
