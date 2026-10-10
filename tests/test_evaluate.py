from pathlib import Path

from ai_lab.evaluate import evaluate
from ai_lab.problems import PROJECT_ROOT

FIXTURES = PROJECT_ROOT / "tests" / "fixtures"
REFERENCE_SOLUTION = FIXTURES / "reference" / "duration_parse.py"
NAIVE_SOLUTION = FIXTURES / "naive" / "duration_parse.py"
HIDDEN_TESTS = PROJECT_ROOT / "problems" / "duration_parse" / "tests" / "test_solution.py"
VALID_CASES = 15  # problems/duration_parse/tests/test_solution.py の正常系
INVALID_CASES = 14  # 同・異常系


def _workspace(tmp_path: Path, source: str | None) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    if source is not None:
        (workspace / "solution.py").write_text(source, encoding="utf-8")
    return workspace


def _evaluate(workspace: Path, tmp_path: Path, timeout: float = 120.0):
    return evaluate(
        workspace,
        HIDDEN_TESTS,
        output_path=tmp_path / "pytest_output.txt",
        junit_path=tmp_path / "junit.xml",
        timeout=timeout,
    )


def test_reference_solution_passes_all_hidden_tests(tmp_path):
    workspace = _workspace(tmp_path, REFERENCE_SOLUTION.read_text(encoding="utf-8"))
    result = _evaluate(workspace, tmp_path)
    assert result.passed is True
    assert result.tests == VALID_CASES + INVALID_CASES
    assert result.failures == 0 and result.errors == 0


def test_naive_solution_fails_hidden_tests(tmp_path):
    workspace = _workspace(tmp_path, NAIVE_SOLUTION.read_text(encoding="utf-8"))
    result = _evaluate(workspace, tmp_path)
    assert result.passed is False
    assert result.failures > 0


def test_missing_solution_is_a_failure(tmp_path):
    result = _evaluate(_workspace(tmp_path, None), tmp_path)
    assert result.passed is False
    assert result.errors > 0


def test_syntax_error_is_a_failure(tmp_path):
    result = _evaluate(_workspace(tmp_path, "def parse_duration(:\n"), tmp_path)
    assert result.passed is False


def test_evaluation_timeout_is_reported(tmp_path):
    result = _evaluate(_workspace(tmp_path, "while True:\n    pass\n"), tmp_path, timeout=5)
    assert result.timed_out is True
    assert result.passed is False


def test_evaluation_leaves_the_workspace_untouched(tmp_path):
    workspace = _workspace(tmp_path, REFERENCE_SOLUTION.read_text(encoding="utf-8"))
    _evaluate(workspace, tmp_path)
    assert sorted(p.name for p in workspace.iterdir()) == ["solution.py"]
