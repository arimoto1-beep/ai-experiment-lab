"""検証用の正解実装。隠しテストが仕様どおりかを確かめるためだけに使う（AI には渡さない）。"""

import re

_UNIT_SECONDS = {"d": 86400, "h": 3600, "m": 60, "s": 1}
_ELEMENT = re.compile(r"[ ]*([0-9]+)([dhms])", re.IGNORECASE)


def parse_duration(text: str) -> int:
    rest = text.strip()
    if not rest:
        raise ValueError("empty duration")
    total = 0
    seen = set()
    pos = 0
    while pos < len(rest):
        match = _ELEMENT.match(rest, pos)
        if match is None:
            raise ValueError(f"invalid duration: {text!r}")
        unit = match.group(2).lower()
        if unit in seen:
            raise ValueError(f"duplicate unit: {text!r}")
        seen.add(unit)
        total += int(match.group(1)) * _UNIT_SECONDS[unit]
        pos = match.end()
    return total
