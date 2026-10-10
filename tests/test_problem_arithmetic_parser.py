"""算術課題（arithmetic_parser）の検証。

1. 参照実装が隠しテストに全件合格すること。
2. 意図的に不完全な実装（変異体）が、対応するテストで不合格になること。
3. 隠しテストの期待値を、CPython の式評価と Fraction による厳密計算で独立に検算すること。

CPython の評価は検算にだけ使います。AI の解答や隠しテストでは使いません。
"""

from __future__ import annotations

import importlib.util
import math
import re
import sys
import types
import warnings
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path

import pytest

from ai_lab.evaluate import evaluate
from ai_lab.problems import PROJECT_ROOT

HIDDEN_TESTS = PROJECT_ROOT / "problems" / "arithmetic_parser" / "tests" / "test_solution.py"
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "arithmetic"
REFERENCE = FIXTURES / "reference.py"
EVAL_BASED = FIXTURES / "eval_based.py"


def _load_hidden_tests():
    """隠しテストのモジュールを、期待値の一覧を読むためだけに読み込む。solution は仮のモジュールで代用する。"""
    stub = types.ModuleType("solution")
    stub.calculate = None
    saved = sys.modules.get("solution")
    saved_flag = sys.dont_write_bytecode
    sys.modules["solution"] = stub
    # 隠しテストの場所に __pycache__ を作らない（評価用のファイルを汚さないため）。
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location("arithmetic_hidden_tests", HIDDEN_TESTS)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = saved_flag
        if saved is None:
            sys.modules.pop("solution", None)
        else:
            sys.modules["solution"] = saved
    return module


HIDDEN = _load_hidden_tests()
VALID_CASES = HIDDEN.VALID_CASES
INVALID_CASES = HIDDEN.INVALID_CASES
SYNTAX_ERROR_WITH_ZERO_DIVISION = HIDDEN.SYNTAX_ERROR_WITH_ZERO_DIVISION
ZERO_DIVISION_CASES = HIDDEN.ZERO_DIVISION_CASES

# ---- 検算用の関数（CPython と Fraction）。解答や隠しテストでは使わない。 ----

_NUMBER = re.compile(r"[0-9]+(?:\.[0-9]+)?")
_LEADING_ZEROS = re.compile(r"(?<![0-9.])0+(?=[0-9])")


def _python_form(expression: str) -> str:
    """CPython の eval に渡せる形にする（空白を半角スペースに統一し、先頭の 0 を除く）。"""
    text = re.sub(r"\s", " ", expression).strip()
    return _LEADING_ZEROS.sub("", text)


def _compile(expression: str):
    with warnings.catch_warnings():
        # 2(3) などは CPython が警告を出しながら受理する。検算の目的では警告は不要。
        warnings.simplefilter("ignore", SyntaxWarning)
        return compile(_python_form(expression), "<expression>", "eval")


def _cpython_value(expression: str) -> float:
    return eval(_compile(expression), {"__builtins__": {}})


def _exact_value(expression: str) -> Fraction:
    rewritten = _NUMBER.sub(lambda match: f"Fraction('{match.group(0)}')", _python_form(expression))
    return eval(compile(rewritten, "<expression>", "eval"), {"__builtins__": {}, "Fraction": Fraction})


# CPython も受理してしまう不正入力と、その理由。課題文の仕様では不正なので、隠しテストでは不正として扱う。
ACCEPTED_BY_CPYTHON = {
    "1.": "CPython は 1. を浮動小数点数として受理する（仕様は小数点の後に数字を要求する）",
    ".5": "CPython は .5 を受理する（仕様は小数点の前に数字を要求する）",
    "1e3": "指数表記（仕様では不正）",
    "1e-3": "指数表記（仕様では不正）",
    "1_000": "桁区切り（仕様では不正）",
    "0x1F": "16進数（仕様では不正）",
    "1,5": "CPython はタプルとして受理する（仕様では不正）",
    "2%3": "CPython は剰余として受理する（仕様に剰余はない）",
    "1^2": "CPython は排他的論理和として受理する（仕様に ^ はない）",
    "a+1": "CPython は変数名として受理する（仕様では不正）",
    "inf": "CPython は変数名として受理する（仕様では不正）",
    "nan": "CPython は変数名として受理する（仕様では不正）",
    "1**2": "CPython は累乗として受理する（仕様に ** はない）",
    "2(3)": "CPython は関数呼び出しとして受理する（仕様では不正）",
    "(1)(2)": "CPython は関数呼び出しとして受理する（仕様では不正）",
    "()": "CPython は空のタプルとして受理する（仕様では不正）",
    "1+()": "CPython は構文として受理する（仕様では不正）",
}


@pytest.mark.parametrize("expression, expected", VALID_CASES)
def test_expected_value_matches_cpython(expression, expected):
    assert math.isclose(_cpython_value(expression), expected, rel_tol=1e-12, abs_tol=1e-15)


@pytest.mark.parametrize("expression, expected", VALID_CASES)
def test_expected_value_matches_exact_rational_arithmetic(expression, expected):
    assert math.isclose(float(_exact_value(expression)), expected, rel_tol=1e-12, abs_tol=1e-15)


@pytest.mark.parametrize("expression", INVALID_CASES)
def test_invalid_case_is_a_syntax_error_in_cpython_or_is_listed(expression):
    try:
        _compile(expression)
    except SyntaxError:
        return
    assert expression in ACCEPTED_BY_CPYTHON, f"CPython が受理するため、理由を記録してください: {expression!r}"


@pytest.mark.parametrize("expression", sorted(ACCEPTED_BY_CPYTHON))
def test_listed_cpython_acceptance_is_real(expression):
    _compile(expression)  # 一覧の項目は、本当に CPython が受理するものであること


@pytest.mark.parametrize("expression", ZERO_DIVISION_CASES)
def test_zero_division_case_is_valid_syntax_and_divides_by_zero(expression):
    code = _compile(expression)
    with pytest.raises(ZeroDivisionError):
        eval(code, {"__builtins__": {}})


@pytest.mark.parametrize("expression", SYNTAX_ERROR_WITH_ZERO_DIVISION)
def test_syntax_error_case_is_invalid_in_cpython(expression):
    with pytest.raises(SyntaxError):
        _compile(expression)


# ---- 参照実装と変異体を、実際の評価（pytest の実行）にかける。 ----

def _run_hidden_tests(source: str, base: Path, name: str):
    workspace = base / name / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "solution.py").write_text(source, encoding="utf-8")
    junit = base / name / "junit.xml"
    result = evaluate(
        workspace,
        HIDDEN_TESTS,
        output_path=base / name / "pytest_output.txt",
        junit_path=junit,
        timeout=120,
    )
    return result, junit


def _failing_tests(junit: Path) -> list[str]:
    root = ET.parse(junit).getroot()
    return [
        case.get("name", "")
        for case in root.iter("testcase")
        if case.find("failure") is not None or case.find("error") is not None
    ]


def test_reference_passes_all_hidden_tests(tmp_path):
    result, _ = _run_hidden_tests(REFERENCE.read_text(encoding="utf-8"), tmp_path, "reference")
    expected_count = (
        len(VALID_CASES)
        + len(INVALID_CASES)
        + len(SYNTAX_ERROR_WITH_ZERO_DIVISION)
        + len(ZERO_DIVISION_CASES)
        + 1  # 禁止事項の確認
    )
    assert result.passed is True
    assert result.tests == expected_count


# 変異体: 参照実装の一部分だけを書き換えたもの。置換対象は参照実装に一箇所だけあること。
_REPLACEMENTS = {
    # 優先順位が無く、四則演算を左から順に計算する
    "same_precedence": (
        '        while self._peek() in ("+", "-"):\n'
        "            op = self._take()[0]\n"
        "            node = (op, node, self._term())\n",
        '        while self._peek() in ("+", "-", "*", "/"):\n'
        "            op = self._take()[0]\n"
        "            node = (op, node, self._unary())\n",
    ),
    # 加減算が右結合
    "right_assoc": (
        "        node = self._term()\n"
        '        while self._peek() in ("+", "-"):\n'
        "            op = self._take()[0]\n"
        "            node = (op, node, self._term())\n"
        "        return node\n",
        "        node = self._term()\n"
        '        if self._peek() in ("+", "-"):\n'
        "            op = self._take()[0]\n"
        "            return (op, node, self._expression())\n"
        "        return node\n",
    ),
    # 単項演算子を受け付けない
    "no_unary": (
        '        if self._peek() in ("+", "-"):\n',
        "        if False:\n",
    ),
    # 小数を受け付けない
    "integers_only": (
        '_NUMBER = re.compile(r"[0-9]+(?:\\.[0-9]+)?")',
        '_NUMBER = re.compile(r"[0-9]+")',
    ),
    # 整数の結果を int で返す
    "int_result": (
        "    return _evaluate(_Parser(tokens).parse())\n",
        "    value = _evaluate(_Parser(tokens).parse())\n"
        "    return int(value) if value == int(value) else value\n",
    ),
    # 解析後に残ったトークンを無視する
    "trailing_ignored": (
        '        if self.pos != len(self.tokens):\n            raise ValueError("unexpected token")\n',
        "",
    ),
    # 構文を最後まで検査する前に、除数の 0 でゼロ除算を送出する
    "zero_check_at_parse_time": (
        "            node = (op, node, self._unary())\n",
        "            right = self._unary()\n"
        '            if op == "/" and right == ("num", 0.0):\n'
        '                raise ZeroDivisionError("division by zero")\n'
        "            node = (op, node, right)\n",
    ),
}

# 変異体ごとに、不合格になるべきテスト（名前の接頭辞）。
_EXPECTED_FAILURES = {
    "same_precedence": ("test_valid_expression",),
    "right_assoc": ("test_valid_expression",),
    "no_unary": ("test_valid_expression",),
    "integers_only": ("test_valid_expression",),
    "int_result": ("test_valid_expression",),
    "trailing_ignored": ("test_invalid_expression_raises_value_error",),
    "zero_check_at_parse_time": ("test_invalid_syntax_with_zero_division_raises_value_error",),
    "eval_based": (
        "test_invalid_expression_raises_value_error",
        "test_solution_does_not_use_forbidden_constructs",
    ),
}


def _mutant_source(name: str) -> str:
    if name == "eval_based":
        return EVAL_BASED.read_text(encoding="utf-8")
    old, new = _REPLACEMENTS[name]
    source = REFERENCE.read_text(encoding="utf-8")
    assert source.count(old) == 1, f"変異体 {name} の置換箇所が一意ではありません"
    return source.replace(old, new)


@pytest.mark.parametrize("name", sorted(_EXPECTED_FAILURES))
def test_incomplete_implementation_is_rejected(name, tmp_path):
    source = _mutant_source(name)
    compile(source, f"{name}.py", "exec")  # 変異体が構文として正しいこと
    result, junit = _run_hidden_tests(source, tmp_path, name)
    failing = _failing_tests(junit)
    assert result.passed is False
    for prefix in _EXPECTED_FAILURES[name]:
        assert any(case.startswith(prefix) for case in failing), f"{prefix} が不合格になりませんでした: {failing}"
