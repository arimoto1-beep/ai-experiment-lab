"""Independent arithmetic checks for the ten frozen answer keys."""

from __future__ import annotations

import itertools
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
EXPECTED = {row["id"]: row["answer"] for row in json.loads((HERE / "cases.json").read_text(encoding="utf-8"))}


def main() -> None:
    doors = [False] * 101
    for step in range(1, 101):
        for door in range(step, 101, step):
            doors[door] = not doors[door]
    actual = {
        "Q01": 17 + 28,
        "Q02": 48 * 3 // 4,
        "Q03": len(list(itertools.combinations(range(7), 2))),
        "Q04": (5 * 12 - 20) // 4,
        "Q05": 100 * (100 // 5),
        "Q06": sum(n % 3 == 0 or n % 5 == 0 for n in range(1, 101)),
        "Q07": sum((n % 2 == 0) != (n % 3 == 0) for n in range(1, 101)),
        "Q08": sum(p[0] != 0 and p[-1] == 0 for p in itertools.permutations((0, 1, 2, 3))),
        "Q09": sum(doors),
        "Q10": sum((n % 6 == 0 or n % 10 == 0) and n % 15 != 0 for n in range(1, 1001)),
    }
    assert actual == EXPECTED, {key: (actual.get(key), EXPECTED.get(key)) for key in EXPECTED if actual.get(key) != EXPECTED.get(key)}
    print(json.dumps({"verified": len(actual), "answers": actual}, ensure_ascii=False))


if __name__ == "__main__":
    main()
