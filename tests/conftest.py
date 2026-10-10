from __future__ import annotations

import sys
from pathlib import Path

import pytest

from ai_lab import claude_cli

FAKE_CLAUDE = Path(__file__).resolve().parent / "fixtures" / "fake_claude.py"


@pytest.fixture
def fake_command() -> list[str]:
    """本物の claude の代わりに使う偽 CLI のコマンド。"""
    return [sys.executable, str(FAKE_CLAUDE)]


@pytest.fixture(autouse=True)
def _forbid_real_claude(monkeypatch: pytest.MonkeyPatch) -> None:
    """テストから本物の Claude Code CLI を起動させない（開発中の入れ子実行を防ぐ）。"""

    def _forbidden() -> list[str]:
        raise AssertionError("テスト中に本物の claude を探そうとしました。fake_command を使ってください。")

    monkeypatch.setattr(claude_cli, "find_claude_command", _forbidden)
    for name in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"):
        monkeypatch.delenv(name, raising=False)
