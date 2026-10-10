"""隠しテスト（評価専用）。AI の作業ディレクトリにはコピーしない。

課題文 problem.md の仕様をそのままテストにしたもの。
"""

import pytest

from solution import parse_duration


@pytest.mark.parametrize(
    "text, expected",
    [
        ("90s", 90),
        ("1h30m", 5400),
        ("2D 3H", 2 * 86400 + 3 * 3600),
        ("30m1h", 3600 + 30 * 60),
        ("  1h  ", 3600),
        ("0s", 0),
        ("007s", 7),
        ("1h 30m", 5400),
        ("2d   3h", 2 * 86400 + 3 * 3600),
        ("1d1h1m1s", 86400 + 3600 + 60 + 1),
        ("0d0h0m0s", 0),
        ("100000d", 100000 * 86400),
        ("1M", 60),
        ("10S", 10),
        ("  90s  ", 90),
    ],
)
def test_valid_inputs(text, expected):
    result = parse_duration(text)
    assert result == expected
    assert type(result) is int


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "90",
        "h",
        "h1",
        "1.5h",
        "-1h",
        "+1h",
        "1w",
        "1ms",
        "1 h",
        "1h30",
        "1h2h",
        "1H1h",
    ],
)
def test_invalid_inputs_raise_value_error(text):
    with pytest.raises(ValueError):
        parse_duration(text)
