import json
from pathlib import Path
from typing import Any

from ai_lab import cli


def _summary(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "model": "claude-haiku-5-5",
        "effort": "medium",
        "completed_runs": 3,
        "requested_runs": 3,
        "passed": 2,
        "pass_rate": 0.6667,
        "any_passed": True,
        "cli_not_ok": 0,
        "mean_wall_seconds": 12.5,
        "tokens": {"input": 300, "output": 150, "cache_read": 9000, "cache_write": 6000},
        "api_equivalent_usd_total": 0.0012,
        "api_equivalent_usd_per_pass": 0.0006,
        "cost_complete": True,
        "cli_reported_usd_total": 0.0012,
    }
    base.update(overrides)
    return base


def _write_experiment(root: Path, name: str, summary: dict[str, Any]) -> Path:
    exp_dir = root / name
    exp_dir.mkdir(parents=True)
    (exp_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
    return exp_dir


def test_dry_run_shows_the_plan_without_calling_claude(tmp_path, capsys):
    rc = cli.main(["run", "--model", "haiku", "--runs", "3", "--results-dir", str(tmp_path / "results"), "--dry-run"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "claude-haiku-5-5" in out
    assert "--effort medium" in out
    assert "--bare" not in out
    assert not (tmp_path / "results").exists()


def test_real_run_is_refused_inside_a_claude_code_session(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CLAUDECODE", "1")

    rc = cli.main(["run", "--model", "haiku", "--results-dir", str(tmp_path / "results")])

    assert rc == 2
    assert "入れ子" in capsys.readouterr().err
    assert not (tmp_path / "results").exists()


def test_unknown_model_is_rejected(tmp_path, capsys):
    rc = cli.main(["run", "--model", "sonnet", "--dry-run", "--results-dir", str(tmp_path / "results")])

    assert rc == 1
    assert "未知のモデル" in capsys.readouterr().err


def test_zero_runs_is_rejected(tmp_path, capsys):
    rc = cli.main(["run", "--runs", "0", "--dry-run", "--results-dir", str(tmp_path / "results")])

    assert rc == 1
    assert "--runs" in capsys.readouterr().err


def test_missing_claude_binary_is_reported_and_no_results_are_written(tmp_path, capsys):
    rc = cli.main(
        ["run", "--claude-bin", str(tmp_path / "no-such-claude.exe"), "--results-dir", str(tmp_path / "results")]
    )

    assert rc == 1
    assert "エラー" in capsys.readouterr().err
    assert not (tmp_path / "results").exists()


def test_report_compares_experiments_side_by_side(tmp_path, capsys):
    haiku = _write_experiment(tmp_path, "haiku_run", _summary())
    opus = _write_experiment(
        tmp_path,
        "opus_run",
        _summary(
            model="claude-opus-5-5",
            completed_runs=1,
            requested_runs=1,
            passed=1,
            pass_rate=1.0,
            api_equivalent_usd_total=0.02,
            api_equivalent_usd_per_pass=0.02,
        ),
    )

    rc = cli.main(["report", str(haiku), str(opus)])

    out = capsys.readouterr().out
    assert rc == 0
    assert "haiku_run" in out and "opus_run" in out
    assert "66.7%" in out and "100.0%" in out
    assert "0.020000" in out
    assert "API 換算" in out


def test_report_explains_an_experiment_without_summary(tmp_path, capsys):
    interrupted = tmp_path / "interrupted"
    interrupted.mkdir()

    rc = cli.main(["report", str(interrupted)])

    assert rc == 1
    assert "summary.json" in capsys.readouterr().err
