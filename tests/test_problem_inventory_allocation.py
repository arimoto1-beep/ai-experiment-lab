"""在庫引当課題の品質検証。実モデルは使用しない。"""

from __future__ import annotations

import ast
import importlib.util
import itertools
import json
import sys
import types
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

import pytest

from ai_lab import claude_cli
from ai_lab.evaluate import evaluate
from ai_lab.experiment import ExperimentConfig, run_experiment
from ai_lab.problems import PROJECT_ROOT

PROBLEM = PROJECT_ROOT / "problems" / "inventory_allocation"
HIDDEN_TESTS = PROBLEM / "tests" / "test_solution.py"
STARTER = PROBLEM / "starter" / "solution.py"
REFERENCE = PROJECT_ROOT / "tests" / "fixtures" / "inventory" / "reference.py"
HIDDEN_COUNT = 36


def _load_case_tables():
    stub = types.ModuleType("solution")
    stub.allocate_orders = None
    saved = sys.modules.get("solution")
    saved_flag = sys.dont_write_bytecode
    sys.modules["solution"] = stub
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location("inventory_hidden_tests", HIDDEN_TESTS)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = saved_flag
        if saved is None:
            sys.modules.pop("solution", None)
        else:
            sys.modules["solution"] = saved
    return [case for group in (module.NORMAL_CASES, module.FIFO_CASES, module.DUPLICATE_CASES,
                              module.ATOMIC_CASES, module.COMBINED_CASES) for case in group]


CASES = _load_case_tables()


def _exhaustive_expected(stock, orders):
    """全受付パターンの列挙で検算する。参照実装の逐次引当処理は使わない。

    優先度・受付順に並べた受付可否の列を、True が先になる順で列挙する。
    最初の実現可能な列は、先の注文の受付を後の注文のために覆さない仕様と等価。
    ケースの注文数は最大5なので列挙は最大32通り。
    """
    priorities = sorted({order["priority"] for order in orders}, reverse=True)
    pending = [order for priority in priorities for order in orders if order["priority"] == priority]
    for flags in itertools.product((True, False), repeat=len(pending)):
        demand = Counter()
        for take, order in zip(flags, pending):
            if take:
                for item in order["items"]:
                    demand[item["sku"]] += item["quantity"]
        if all(quantity <= stock.get(sku, 0) for sku, quantity in demand.items()):
            return {
                "accepted": [order["id"] for take, order in zip(flags, pending) if take],
                "rejected": [order["id"] for take, order in zip(flags, pending) if not take],
                "remaining": {sku: quantity - demand[sku] for sku, quantity in stock.items()},
            }
    raise AssertionError("全拒否のパターンは必ず実現可能")


@pytest.mark.parametrize("name,stock,orders,accepted,rejected,remaining", CASES,
                         ids=[case[0] for case in CASES])
def test_fixed_expectations_match_exhaustive_search(name, stock, orders, accepted, rejected, remaining):
    assert _exhaustive_expected(stock, orders) == {
        "accepted": accepted, "rejected": rejected, "remaining": remaining,
    }


# 参照実装に1つだけ不具合を戻し、他の不具合に隠れず検出できることを確認する。
# 初期実装がこの4つの置換だけで再現できることも下で確認する。
BUGS = {
    "fifo": (
        '    pending = sorted(orders, key=lambda order: -order["priority"])\n',
        '    pending = sorted(orders, key=lambda order: (-order["priority"], order["id"]))\n',
        "test_fifo[scarce_stock]",
    ),
    "duplicate_quantities": (
        '        sku = item["sku"]\n'
        '        required[sku] = required.get(sku, 0) + item["quantity"]\n',
        '        required[item["sku"]] = item["quantity"]\n',
        "test_duplicate_quantities[total_exceeds_stock]",
    ),
    "atomicity": (
        '    if any(inventory.get(sku, 0) < quantity for sku, quantity in required.items()):\n'
        '        return False\n'
        '    for sku, quantity in required.items():\n',
        '    for sku, quantity in required.items():\n'
        '        if inventory.get(sku, 0) < quantity:\n'
        '            return False\n',
        "test_rejection_is_atomic[followup_uses_unspent_stock]",
    ),
    "input_mutation": (
        "    inventory = stock.copy()\n",
        "    inventory = stock\n",
        "test_stock_is_unchanged[accepted]",
    ),
}


def _with_bugs(names):
    source = REFERENCE.read_text(encoding="utf-8")
    for name in names:
        old, new, _ = BUGS[name]
        assert source.count(old) == 1, f"{name} の置換箇所が一意ではありません"
        source = source.replace(old, new)
    return source


def _evaluate_source(source, base):
    workspace = base / "workspace"
    workspace.mkdir()
    (workspace / "solution.py").write_text(source, encoding="utf-8")
    junit = base / "junit.xml"
    result = evaluate(workspace, HIDDEN_TESTS, output_path=base / "pytest_output.txt", junit_path=junit)
    cases = list(ET.parse(junit).getroot().iter("testcase"))
    failed = {case.get("name") for case in cases
              if case.find("failure") is not None or case.find("error") is not None}
    assert result.tests == HIDDEN_COUNT
    assert result.errors == result.skipped == 0
    assert sorted(path.name for path in workspace.iterdir()) == ["solution.py"]
    return result, failed


def test_reference_passes_all_hidden_tests(tmp_path):
    result, failed = _evaluate_source(REFERENCE.read_text(encoding="utf-8"), tmp_path)
    assert result.passed and result.failures == 0
    assert not failed


def test_starter_detects_all_four_bugs_and_preserves_normal_behavior(tmp_path):
    source = STARTER.read_text(encoding="utf-8")
    # 冒頭の説明文以外に、想定した4つ以外のコード差分がないこと。
    expected = ast.parse(_with_bugs(BUGS))
    actual = ast.parse(source)
    assert ast.dump(ast.Module(body=expected.body[1:], type_ignores=[])) == ast.dump(
        ast.Module(body=actual.body[1:], type_ignores=[]))
    result, failed = _evaluate_source(source, tmp_path)
    assert not result.passed
    assert {bug[2] for bug in BUGS.values()} <= failed
    assert not any(name.startswith("test_normal[") for name in failed)


@pytest.mark.parametrize("name", sorted(BUGS))
def test_each_bug_is_independently_detected(name, tmp_path):
    source = _with_bugs([name])
    compile(source, f"{name}.py", "exec")
    result, failed = _evaluate_source(source, tmp_path)
    assert not result.passed
    assert BUGS[name][2] in failed
    # 単独の不具合が、他の3つの代表テストを失敗させないこと。
    assert not ({bug[2] for key, bug in BUGS.items() if key != name} & failed)
    assert not any(case.startswith("test_normal[") for case in failed)


@pytest.mark.parametrize("model", ["haiku", "opus"])
def test_fake_cli_receives_only_starter_and_statement(model, tmp_path, fake_command, monkeypatch):
    arglog = tmp_path / "args.jsonl"
    monkeypatch.setenv("FAKE_CLAUDE_ARGLOG", str(arglog))
    invoke = claude_cli.invoke

    def inspect_invoke(command, args, *, cwd, env, timeout):
        workspace = Path(cwd)
        assert sorted(path.name for path in workspace.iterdir()) == ["solution.py"]
        assert (workspace / "solution.py").read_bytes() == STARTER.read_bytes()
        assert args[args.index("--tools") + 1] == "Read,Write,Edit"
        assert "FAKE_CLAUDE_SOLUTION" not in env
        prompt = args[args.index("-p") + 1]
        assert "allocate_orders" in prompt
        for private_marker in ("def test_", "reference.py", "FIFO_CASES", str(HIDDEN_TESTS), str(REFERENCE)):
            assert private_marker not in prompt
        # 参照実装をコピーするのは偽CLIだけ。モデルへの配布を再現する部分には含めない。
        fake_env = dict(env)
        fake_env["FAKE_CLAUDE_SOLUTION"] = str(REFERENCE)
        return invoke(command, args, cwd=cwd, env=fake_env, timeout=timeout)

    monkeypatch.setattr(claude_cli, "invoke", inspect_invoke)
    config = ExperimentConfig(
        problem="inventory_allocation", model_id=f"claude-{model}-5-5", model_label=model,
        effort="medium", runs=1, timeout=60, results_dir=(tmp_path / "results").resolve(),
        problems_root=PROJECT_ROOT / "problems",
    )
    exp_dir = run_experiment(config, fake_command, log=lambda _: None)
    trial = json.loads((exp_dir / "trial_01" / "trial.json").read_text(encoding="utf-8"))
    assert trial["outcome"] == "pass"
    assert trial["evaluation"]["tests"] == HIDDEN_COUNT
    calls = [json.loads(line) for line in arglog.read_text(encoding="utf-8").splitlines()]
    assert len(calls) == 1
    assert calls[0]["argv"][calls[0]["argv"].index("--model") + 1] == config.model_id
