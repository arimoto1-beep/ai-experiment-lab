"""Independently check every published answer against the fixed tables."""

import json
from pathlib import Path


def main() -> None:
    cases = json.loads(Path(__file__).with_name("cases.json").read_text(encoding="utf-8"))
    assert len(cases) == 8
    for case in cases:
        rows = case["rows"]
        assert len(rows) == 12 and len({r["id"] for r in rows}) == 12
        red = [r["quantity"] for r in rows if r["color"] == "赤"]
        blue = [r for r in rows if r["color"] == "青" and r["quantity"] >= 5]
        green = [r["id"] for r in rows if r["color"] == "緑" and r["quantity"] % 2 == 0]
        yellow = [r["quantity"] for r in rows if r["color"] == "黄"]
        assert red and blue and green and yellow
        assert case["answers"] == {
            "R": sum(red), "B": len(blue), "G": ",".join(sorted(green)), "Y": max(yellow)
        }
    print(f"verified {len(cases)} cases")


if __name__ == "__main__":
    main()
