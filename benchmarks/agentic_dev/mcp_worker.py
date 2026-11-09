"""Task-scoped MCP server. Runs only in the credential-free work container."""

import json
import os
import socket
import subprocess
from pathlib import Path, PurePosixPath


WORK = Path("/work")
SOCKET = Path("/ipc/mcp.sock")
MAX_FILE = 100_000
MAX_OUTPUT = 12_000
TOOLS = [
    {"name": "list_files", "description": "List source and public test files.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "read_file", "description": "Read a UTF-8 file in src or public_tests.",
     "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}},
                     "required": ["path"], "additionalProperties": False}},
    {"name": "write_file", "description": "Replace one UTF-8 file in src with content.",
     "inputSchema": {"type": "object", "properties": {"path": {"type": "string"},
                                                   "content": {"type": "string"}},
                     "required": ["path", "content"], "additionalProperties": False}},
    {"name": "run_public_tests", "description": "Run the fixed public pytest suite.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
]
REVIEW_READ_ONLY = os.environ.get("AI_LAB_REVIEW_READ_ONLY") == "1"
if REVIEW_READ_ONLY:
    TOOLS = TOOLS[:2]


def checked_path(value: object, *, write: bool = False) -> Path:
    if not isinstance(value, str) or "\\" in value or "\x00" in value:
        raise ValueError("invalid path")
    relative = PurePosixPath(value)
    if relative.is_absolute() or len(relative.parts) < 2 or any(p in (".", "..") for p in value.split("/")):
        raise ValueError("invalid path")
    if relative.parts[0] not in (("src",) if write else ("src", "public_tests")):
        raise ValueError("invalid path")
    target = WORK.joinpath(*relative.parts)
    base = WORK / relative.parts[0]
    if not target.resolve().is_relative_to(base.resolve()) or target.is_symlink():
        raise ValueError("invalid path")
    if write and (not target.parent.is_dir() or not target.suffix == ".py"):
        raise ValueError("invalid path")
    return target


def call(name: str, args: object) -> dict:
    try:
        if REVIEW_READ_ONLY and name not in ("list_files", "read_file"):
            raise ValueError("unsupported operation")
        if not isinstance(args, dict):
            raise ValueError("invalid arguments")
        if name == "list_files" and not args:
            files = [p.relative_to(WORK).as_posix() for area in ("src", "public_tests")
                     for p in (WORK / area).rglob("*") if p.is_file() and not p.is_symlink()
                     and "__pycache__" not in p.parts]
            result = "\n".join(sorted(files))
        elif name == "read_file" and set(args) == {"path"}:
            target = checked_path(args["path"])
            if not target.is_file() or target.stat().st_size > MAX_FILE:
                raise ValueError("file unavailable")
            result = target.read_text(encoding="utf-8")
        elif name == "write_file" and set(args) == {"path", "content"}:
            target = checked_path(args["path"], write=True)
            content = args["content"]
            if not isinstance(content, str) or len(content.encode("utf-8")) > MAX_FILE:
                raise ValueError("invalid content")
            target.write_text(content, encoding="utf-8")
            result = "written"
        elif name == "run_public_tests" and not args:
            try:
                run = subprocess.run(["python", "-m", "pytest", "-q", "public_tests",
                                      "-p", "no:cacheprovider"], cwd=WORK,
                                     capture_output=True, text=True, timeout=120, check=False,
                                     env={**os.environ, "PYTHONPATH": "/work/src", "PYTHONDONTWRITEBYTECODE": "1"})
                result = f"exit_code={run.returncode}\n{run.stdout}{run.stderr}"[:MAX_OUTPUT]
            except subprocess.TimeoutExpired:
                result = "exit_code=124\npublic tests timed out"
        else:
            raise ValueError("unsupported operation")
        return {"content": [{"type": "text", "text": result[:MAX_OUTPUT]}], "isError": False}
    except (ValueError, OSError, UnicodeError) as exc:
        # Do not reflect untrusted arguments, paths, or file contents in errors.
        message = str(exc) if isinstance(exc, ValueError) and str(exc) in (
            "invalid path", "file unavailable", "invalid content", "invalid arguments", "unsupported operation") else "operation failed"
        return {"content": [{"type": "text", "text": message}], "isError": True}


def dispatch(request: dict) -> dict | None:
    if "id" not in request:
        return None
    method = request.get("method")
    if method == "initialize":
        result = {"protocolVersion": request.get("params", {}).get("protocolVersion", "2025-03-26"),
                  "capabilities": {"tools": {}}, "serverInfo": {"name": "lab", "version": "1.0"}}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = request.get("params", {})
        result = call(params.get("name", ""), params.get("arguments", {}))
    else:
        return {"jsonrpc": "2.0", "id": request["id"],
                "error": {"code": -32601, "message": "method unavailable"}}
    return {"jsonrpc": "2.0", "id": request["id"], "result": result}


def main() -> None:
    SOCKET.unlink(missing_ok=True)
    server = socket.socket(socket.AF_UNIX)
    server.bind(str(SOCKET))
    server.listen(1)
    while True:
        connection, _ = server.accept()
        with connection, connection.makefile("rwb") as stream:
            for line in stream:
                try:
                    answer = dispatch(json.loads(line))
                except (ValueError, TypeError, AttributeError):
                    answer = {"jsonrpc": "2.0", "id": None,
                              "error": {"code": -32600, "message": "invalid request"}}
                if answer is not None:
                    stream.write(json.dumps(answer, ensure_ascii=False).encode() + b"\n")
                    stream.flush()


if __name__ == "__main__":
    main()
