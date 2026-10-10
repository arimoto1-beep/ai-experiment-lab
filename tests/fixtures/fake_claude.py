"""テスト専用の偽 Claude Code CLI。実際のモデルは呼び出さない。

開発中は Claude Code の入れ子実行を避けるため、テストはこのスクリプトだけを使う。
環境変数で振る舞いを切り替える:
  FAKE_CLAUDE_SOLUTION    作業ディレクトリの solution.py にコピーするファイル（未指定なら何も書かない）
  FAKE_CLAUDE_AUTH        `auth status` が返す authMethod（既定: claude.ai）
  FAKE_CLAUDE_LOGGED_OUT  設定されていれば `auth status` が未ログインを返す
  FAKE_CLAUDE_AUTH_SLEEP  `auth status` の待ち秒数（起動確認のタイムアウトの試験用）
  FAKE_CLAUDE_EXIT        本体実行の終了コード（既定: 0）
  FAKE_CLAUDE_SLEEP       本体実行の待ち秒数（タイムアウトの試験用）
  FAKE_CLAUDE_OUTPUT      json（既定）または text（JSON 以外を返す試験用）
  FAKE_CLAUDE_ARGLOG      受け取った引数・作業ディレクトリ・環境の要約を追記する JSON Lines ファイル
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path


def _flag_value(argv: list[str], flag: str) -> str | None:
    if flag in argv:
        index = argv.index(flag)
        if index + 1 < len(argv):
            return argv[index + 1]
    return None


def main(argv: list[str]) -> int:
    if argv[:2] == ["auth", "status"]:
        time.sleep(float(os.environ.get("FAKE_CLAUDE_AUTH_SLEEP", "0")))
        if os.environ.get("FAKE_CLAUDE_LOGGED_OUT"):
            print("Not logged in")
            return 1
        print(json.dumps({"loggedIn": True, "authMethod": os.environ.get("FAKE_CLAUDE_AUTH", "claude.ai")}))
        return 0
    if argv == ["--version"]:
        print("9.9.9 (Claude Code)")
        return 0

    model = _flag_value(argv, "--model") or "unknown-model"
    arglog = os.environ.get("FAKE_CLAUDE_ARGLOG")
    if arglog:
        record = {
            "argv": argv,
            "cwd": os.getcwd(),
            "env": {
                "ANTHROPIC_API_KEY": "ANTHROPIC_API_KEY" in os.environ,
                "CLAUDE_CODE_USE_BEDROCK": "CLAUDE_CODE_USE_BEDROCK" in os.environ,
            },
        }
        with open(arglog, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    sleep_seconds = float(os.environ.get("FAKE_CLAUDE_SLEEP", "0"))
    if sleep_seconds:
        time.sleep(sleep_seconds)

    solution = os.environ.get("FAKE_CLAUDE_SOLUTION")
    if solution:
        shutil.copyfile(solution, Path.cwd() / "solution.py")

    exit_code = int(os.environ.get("FAKE_CLAUDE_EXIT", "0"))
    if os.environ.get("FAKE_CLAUDE_OUTPUT", "json") == "text":
        print("これはJSONではありません")
        return exit_code

    # 数値はテスト用の固定値。実際のモデルの使用量ではない。
    usage = {
        "input_tokens": 100,
        "output_tokens": 50,
        "cache_read_input_tokens": 3000,
        "cache_creation_input_tokens": 2000,
    }
    payload = {
        "type": "result",
        "subtype": "success" if exit_code == 0 else "error_during_execution",
        "is_error": exit_code != 0,
        "duration_ms": 4321,
        "duration_api_ms": 4000,
        "num_turns": 3,
        "result": "実装しました。",
        "session_id": "fake-session",
        "total_cost_usd": 0.000465,
        "usage": usage,
        "modelUsage": {
            model: {
                "inputTokens": 100,
                "outputTokens": 50,
                "cacheReadInputTokens": 3000,
                "cacheCreationInputTokens": 2000,
                "costUSD": 0.000465,
            }
        },
        "permission_denials": [],
    }
    print(json.dumps(payload, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
