import pytest

from ai_lab.problems import PROJECT_ROOT, build_prompt, load_problem

PROBLEMS = PROJECT_ROOT / "problems"


PROBLEM_FUNCTIONS = [
    ("duration_parse", "parse_duration"),
    ("arithmetic_parser", "calculate"),
    ("inventory_allocation", "allocate_orders"),
]


@pytest.mark.parametrize("name, function", PROBLEM_FUNCTIONS)
def test_prompt_contains_the_statement_but_not_the_hidden_tests(name, function):
    prompt = build_prompt(load_problem(name, PROBLEMS))
    assert function in prompt
    assert "solution.py" in prompt
    assert "def test_" not in prompt
    assert "pytest" not in prompt


@pytest.mark.parametrize("name, function", PROBLEM_FUNCTIONS)
def test_starter_directory_holds_only_the_solution(name, function):
    problem = load_problem(name, PROBLEMS)
    assert sorted(p.name for p in problem.starter_dir.iterdir()) == ["solution.py"]
    assert function in (problem.starter_dir / "solution.py").read_text(encoding="utf-8")


def test_problem_names_must_be_plain_identifiers():
    with pytest.raises(ValueError):
        load_problem("../escape", PROBLEMS)


def test_missing_problem_is_reported():
    with pytest.raises(FileNotFoundError):
        load_problem("no_such_problem", PROBLEMS)
