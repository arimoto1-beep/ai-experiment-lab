"""Stream/stdin fixture for long-context tests. Never invokes a real model."""

import hashlib
import json
import os
import sys
import time
from pathlib import Path

from fake_claude import main as old_fake


def main(argv):
    if argv == ["--version"] or argv[:2] == ["auth", "status"]:
        return old_fake(argv)
    raw_input = sys.stdin.buffer.read()
    payload = raw_input.decode("utf-8")
    user = json.loads(payload)
    prompt = user["message"]["content"]
    model = os.environ.get("FAKE_LONG_MODEL") or argv[argv.index("--model") + 1]
    log = os.environ.get("FAKE_LONG_ARGLOG")
    if log:
        Path(log).write_text(json.dumps({"argv": argv, "stdin_bytes": len(raw_input),
                                        "stdin_sha256": hashlib.sha256(raw_input).hexdigest(),
                                        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                                        "cwd_entries": list(os.listdir()),
                                        "api_key_present": "ANTHROPIC_API_KEY" in os.environ,
                                        "output_budget": os.environ.get("CLAUDE_CODE_MAX_OUTPUT_TOKENS")}), encoding="utf-8")
    if os.environ.get("FAKE_LONG_SLEEP"):
        time.sleep(float(os.environ["FAKE_LONG_SLEEP"]))
    if os.environ.get("FAKE_LONG_BAD_ECHO"):
        user["message"]["content"] = prompt[:100]
    print(json.dumps(user))
    if os.environ.get("FAKE_LONG_COMPACT"):
        print(json.dumps({"type": "system", "subtype": "compact_boundary", "compact_metadata": {"trigger": "auto"}}))
    prompt_tokens = int(os.environ.get("FAKE_LONG_PROMPT_TOKENS", len(prompt) // 4 + 1000))
    usage = {"input_tokens": prompt_tokens, "output_tokens": 1000,
             "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
             "output_tokens_details": {"thinking_tokens": 100}}
    print(json.dumps({"type": "assistant", "message": {"id": "fake-message", "model": model, "usage": usage, "content": []}}))
    print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "num_turns": 1,
                      "result": os.environ.get("FAKE_LONG_RESPONSE", '{}'), "usage": usage,
                      "modelUsage": {model: {"inputTokens": prompt_tokens, "outputTokens": 1000,
                                             "cacheReadInputTokens": 0, "cacheCreationInputTokens": 0,
                                             "contextWindow": 200000}}, "total_cost_usd": 0.123}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
