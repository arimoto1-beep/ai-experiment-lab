"""検証用の正解実装（AI には渡さない）。隠しテストが仕様どおりかを確かめるためだけに使う。

tests/test_problem_arithmetic_parser.py は、この中の一部の行を置き換えて変異体（不完全な実装）を作るので、
置き換え対象の行は変えないこと。
"""

import re

_NUMBER = re.compile(r"[0-9]+(?:\.[0-9]+)?")
_OPERATORS = "+-*/()"
_WHITESPACE = " \t\r\n"


def _tokenize(text: str) -> list[tuple[str, str]]:
    tokens = []
    pos = 0
    while pos < len(text):
        char = text[pos]
        if char in _WHITESPACE:
            pos += 1
        elif char in _OPERATORS:
            tokens.append((char, char))
            pos += 1
        else:
            match = _NUMBER.match(text, pos)
            if match is None:
                raise ValueError(f"unexpected character {char!r}")
            tokens.append(("number", match.group(0)))
            pos = match.end()
    return tokens


class _Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def _peek(self):
        return self.tokens[self.pos][0] if self.pos < len(self.tokens) else None

    def _take(self):
        token = self.tokens[self.pos]
        self.pos += 1
        return token

    def parse(self):
        node = self._expression()
        if self.pos != len(self.tokens):
            raise ValueError("unexpected token")
        return node

    def _expression(self):
        node = self._term()
        while self._peek() in ("+", "-"):
            op = self._take()[0]
            node = (op, node, self._term())
        return node

    def _term(self):
        node = self._unary()
        while self._peek() in ("*", "/"):
            op = self._take()[0]
            node = (op, node, self._unary())
        return node

    def _unary(self):
        if self._peek() in ("+", "-"):
            op = self._take()[0]
            return ("u" + op, self._unary())
        return self._primary()

    def _primary(self):
        kind = self._peek()
        if kind == "number":
            return ("num", float(self._take()[1]))
        if kind == "(":
            self._take()
            node = self._expression()
            if self._peek() != ")":
                raise ValueError("missing ')'")
            self._take()
            return node
        raise ValueError("expected a number or '('")


def _evaluate(node) -> float:
    kind = node[0]
    if kind == "num":
        return node[1]
    if kind == "u+":
        return _evaluate(node[1])
    if kind == "u-":
        return -_evaluate(node[1])
    op, left, right = node
    a = _evaluate(left)
    b = _evaluate(right)
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if b == 0:
        raise ZeroDivisionError("division by zero")
    return a / b


def calculate(expression: str) -> float:
    tokens = _tokenize(expression)
    if not tokens:
        raise ValueError("empty expression")
    return _evaluate(_Parser(tokens).parse())
