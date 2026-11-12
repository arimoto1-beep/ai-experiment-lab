"""Restore the two #7 first artifacts from pinned Git blobs and saved patches."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
TASK = ROOT / "analysis/terminal-bench-v4.0.0"
COMMIT = "452bf305c6daa62fc59061d22133a7cbc7c1572e"
PREFIX = "tasks/react-lead-form/environment/app/"
SOURCES = {
    "A": ("rlfm-aa5796866708", "react-lead-form__8SEeuNJ"),
    "B": ("rlfm-1170a1288c0a", "react-lead-form__whpeeEE"),
}


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(TASK), *args])


def hashes(directory: Path) -> dict[str, str]:
    return {
        path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.rglob("*")) if path.is_file()
    }


def main() -> None:
    if git("rev-parse", "HEAD").decode().strip() != COMMIT:
        raise RuntimeError("official task commit changed")
    manifest = json.loads((OUT / "restoration.json").read_text(encoding="utf-8"))
    source_paths = [p.decode() for p in git("ls-tree", "-r", "--name-only", "HEAD", PREFIX).split(b"\n") if p]
    records = {}
    for label, (run_id, trial) in SOURCES.items():
        target = OUT / "restored" / label
        if target.exists():
            raise RuntimeError(f"existing restoration: {target}")
        target.mkdir(parents=True)
        for source_path in source_paths:
            destination = target / source_path.removeprefix(PREFIX)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(git("show", f"{COMMIT}:{source_path}"))
        patch = ROOT / "analysis/react-lead-form-replication-20261031/patches" / f"{run_id}.patch"
        patch_hash = hashlib.sha256(patch.read_bytes()).hexdigest()
        if patch_hash != manifest[label]["patch_sha256"]:
            raise RuntimeError(f"{label} saved patch differs from manifest")
        subprocess.run(["git", "-c", "core.autocrlf=false", "-C", str(target), "apply", "-p1", str(patch)], check=True)
        original = ROOT / "results/react_lead_form_harbor" / run_id / "jobs" / run_id / trial / "artifacts/app"
        actual, expected = hashes(target), manifest[label]["files"]
        if actual != expected:
            raise RuntimeError(f"{label} differs from frozen manifest: {set(actual.items()) ^ set(expected.items())}")
        if original.is_dir() and actual != hashes(original):
            raise RuntimeError(f"{label} differs from original local artifact")
        records[label] = {"run_id": run_id, "trial": trial, "file_count": len(actual),
                          "matches_frozen_manifest": True,
                          "matches_local_original": original.is_dir()}
    print(json.dumps(records))


if __name__ == "__main__":
    main()
