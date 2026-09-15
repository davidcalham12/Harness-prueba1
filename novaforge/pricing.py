"""Token pricing, in one place.

Rates are US dollars per million tokens, from the Anthropic pricing table.
The mock engine reports the same model id as a real run, so a dry run produces
a cost estimate with the same arithmetic as a paid one - the numbers are
simulated, the pricing logic is not.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["DEFAULT_MODEL", "MODEL_PRICING", "Price", "cost_usd", "is_known_model"]

DEFAULT_MODEL = "claude-opus-5"


@dataclass(frozen=True)
class Price:
    """Dollars per million tokens."""

    input_per_mtok: float
    output_per_mtok: float


MODEL_PRICING: dict[str, Price] = {
    "claude-opus-5": Price(5.00, 25.00),
    "claude-opus-4-8": Price(5.00, 25.00),
    "claude-sonnet-5": Price(2.00, 10.00),
    "claude-haiku-4-5": Price(1.00, 5.00),
    "claude-fable-5-1": Price(10.00, 50.00),
}


def is_known_model(model: str) -> bool:
    return model in MODEL_PRICING


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Cost of one call. Unknown models are priced at the default tier, never
    at zero - a silent $0 would hide real spend from the budget guard."""
    price = MODEL_PRICING.get(model) or MODEL_PRICING[DEFAULT_MODEL]
    total = (
        (max(0, int(input_tokens)) / 1_000_000) * price.input_per_mtok
        + (max(0, int(output_tokens)) / 1_000_000) * price.output_per_mtok
    )
    return round(total, 6)
