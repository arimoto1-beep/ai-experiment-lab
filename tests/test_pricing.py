import pytest

from ai_lab.pricing import TokenCounts, cost_usd, price_key

ONE_MILLION = 1_000_000


def test_opus_55_list_prices_per_million_tokens():
    model = "claude-opus-5-5"
    assert cost_usd(model, TokenCounts(input=ONE_MILLION)) == pytest.approx(4.00)
    assert cost_usd(model, TokenCounts(output=ONE_MILLION)) == pytest.approx(20.00)
    assert cost_usd(model, TokenCounts(cache_read=ONE_MILLION)) == pytest.approx(0.20)
    assert cost_usd(model, TokenCounts(cache_write=ONE_MILLION), "5m") == pytest.approx(5.00)
    assert cost_usd(model, TokenCounts(cache_write=ONE_MILLION), "1h") == pytest.approx(8.00)


def test_haiku_55_list_prices_for_prompts_up_to_100k_tokens():
    model = "claude-haiku-5-5"
    assert cost_usd(model, TokenCounts(input=ONE_MILLION)) == pytest.approx(0.10)
    assert cost_usd(model, TokenCounts(output=ONE_MILLION)) == pytest.approx(0.50)
    assert cost_usd(model, TokenCounts(cache_read=ONE_MILLION)) == pytest.approx(0.01)
    assert cost_usd(model, TokenCounts(cache_write=ONE_MILLION), "5m") == pytest.approx(0.125)
    assert cost_usd(model, TokenCounts(cache_write=ONE_MILLION), "1h") == pytest.approx(0.20)


def test_cost_adds_all_token_kinds():
    tokens = TokenCounts(input=100, output=50, cache_read=3000, cache_write=2000)
    expected = (100 * 0.10 + 50 * 0.50 + 3000 * 0.01 + 2000 * 0.20) / ONE_MILLION
    assert cost_usd("claude-haiku-5-5", tokens) == pytest.approx(expected)


def test_price_key_accepts_dated_ids_and_rejects_unknown_models():
    assert price_key("claude-haiku-5-5") == "claude-haiku-5-5"
    assert price_key("claude-haiku-5-5-20261001") == "claude-haiku-5-5"
    assert price_key("claude-opus-5") is None
    assert price_key("claude-sonnet-5-5") is None


def test_token_counts_add_and_report_prompt_size():
    total = TokenCounts(1, 2, 3, 4) + TokenCounts(10, 20, 30, 40)
    assert (total.input, total.output, total.cache_read, total.cache_write) == (11, 22, 33, 44)
    assert TokenCounts(1, 2, 3, 4).prompt_tokens == 1 + 3 + 4
