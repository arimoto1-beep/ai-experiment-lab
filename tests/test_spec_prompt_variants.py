import hashlib
import json

import pytest

from ai_lab import claude_cli, spec_benchmark
from ai_lab.spec_scoring import ALL_SPEC_NAMES, MINIMALITY_INSTRUCTIONS, PROMPT_TEMPLATE, build_prompt, load_spec


def _json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_original_baseline_template_is_unchanged():
    # 追加実装前の既存テンプレートから取得。現テンプレートを使って期待値を再生成しない。
    assert hashlib.sha256(PROMPT_TEMPLATE.encode("utf-8")).hexdigest() == "4829d8f2f73b192bc991de73b7f0bbc0cbfcecba4bd319e051ca7d2ea3e6aa66"


@pytest.mark.parametrize("name", ALL_SPEC_NAMES)
def test_default_and_explicit_baseline_match_the_previous_prompt(name):
    case = load_spec(name)
    previous = PROMPT_TEMPLATE.format(statement=case.statement.strip())
    assert build_prompt(case) == previous
    assert build_prompt(case, "baseline") == previous


@pytest.mark.parametrize("name", ALL_SPEC_NAMES)
def test_minimality_only_adds_generic_instructions_and_preserves_json_and_statement(name):
    case = load_spec(name)
    baseline = build_prompt(case)
    minimality = build_prompt(case, "minimality")
    added = "\n" + MINIMALITY_INSTRUCTIONS + "\n"
    assert minimality.count(added) == 1
    assert minimality.replace(added, "", 1) == baseline
    assert minimality.index(MINIMALITY_INSTRUCTIONS) < minimality.index("===== 仕様書 =====")
    assert minimality.split("===== 仕様書 =====", 1)[1] == baseline.split("===== 仕様書 =====", 1)[1]
    for text in ("同一対象・同一状況", "要件IDだけで", "1つずつ取り除いた", "最小ではない", "条件が不明", "長文出力は不要", "簡潔な理由"):
        assert text in MINIMALITY_INSTRUCTIONS
    assert "requirement_ids" in minimality and "insufficient_information" in minimality
    assert all(rid not in MINIMALITY_INSTRUCTIONS for rid in case.requirement_ids)
    assert all(spec not in MINIMALITY_INSTRUCTIONS for spec in ALL_SPEC_NAMES)
    for finding in case.answer_key["contradictions"]:
        assert finding["reason"] not in minimality
        if "condition" in finding:
            assert finding["condition"] not in minimality


@pytest.mark.parametrize("variant", ["baseline", "minimality"])
def test_cli_records_actual_prompt_variant_and_hash_with_fake_cli(tmp_path, fake_command, monkeypatch, variant, capsys):
    case = load_spec("subscription_billing")
    response = {"contradictions": [
        {"requirement_ids": item["requirement_ids"], "reason": "模擬回答の理由"}
        for item in case.answer_key["contradictions"]
    ], "insufficient_information": [{"requirement_ids": ["R14"], "reason": "日数が未指定"}]}
    monkeypatch.setenv("FAKE_CLAUDE_RESPONSE", json.dumps(response))
    arglog = tmp_path / "args.jsonl"
    monkeypatch.setenv("FAKE_CLAUDE_ARGLOG", str(arglog))
    monkeypatch.setattr(claude_cli, "find_claude_command", lambda: fake_command)
    args = ["run", "--set", "set2", "--spec", case.name, "--model", "haiku", "--effort", "medium",
            "--runs", "2", "--results-dir", str(tmp_path / "results")]
    if variant == "minimality":
        args.extend(["--prompt-variant", variant])
    assert spec_benchmark.main(args) == 0
    exp = next((tmp_path / "results").iterdir())
    assert f"_{variant}_" in exp.name
    prompt = build_prompt(case, variant)
    calls = [json.loads(line) for line in arglog.read_text(encoding="utf-8").splitlines()]
    assert len(calls) == len({call["cwd"] for call in calls}) == 2
    for call in calls:
        assert call["argv"][1] == prompt and call["cwd_entries"] == []
        assert call["argv"] == spec_benchmark.build_args("claude-haiku-5-5", "medium", prompt)
        assert call["argv"][call["argv"].index("--tools") + 1] == ""
        assert call["argv"][call["argv"].index("--disallowedTools") + 1] == "*"
    for filename in ("experiment.json", "summary.json"):
        record = _json(exp / filename)
        assert record["prompt_variant"] == variant
        assert record["prompt_sha256"][case.name] == hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    for trial in ("trial_001", "trial_002"):
        record = _json(exp / trial / "trial.json")
        assert record["prompt_variant"] == variant and record["model_check"]["status"] == "match"
        assert record["scoring"]["metrics"]["f1"] == 1
        assert record["scoring"]["information_findings"] == response["insufficient_information"]
        assert record["cost"]["api_equivalent_usd"] == pytest.approx(0.000465)
    assert "prompt_variant" in capsys.readouterr().out


@pytest.mark.parametrize("variant", [None, "minimality"])
def test_dry_run_shows_selected_variant_without_model_calls(tmp_path, capsys, variant):
    args = ["run", "--set", "set2", "--dry-run", "--results-dir", str(tmp_path / "results")]
    if variant:
        args.extend(["--prompt-variant", variant])
    assert spec_benchmark.main(args) == 0
    assert f"prompt_variant={variant or 'baseline'}" in capsys.readouterr().out
    assert not (tmp_path / "results").exists()


def test_report_distinguishes_variants_and_reads_legacy_results(tmp_path, fake_command, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_RESPONSE", '{"contradictions": []}')
    case = load_spec("subscription_billing")
    experiments = []
    for variant in ("baseline", "minimality"):
        experiments.append(spec_benchmark.run_benchmark(
            [case], model_id="claude-haiku-5-5", model_label="haiku", effort="medium", runs=1,
            timeout=60, results_dir=tmp_path / "results", claude_command=fake_command,
            prompt_variant=variant, log=lambda _: None,
        ))
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    old_summary = _json(experiments[0] / "summary.json")
    del old_summary["prompt_variant"]
    (legacy / "summary.json").write_text(json.dumps(old_summary), encoding="utf-8")
    before = (legacy / "summary.json").read_bytes()
    report = spec_benchmark.build_report([legacy, *experiments])
    column = report.splitlines()[0].split().index("prompt_variant")
    for path, variant in ((legacy, "baseline"), (experiments[0], "baseline"), (experiments[1], "minimality")):
        overall = next(line for line in report.splitlines() if line.startswith(path.name + " ") and " ALL " in line)
        assert overall.split()[column] == variant
    assert (legacy / "summary.json").read_bytes() == before


def test_unknown_variant_is_rejected_before_authentication_or_results(tmp_path, fake_command, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("不正なvariantで認証確認を呼んではいけません")

    monkeypatch.setattr(claude_cli, "preflight", forbidden)
    with pytest.raises(ValueError, match="未知のプロンプト"):
        spec_benchmark.run_benchmark(
            [load_spec("subscription_billing")], model_id="claude-haiku-5-5", model_label="haiku", effort="medium",
            runs=1, timeout=60, results_dir=tmp_path / "results", claude_command=fake_command, prompt_variant="unknown",
        )
    assert not (tmp_path / "results").exists()
