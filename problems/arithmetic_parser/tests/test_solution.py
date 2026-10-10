"""隠しテスト（評価専用）。AI の作業ディレクトリにはコピーしない。

期待値は課題文の規則から導いたもの。CPython の式評価と Fraction による厳密計算で独立に検算している
（tests/test_problem_arithmetic_parser.py を参照）。
"""

import ast
from pathlib import Path

import pytest

import solution
from solution import calculate

REL_TOL = 1e-9
ABS_TOL = 1e-12

FORBIDDEN_MODULES = {"ast", "sympy", "numexpr", "simpleeval", "asteval"}
FORBIDDEN_NAMES = {"eval", "exec", "compile", "__import__"}
FORBIDDEN_ATTRIBUTES = {"eval", "exec"}

DEEP = 50  # 括弧の入れ子の段数（課題文の要求）

VALID_CASES = [
    # 基本の四則演算
    ("1+2", 3.0),
    ("5-3", 2.0),
    ("4*6", 24.0),
    ("9/3", 3.0),
    ("7/2", 3.5),
    ("0+0", 0.0),
    ("1.5+2.25", 3.75),
    ("0.5*4", 2.0),
    ("10.0/4", 2.5),
    ("100-0.5", 99.5),
    ("1/4", 0.25),
    ("1/3", 1 / 3),
    ("0.1+0.2", 0.3),
    ("0.1*3", 0.3),
    # 優先順位
    ("1+2*3", 7.0),
    ("2*3+1", 7.0),
    ("10-2*3", 4.0),
    ("2*3+4*5", 26.0),
    ("1+2*3-4/2", 5.0),
    ("2+3*4-5", 9.0),
    ("8/4+6/3", 4.0),
    ("1-2*3/6", 0.0),
    ("2*(3+4)*5", 70.0),
    ("10/4*2-3*(2-5)/-3", 2.0),
    # 左結合
    ("8-4-2", 2.0),
    ("8/4/2", 1.0),
    ("100/10/5", 2.0),
    ("7/2*2", 7.0),
    ("1-2-3", -4.0),
    ("2/4*8", 4.0),
    ("10-5+3", 8.0),
    ("1+2-3+4", 4.0),
    # 括弧
    ("(1+2)*3", 9.0),
    ("2*(3+4)", 14.0),
    ("((1+2)*(3+4))", 21.0),
    ("(((5)))", 5.0),
    ("(2+3)*(4-1)/(5)", 3.0),
    ("((2))*((3))", 6.0),
    ("(1+(2*(3+(4))))", 15.0),
    ("(10-(4-2))", 8.0),
    ("100/(5*(2+2))", 5.0),
    ("((8-4)-2)", 2.0),
    ("((1+2)*3-(4/2))*(-1)", -7.0),
    ("2*(3+4*(5-1))/4", 9.5),
    ("(1.5+2.5)*(3-0.5)/2", 5.0),
    # 単項演算子
    ("-1", -1.0),
    ("+1", 1.0),
    ("-(1+2)", -3.0),
    ("-(-(1+2))", 3.0),
    ("--3", 3.0),
    ("+-3", -3.0),
    ("-+3", -3.0),
    ("1--1", 2.0),
    ("1+-1", 0.0),
    ("1-+1", 0.0),
    ("2*-3", -6.0),
    ("-2*3", -6.0),
    ("-2*-3", 6.0),
    ("4/-2", -2.0),
    ("-6/3", -2.0),
    ("-2+3", 1.0),
    ("-2*3+1", -5.0),
    ("+(2)*3", 6.0),
    ("2*+(3)", 6.0),
    ("3*(-(2+1))", -9.0),
    ("-(2*3)/(-2)", 3.0),
    ("-0.5", -0.5),
    ("-1.5*-2", 3.0),
    ("1 - - 1", 2.0),
    ("-(3-5)*(2+-1)", 2.0),
    ("-0", 0.0),
    # 空白（半角スペース・タブ・改行）
    (" 1 + 2 * 3 ", 7.0),
    ("( 1 + 2 ) * 3", 9.0),
    ("1\t+\t2", 3.0),
    ("  -  4  ", -4.0),
    ("1 +\n2", 3.0),
    ("\t(2 * 3)\n", 6.0),
    ("  7  ", 7.0),
    # 数値の表記
    ("0", 0.0),
    ("007", 7.0),
    ("00.5", 0.5),
    ("0.5", 0.5),
    ("0/5", 0.0),
    ("0*(-3)", 0.0),
    # 境界値
    ("1000000*1000000", 1e12),
    ("0.001*0.001", 1e-6),
    ("1/1000", 0.001),
    ("2*2*2*2*2*2*2*2*2*2*1", 1024.0),
    ("(" * DEEP + "1" + ")" * DEEP, 1.0),
    ("-(" * DEEP + "1" + ")" * DEEP, 1.0),  # 符号を50回反転させると正になる
    ("+".join(["1"] * 200), 200.0),
]

INVALID_CASES = [
    # 空・空白だけ
    "",
    "   ",
    "\t\n",
    # 演算子・数値・括弧の欠落や過剰
    "1+",
    "1-",
    "1*",
    "1/",
    "1+2*",
    "+",
    "-",
    "*",
    "/",
    "*2",
    "/2",
    "+-",
    "--",
    "(-)",
    "1+*2",
    "1*/2",
    "1**2",
    "1 2",
    "1 + 2 3",
    "2(3)",
    "(1)(2)",
    # 括弧の対応の不一致・空の括弧
    "(1+2",
    "1+2)",
    ")1(",
    "()",
    "(+)",
    "(1+)",
    "1+()",
    "((1)",
    "2 * (3 + 4",
    "1 + 2 )",
    # 小数・指数・桁区切り・16進数
    "1.",
    ".5",
    "1..2",
    "1.2.3",
    "1. 5",
    "1 .5",
    "1e3",
    "1e-3",
    "1_000",
    "0x1F",
    # 課題文に無い文字
    "1,5",
    "2%3",
    "1^2",
    "a+1",
    "1+2=3",
    "1+2;",
    "inf",
    "nan",
    "１+２",  # 全角の数字
    "1＋2",  # 全角の演算子
]

# 構文が不正な式。ゼロ除算に見える部分を含むが、ValueError でなければならない。
SYNTAX_ERROR_WITH_ZERO_DIVISION = [
    "1/0+",
    "1/0 2",
    "1/0*",
    "1/(0",
    "1/0)",
    "1/(0+)",
]

# 構文は正しく、除数が 0 になる式。
ZERO_DIVISION_CASES = [
    "1/0",
    "0/0",
    "1/0.0",
    "1/(2-2)",
    "1/-0",
    "1/(-0.0)",
    "10/(5-5)*3",
    "(1/0)",
    "1/(1/0)",
    "5/(2*0)",
    "1/(0.5-0.5)",
    "2-1/0",
    "-1/(0)",
]


@pytest.mark.parametrize("expression, expected", VALID_CASES)
def test_valid_expression(expression, expected):
    result = calculate(expression)
    assert isinstance(result, float)
    assert result == pytest.approx(expected, rel=REL_TOL, abs=ABS_TOL)


@pytest.mark.parametrize("expression", INVALID_CASES)
def test_invalid_expression_raises_value_error(expression):
    with pytest.raises(ValueError):
        calculate(expression)


@pytest.mark.parametrize("expression", SYNTAX_ERROR_WITH_ZERO_DIVISION)
def test_invalid_syntax_with_zero_division_raises_value_error(expression):
    with pytest.raises(ValueError):
        calculate(expression)


@pytest.mark.parametrize("expression", ZERO_DIVISION_CASES)
def test_zero_division_raises_zero_division_error(expression):
    with pytest.raises(ZeroDivisionError):
        calculate(expression)


def test_solution_does_not_use_forbidden_constructs():
    source = Path(solution.__file__).read_text(encoding="utf-8")
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [alias.name for alias in node.names if alias.name.split(".")[0] in FORBIDDEN_MODULES]
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] in FORBIDDEN_MODULES:
                found.append(node.module)
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            found.append(f"{node.id}（{node.lineno} 行目）")
        elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_ATTRIBUTES:
            found.append(f".{node.attr}（{node.lineno} 行目）")
    assert not found, "禁止事項に触れています: " + ", ".join(found)
