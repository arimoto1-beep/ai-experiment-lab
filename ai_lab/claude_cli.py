"""Claude Code CLI（claude -p）の呼び出し・認証確認・出力の解析。

モデルを実際に呼び出すのはこのモジュールだけです。
- 従量課金に繋がる環境変数（APIキーなど）は子プロセスから取り除き、サブスクリプションの認証だけを使います。
- 試行の前に `claude auth status` で認証方式を確認し、サブスクリプション以外なら実行しません。
- `--bare` は使いません。--bare は OAuth（サブスクリプション）を読まず、APIキーが必要になるためです。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

# 従量課金（APIキー・クラウド経由）に繋がる環境変数。子プロセスからは必ず取り除く。
BILLING_ENV_VARS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY",
)

# サブスクリプションによる認証方式（claude auth status の authMethod）。
SUBSCRIPTION_AUTH_METHODS = ("claude.ai", "oauth_token")

# Claude Code のセッション内から起動されたことを示す環境変数（入れ子実行の検出に使う）。
NESTED_RUN_ENV_VARS = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")

# 1試行あたりの最大ターン数（暴走防止）。
MAX_TURNS = 10


@dataclass
class CliRun:
    returncode: int | None
    stdout: str
    stderr: str
    wall_seconds: float
    timed_out: bool


def check_native_executable(path: str) -> None:
    """.cmd / .bat のラッパーは cmd.exe を経由するため、課題文の引用符や記号が崩れる。実行ファイル本体だけを許可する。"""
    if path.lower().endswith((".cmd", ".bat")):
        raise RuntimeError(
            f"{path} は cmd.exe 経由で起動されるため、課題文の記号が崩れるおそれがあります。"
            "claude.exe の場所を --claude-bin で指定してください（`where claude` で候補を確認できます）。"
        )


def find_claude_command() -> list[str]:
    path = shutil.which("claude")
    if path is None:
        raise FileNotFoundError(
            "claude が PATH 上に見つかりません。Claude Code CLI をインストールするか、--claude-bin で場所を指定してください。"
        )
    check_native_executable(path)
    return [path]


def child_environment(base: Mapping[str, str]) -> dict[str, str]:
    return {name: value for name, value in base.items() if name not in BILLING_ENV_VARS}


def nested_run_reason(env: Mapping[str, str]) -> str | None:
    """Claude Code の内部から起動されている場合は、その環境変数名を返す。"""
    for name in NESTED_RUN_ENV_VARS:
        if env.get(name):
            return name
    return None


def build_args(model_id: str, effort: str, prompt: str) -> list[str]:
    return [
        "-p",
        prompt,
        "--model",
        model_id,
        "--effort",
        effort,
        "--output-format",
        "json",
        # 読み書きだけを許可する。実行系のツール（Bash など）は与えない。
        "--tools",
        "Read,Write,Edit",
        "--permission-mode",
        "acceptEdits",
        "--max-turns",
        str(MAX_TURNS),
        # 試行どうしが会話を引き継がないようにする。
        "--no-session-persistence",
        # CLAUDE.md・フック・MCP などを読み込まず、条件を全試行で揃える。認証は通常どおり使われる。
        "--safe-mode",
    ]


def _text(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _run_quick(command: list[str], env: Mapping[str, str], timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        env=dict(env),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def preflight(command: list[str], env: Mapping[str, str], timeout: float = 60.0) -> dict[str, str]:
    """Claude Code が使えること、サブスクリプションで認証済みであることを確認する。失敗時は RuntimeError。"""
    try:
        version = _run_quick([*command, "--version"], env, timeout)
        auth = _run_quick([*command, "auth", "status"], env, timeout)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"claude の起動確認がタイムアウトしました（{timeout} 秒）。") from exc
    if version.returncode != 0:
        raise RuntimeError(f"claude --version が失敗しました: {version.stderr.strip()}")
    if auth.returncode != 0:
        raise RuntimeError("Claude Code にログインしていません。`claude auth login` を実行してから再度お試しください。")
    try:
        info = json.loads(auth.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"claude auth status の出力を解析できません: {exc}") from exc
    method = info.get("authMethod")
    if method not in SUBSCRIPTION_AUTH_METHODS:
        raise RuntimeError(
            f"認証方式が {method!r} です。サブスクリプションでの認証（{', '.join(SUBSCRIPTION_AUTH_METHODS)}）以外では実行しません。"
        )
    return {"version": version.stdout.strip(), "auth_method": str(method)}


def invoke(command: list[str], args: list[str], *, cwd: str | None, env: Mapping[str, str], timeout: float) -> CliRun:
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            [*command, *args],
            cwd=cwd,
            env=dict(env),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return CliRun(
            returncode=None,
            stdout=_text(exc.stdout),
            stderr=_text(exc.stderr),
            wall_seconds=time.perf_counter() - started,
            timed_out=True,
        )
    return CliRun(
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        wall_seconds=time.perf_counter() - started,
        timed_out=False,
    )


def _result_message(data: Any) -> dict[str, Any] | None:
    if isinstance(data, list):
        for item in reversed(data):
            if isinstance(item, dict) and item.get("type") == "result":
                return item
        return None
    if isinstance(data, dict) and (data.get("type") == "result" or "result" in data):
        return data
    return None


def parse_output(stdout: str) -> dict[str, Any] | None:
    """--output-format json の出力から result メッセージを取り出す。解析できなければ None。"""
    text = stdout.strip()
    try:
        return _result_message(json.loads(text))
    except json.JSONDecodeError:
        pass
    # 先頭に警告などが混ざった場合に備え、後ろの行から JSON を探す。
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line.startswith(("{", "[")):
            continue
        try:
            found = _result_message(json.loads(line))
        except json.JSONDecodeError:
            continue
        if found is not None:
            return found
    return None


def _count(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def summarize_run(run: CliRun) -> dict[str, Any]:
    """CLI の実行結果を trial.json に記録する形に整える。"""
    result = parse_output(run.stdout)
    if run.timed_out:
        status = "timeout"
    elif run.returncode != 0:
        status = "error"
    elif result is None:
        status = "unparsed"
    elif result.get("is_error") or result.get("subtype", "success") != "success":
        status = "error"
    else:
        status = "ok"
    result = result or {}
    return {
        "status": status,
        "returncode": run.returncode,
        "subtype": result.get("subtype"),
        "is_error": result.get("is_error"),
        "num_turns": result.get("num_turns"),
        "duration_ms": result.get("duration_ms"),
        "duration_api_ms": result.get("duration_api_ms"),
        "session_id": result.get("session_id"),
        "permission_denials": _count(result.get("permission_denials")),
        "cli_total_cost_usd": result.get("total_cost_usd"),
        "usage": result.get("usage"),
        "model_usage": result.get("modelUsage"),
        "result_text": result.get("result"),
    }
