import json
import shutil
from pathlib import Path

import pytest

from ai_lab import agentic_dev, cli
from ai_lab.claude_cli import CliRun


ROOT = Path(__file__).resolve().parent.parent
REFERENCE = ROOT / "tests" / "fixtures" / "agentic_reference"


@pytest.mark.parametrize("task", agentic_dev.TASKS)
def test_bundle_is_frozen_and_reference_passes_all_tests(task, tmp_path, monkeypatch):
    root, hashes = agentic_dev.validate_bundle(task)
    assert len(hashes) >= 7
    monkeypatch.syspath_prepend(str(REFERENCE / task))
    assert pytest.main([str(root / "public_tests"), str(root / "hidden_tests"),
                        "-q", "-p", "no:cacheprovider", f"--basetemp={tmp_path / 'pytest'}"]) == 0


def test_changed_bundle_is_rejected_before_a_model_run(tmp_path):
    from shutil import copytree

    copytree(agentic_dev.BUNDLES / "parcel_manifest", tmp_path / "parcel_manifest")
    copytree(agentic_dev.BUNDLES / "room_booking", tmp_path / "room_booking")
    (tmp_path / "parcel_manifest" / "problem.md").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="固定ファイル"):
        agentic_dev.validate_bundle("parcel_manifest", tmp_path)


@pytest.mark.parametrize("task,model,expected", [
    ("parcel_manifest", "haiku45", "claude-haiku-4-5"),
    ("room_booking", "haiku", "claude-haiku-5-5"),
])
def test_agentic_dry_run_has_same_scaffold_and_makes_no_results(tmp_path, capsys, task, model, expected):
    result_dir = tmp_path / "results"
    assert cli.main(["agentic", "--task", task, "--model", model,
                     "--results-dir", str(result_dir), "--dry-run"]) == 0
    output = capsys.readouterr().out
    assert expected in output and "max-turns: 20" in output
    assert "target=/work" in output and "非公開テスト" in output
    assert not result_dir.exists()


def test_no_container_stops_before_result_dir(tmp_path, monkeypatch):
    config = agentic_dev.AgenticConfig("parcel_manifest", "claude-haiku-5-5", "medium", 1, 30,
                                       tmp_path / "results", docker_bin="missing-docker-executable")
    with pytest.raises(RuntimeError, match="Docker"):
        agentic_dev.run(config)
    assert not config.results_dir.exists()


def test_container_mounts_exclude_repository_and_hidden_tests(tmp_path):
    config = agentic_dev.AgenticConfig("parcel_manifest", "claude-haiku-5-5", "medium", 1, 30,
                                       tmp_path / "results")
    work = tmp_path / "trial" / "workspace"
    hidden = agentic_dev.BUNDLES / "parcel_manifest" / "hidden_tests"
    model_cmd = agentic_dev._docker_prefix(config, work, "trial", ipc="test-ipc")
    worker_cmd = agentic_dev._docker_prefix(config, work, "worker", role="worker", ipc="test-ipc")
    grade_cmd = agentic_dev._docker_prefix(config, work, "grade", grader=True,
                                          hidden=hidden, output=tmp_path)
    assert str(hidden) not in " ".join(model_cmd)
    assert str(ROOT) not in " ".join(model_cmd).replace(str(work), "")
    assert not any("target=/work" in item for item in model_cmd)
    assert any("target=/work" in item for item in worker_cmd)
    assert any("target=/work/public_tests,readonly" in item for item in worker_cmd)
    assert not any("target=/home/lab/.claude" in item for item in worker_cmd)
    assert worker_cmd[worker_cmd.index("--network") + 1] == "none"
    assert model_cmd[model_cmd.index("--network") + 1] == "bridge"
    assert grade_cmd[grade_cmd.index("--network") + 1] == "none"
    for command in (model_cmd, worker_cmd, grade_cmd):
        assert command[command.index("--user") + 1] == "1000:1000"
        assert command[command.index("--cap-drop") + 1] == "ALL"
        assert command[command.index("--security-opt") + 1] == "no-new-privileges"
        assert command[command.index("--memory-swap") + 1] == "4g"
    assert any("target=/hidden,readonly" in item for item in grade_cmd)
    assert "none" in grade_cmd


def test_history_extracts_failed_test_and_revision():
    def row(kind, blocks):
        return json.dumps({"type": kind, "message": {"content": blocks}})

    stream = "\n".join([
        row("assistant", [{"type": "tool_use", "id": "r", "name": "Read", "input": {"file_path": "src/x.py"}}]),
        row("assistant", [{"type": "tool_use", "id": "e", "name": "Edit", "input": {"file_path": "src/x.py"}}]),
        row("assistant", [{"type": "tool_use", "id": "t", "name": "Bash", "input": {"command": agentic_dev.PUBLIC_COMMAND}}]),
        row("user", [{"type": "tool_result", "tool_use_id": "t", "content": "1 failed"}]),
        row("assistant", [{"type": "tool_use", "id": "e2", "name": "Edit", "input": {"file_path": "src/x.py"}}]),
    ])
    events, counts = agentic_dev._events(stream)
    assert len(events) == 5
    assert counts == {"reads": 1, "edits": 2, "test_runs": 1,
                      "failed_test_runs": 1, "edits_after_failed_test": 1}


def test_runner_records_isolated_trial_without_calling_a_model(tmp_path, monkeypatch):
    config = agentic_dev.AgenticConfig("parcel_manifest", "claude-haiku-5-5", "medium", 1, 30,
                                       tmp_path / "results")
    monkeypatch.setattr(agentic_dev, "_check_runtime", lambda _: ("sha256:fixed-image", "sha256:fixed-worker"))
    monkeypatch.setattr(agentic_dev, "_check_auth", lambda _: {"version": "fake", "auth_method": "claude.ai"})
    monkeypatch.setattr(agentic_dev, "_start_worker", lambda *args: None)
    monkeypatch.setattr(agentic_dev, "_stop_container", lambda *args: None)
    monkeypatch.setattr(agentic_dev, "_remove_ipc", lambda *args: None)
    monkeypatch.setattr(agentic_dev, "_grade", lambda *args: {
        "passed": True, "tests": 10, "failures": 0, "errors": 0, "skipped": 0,
        "timed_out": False, "returncode": 0,
    })

    def fake_invoke(command, args, *, cwd, env, timeout):
        workspace = Path(cwd)
        assert command[0] == "docker" and "target=/hidden" not in " ".join(command)
        assert "sha256:fixed-image" in command
        assert sorted(path.name for path in workspace.iterdir()) == ["public_tests", "src"]
        assert not list(workspace.rglob("__pycache__"))
        shutil.copytree(REFERENCE / "parcel_manifest" / "parcel_manifest",
                        workspace / "src" / "parcel_manifest", dirs_exist_ok=True)
        tool_use = {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "mcp__lab__run_public_tests", "id": "test", "input": {}}
        ]}}
        tool_result = {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "test", "content": "10 passed"}
        ]}}
        result = {"type": "result", "subtype": "success", "num_turns": 2,
                  "modelUsage": {"claude-haiku-5-5": {"inputTokens": 100, "outputTokens": 50,
                                                     "cacheReadInputTokens": 0, "cacheCreationInputTokens": 0}}}
        stream = "\n".join(json.dumps(row) for row in (tool_use, tool_result, result))
        return CliRun(0, stream, "", 1.5, False)

    monkeypatch.setattr(agentic_dev.claude_cli, "invoke", fake_invoke)
    output = agentic_dev.run(config, log=lambda _: None)
    trial = json.loads((output / "trial_01" / "trial.json").read_text(encoding="utf-8"))
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert trial["outcome"] == "pass" and trial["workflow_complete"]
    assert trial["workflow"]["test_runs"] == 1
    assert trial["evaluation"]["tests"] == 10
    assert trial["tokens"]["input"] == 100
    assert trial["cost"]["api_equivalent_usd"] is not None
    assert summary["passed"] == 1 and summary["workflow_complete_runs"] == 1
    assert summary["cost_complete"]
