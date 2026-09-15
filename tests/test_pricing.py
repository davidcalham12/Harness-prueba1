"""Token pricing.

The one that matters is :func:`test_unknown_model_is_never_free`: an unknown
model priced at $0 would hide real spend from the budget guard, which is a
silent failure of the one control that stops a rewrite loop from billing.
"""

from __future__ import annotations

import pytest

from novaforge.pricing import DEFAULT_MODEL, MODEL_PRICING, cost_usd, is_known_model


@pytest.mark.parametrize("model,inp,out,expected", [
    ("claude-opus-5", 1_000_000, 0, 5.0),
    ("claude-opus-5", 0, 1_000_000, 25.0),
    ("claude-sonnet-5", 500_000, 200_000, 3.0),
    ("claude-haiku-4-5", 1_000_000, 1_000_000, 6.0),
    ("claude-fable-5-1", 1_000_000, 1_000_000, 60.0),
])
def test_rates_match_the_published_table(model, inp, out, expected):
    assert cost_usd(model, inp, out) == expected


def test_unknown_model_is_never_free():
    """An unknown model is priced at the default tier, never at zero."""
    assert cost_usd("not-a-model", 1_000_000, 0) == cost_usd(DEFAULT_MODEL, 1_000_000, 0)
    assert cost_usd("not-a-model", 0, 1_000_000) > 0


def test_negative_token_counts_clamp_to_zero():
    assert cost_usd("claude-opus-5", -500, -500) == 0.0


def test_zero_tokens_cost_nothing():
    assert cost_usd("claude-opus-5", 0, 0) == 0.0


def test_rounding_is_six_decimal_places():
    assert cost_usd("claude-opus-5", 1, 1) == round(5 / 1e6 + 25 / 1e6, 6)


def test_known_models():
    assert is_known_model(DEFAULT_MODEL)
    assert not is_known_model("gpt-9")
    assert DEFAULT_MODEL in MODEL_PRICING


def test_output_is_never_cheaper_than_input():
    """Output tokens cost more than input on every tier. A table entry that
    reversed them would make long chapters look cheap."""
    for model, price in MODEL_PRICING.items():
        assert price.output_per_mtok >= price.input_per_mtok, model
