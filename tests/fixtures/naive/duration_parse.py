"""検証用の不完全な実装（素朴な正規表現で拾うだけ）。隠しテストが不正入力を見逃さないことを確かめるために使う。"""

import re

_UNIT_SECONDS = {"d": 86400, "h": 3600, "m": 60, "s": 1}


def parse_duration(text: str) -> int:
    total = 0
    for number, unit in re.findall(r"([0-9]+)([dhmsDHMS])", text):
        total += int(number) * _UNIT_SECONDS[unit.lower()]
    return total
