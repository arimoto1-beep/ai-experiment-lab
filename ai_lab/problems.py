"""課題の読み込みとプロンプトの組み立て。

課題ディレクトリの構成（problems/<名前>/）:
  problem.md       課題文（AI に渡す）
  starter/         作業ディレクトリにコピーする初期ファイル（solution.py など）
  tests/           隠しテスト（AI には渡さない。評価にだけ使う）
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

PROMPT_TEMPLATE = """以下のPython課題を解いてください。

作業ディレクトリにある solution.py を編集して、課題で指定された関数を実装してください。

制約:
- 編集するファイルは solution.py だけにしてください。新しいファイルは作らないでください。
- 作業ディレクトリの外にあるファイルは読まないでください。
- 標準ライブラリだけを使用してください。
- コードを実行する手段はありません。コードを読み直して、仕様どおりに動くか確認してください。
- 完了したら、実装の要点を3行以内で報告してください。

===== 課題 =====
{statement}
"""


@dataclass(frozen=True)
class Problem:
    name: str
    statement: str
    starter_dir: Path
    tests_path: Path


def load_problem(name: str, problems_root: Path) -> Problem:
    if not re.fullmatch(r"[a-z0-9_]+", name):
        raise ValueError(f"課題名は英小文字・数字・アンダースコアのみ使えます: {name!r}")
    base = problems_root / name
    statement_path = base / "problem.md"
    starter_dir = base / "starter"
    tests_path = base / "tests" / "test_solution.py"
    missing = [str(path) for path in (statement_path, starter_dir, tests_path) if not path.exists()]
    if missing:
        raise FileNotFoundError(f"課題ファイルが見つかりません: {', '.join(missing)}")
    return Problem(
        name=name,
        statement=statement_path.read_text(encoding="utf-8"),
        starter_dir=starter_dir,
        tests_path=tests_path,
    )


def build_prompt(problem: Problem) -> str:
    return PROMPT_TEMPLATE.format(statement=problem.statement.strip())
