"""不完全な実装（変異体）: 入力を検査せず、Python の eval() に任せている。"""


def calculate(expression: str) -> float:
    return float(eval(expression))
