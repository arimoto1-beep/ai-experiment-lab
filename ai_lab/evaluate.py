"""成果物の客観評価。隠しテスト（pytest）を、作業ディレクトリの solution.py に対して実行する。

テストファイルは問題ディレクトリにあり、作業ディレクトリにはコピーしない。
AI は作業ディレクトリ内のファイルしか編集できないため、テストを見ることも書き換えることもできない。
"""

from __future__ import annotations

import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


@dataclass
class EvalResult:
    passed: bool
    tests: int = 0
    failures: int = 0
    errors: int = 0
    skipped: int = 0
    returncode: int | None = None
    timed_out: bool = False


def _read_junit(path: Path) -> tuple[int, int, int, int]:
    if not path.exists():
        return (0, 0, 0, 0)
    root = ET.parse(path).getroot()
    suites = list(root.iter("testsuite"))
    totals = [0, 0, 0, 0]
    for suite in suites:
        for index, attribute in enumerate(("tests", "failures", "errors", "skipped")):
            totals[index] += int(suite.get(attribute, "0"))
    return (totals[0], totals[1], totals[2], totals[3])


def evaluate(
    workspace: Path,
    tests_path: Path,
    *,
    output_path: Path,
    junit_path: Path,
    timeout: float = 120.0,
) -> EvalResult:
    env = dict(os.environ)
    # 作業ディレクトリを import できるようにし、評価で __pycache__ を作らない。
    env["PYTHONPATH"] = str(workspace)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    command = [
        sys.executable,
        "-m",
        "pytest",
        str(tests_path),
        "-q",
        "-p",
        "no:cacheprovider",
        f"--junitxml={junit_path}",
    ]
    try:
        proc = subprocess.run(
            command,
            cwd=workspace,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        output_path.write_text(f"評価がタイムアウトしました（{timeout} 秒）。\n", encoding="utf-8")
        return EvalResult(passed=False, timed_out=True)

    output_path.write_text(proc.stdout + proc.stderr, encoding="utf-8")
    tests, failures, errors, skipped = _read_junit(junit_path)
    passed = proc.returncode == 0 and tests > 0 and failures == 0 and errors == 0
    return EvalResult(
        passed=passed,
        tests=tests,
        failures=failures,
        errors=errors,
        skipped=skipped,
        returncode=proc.returncode,
    )
