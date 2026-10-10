"""API換算コストの計算。

単価は Anthropic 公式の料金表（https://platform.claude.com/docs/en/about-claude/pricing、
2026-10-10 に取得）を USD / 100万トークンで転記したものです。

注意:
- Claude Haiku 5.5 は1リクエストのプロンプト（入力＋キャッシュ読み書き）が10万トークンを超えると
  高価格帯になります。CLI の使用量はリクエストを合算した値しか得られないため、ここでは基本料金だけで計算し、
  平均プロンプト長が閾値を超えた試行には注記を付けます（trial.json の cost.notes）。
- キャッシュ書き込みのTTL内訳は CLI の出力から確実に得られないため、DEFAULT_CACHE_WRITE_TTL を仮定します。
"""

from __future__ import annotations

from dataclasses import dataclass

# 実験で使うモデル。短い名前から正式なモデルIDへの対応。
MODEL_IDS = {"haiku": "claude-haiku-5-5", "opus": "claude-opus-5-5"}

# サブスクリプションのメイン会話のキャッシュ書き込みは1時間TTLとして扱う（料金表の2倍の書き込み単価）。
DEFAULT_CACHE_WRITE_TTL = "1h"

PRICES_PER_MTOK: dict[str, dict[str, float]] = {
    "claude-opus-5-5": {
        "input": 4.00,
        "output": 20.00,
        "cache_write_5m": 5.00,
        "cache_write_1h": 8.00,
        "cache_read": 0.20,
    },
    "claude-haiku-5-5": {
        "input": 0.10,
        "output": 0.50,
        "cache_write_5m": 0.125,
        "cache_write_1h": 0.20,
        "cache_read": 0.01,
    },
}

# この閾値を超えるプロンプトで高価格帯になるモデル（料金表の「prompts over 100,000 tokens」）。
LONG_PROMPT_THRESHOLD_TOKENS = {"claude-haiku-5-5": 100_000}


@dataclass
class TokenCounts:
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0

    @property
    def prompt_tokens(self) -> int:
        return self.input + self.cache_read + self.cache_write

    def __add__(self, other: "TokenCounts") -> "TokenCounts":
        return TokenCounts(
            input=self.input + other.input,
            output=self.output + other.output,
            cache_read=self.cache_read + other.cache_read,
            cache_write=self.cache_write + other.cache_write,
        )


def price_key(model_name: str) -> str | None:
    """CLI が報告するモデル名（日付サフィックス付きを含む）を価格表のキーに対応付ける。対応しなければ None。"""
    for key in PRICES_PER_MTOK:
        if model_name == key or model_name.startswith(key + "-"):
            return key
    return None


def cost_usd(model_key: str, tokens: TokenCounts, cache_write_ttl: str = DEFAULT_CACHE_WRITE_TTL) -> float:
    rates = PRICES_PER_MTOK[model_key]
    dollars = (
        tokens.input * rates["input"]
        + tokens.output * rates["output"]
        + tokens.cache_read * rates["cache_read"]
        + tokens.cache_write * rates[f"cache_write_{cache_write_ttl}"]
    )
    return dollars / 1_000_000
