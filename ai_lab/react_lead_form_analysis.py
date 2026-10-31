"""Read-only diagnostic analysis of one official react-lead-form Harbor trial.

Only writes derived files under that trial's agent directory. The official
verifier and reward are never changed.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
from pathlib import Path

from ai_lab.react_lead_form_harbor import TASK


STATUS = {"success": "成功", "failure": "失敗", "undetermined": "前段の失敗により判定不能"}
GROUPS = {
    "form_ui": ("form field", "form fields", "label", "labels", "placeholder", "visible field", "success state",
                "transitions to success"),
    "validation": ("invalid email", "invalid lead", "without consent", "disposable",
                   "reject", "rejects", "rejected", "rejection", "contradictory",
                   "conflict", "identity_conflict"),
    "payload_attribution": ("source submission", "source expected", "campaign", "utm",
                            "gclid", "attribution", "facebook", "crm status"),
    "timestamp": ("timestamp", "submittedat", "clock", "first-contact"),
    "ledgers_reconciliation": ("ledger", "ledgers", "crm", "crm_leads", "incomplete",
                               "incomplete_leads", "reconciliation", "lead_sources",
                               "source group", "source groups", "duplicate"),
    "batch_atomicity": ("batch", "atomic", "atomicity", "unwritable", "multi-file"),
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _matches_group(message: str, keywords: tuple[str, ...]) -> bool:
    """Match whole terms, so 'malformed' is not a form failure."""
    lowered = message.lower()
    return any(re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", lowered)
               for word in keywords)


def _tests(log: str, reward: float) -> list[dict[str, str]]:
    source = TASK / "tests"
    names: list[str] = []
    for filename in ("lead-form.test.tsx", "lead-form-verifier.test.tsx"):
        content = (source / filename).read_text(encoding="utf-8")
        names.extend(re.findall(r"\bit\(\s*['\"](.+?)['\"]", content))
    failed = set(re.findall(r"(?m)^\s*FAIL\s+tests/[^\n]+?\s+>\s+[^\n]+?\s+>\s+([^\n]+)$", log))
    counts = re.findall(r"Tests\s+(?:(\d+) failed\s*\|\s*)?(\d+) passed\s*\((\d+)\)", log)
    complete = reward == 1 or any(int(total) == len(names) and int(fail or 0) == len(failed)
                                  and int(passed) + int(fail or 0) == len(names)
                                  for fail, passed, total in counts)
    return [{"name": name, "status": "failure" if name in failed else
             "success" if complete else "undetermined",
             "status_ja": STATUS["failure" if name in failed else "success" if complete else "undetermined"],
             "evidence": "Vitest FAIL line" if name in failed else
             "complete Vitest case count" if complete else "suite completion unconfirmed"}
            for name in names]


def analyze_trial(trial_dir: Path) -> dict:
    trial_dir = trial_dir.resolve()
    agent = trial_dir / "agent"
    verifier = trial_dir / "verifier"
    reward = float((verifier / "reward.txt").read_text(encoding="utf-8").strip())
    log = (verifier / "test-stdout.txt").read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
    tests = _tests(log, reward)
    tail = log.rsplit("\nFAIL\n", 1)[-1] if "\nFAIL\n" in log else ""
    failures = re.findall(r"(?m)^\s+- (.+)$", tail)
    groups = {}
    for group, keywords in GROUPS.items():
        matched = [item for item in tests if item["status"] == "failure" and
                   _matches_group(item["name"], keywords)]
        messages = [message for message in failures if _matches_group(message, keywords)]
        state = "success" if reward == 1 else "failure" if matched or messages else "undetermined"
        groups[group] = {"status": state, "status_ja": STATUS[state],
                         "failed_vitest_cases": [item["name"] for item in matched],
                         "official_failure_messages": messages}

    initial = TASK / "environment" / "app"
    final = trial_dir / "artifacts" / "app"
    initial_files = {p.relative_to(initial).as_posix(): p for p in initial.rglob("*") if p.is_file()}
    final_files = {p.relative_to(final).as_posix(): p for p in final.rglob("*") if p.is_file()}
    changes = []
    patch = []
    for name in sorted(initial_files.keys() | final_files.keys()):
        before = initial_files[name].read_bytes() if name in initial_files else b""
        after = final_files[name].read_bytes() if name in final_files else b""
        if before == after:
            continue
        changes.append({"path": name, "before_sha256": _sha(before) if name in initial_files else None,
                        "after_sha256": _sha(after) if name in final_files else None,
                        "kind": "added" if name not in initial_files else "removed" if name not in final_files else "modified"})
        patch.extend(difflib.unified_diff(before.decode("utf-8", errors="replace").splitlines(True),
                                          after.decode("utf-8", errors="replace").splitlines(True),
                                          fromfile="initial/" + name, tofile="final/" + name))
    (agent / "changes.patch").write_text("".join(patch), encoding="utf-8")

    operations_file = agent / "worker-operations.jsonl"
    operations = [json.loads(line) for line in operations_file.read_text(encoding="utf-8").splitlines()] if operations_file.exists() else []
    report = {
        "trial_id": trial_dir.name,
        "official_reward": reward,
        "official_log": str(verifier / "test-stdout.txt"),
        "status_meaning": STATUS,
        "vitest_cases": tests,
        "feature_groups": groups,
        "official_failure_messages": failures,
        "changed_files": changes,
        "command_runs": [row for row in operations if row.get("tool") == "run_command"],
        "operation_counts": {"total": len(operations), "denied": sum(row.get("status") == "denied" for row in operations)},
    }
    (agent / "partial-analysis.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def analyze_job(job_dir: Path) -> list[dict]:
    return [analyze_trial(path) for path in job_dir.iterdir()
            if path.is_dir() and (path / "verifier" / "reward.txt").exists()]
