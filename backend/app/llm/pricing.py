"""What each model costs, in US dollars per 1 million tokens (standard tier).

Source: https://developers.openai.com/api/docs/pricing (checked 2026-09-30).
Prices change: check the page when you add a model or once a quarter. A model that is
missing here is still called, but its cost is logged as 0 and an error is logged.

OpenAI counts cached input tokens inside `input_tokens`; they cost the lower cached price.
"""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPrice:
    """USD per 1,000,000 tokens."""

    input: float
    cached_input: float
    output: float


PRICES: dict[str, ModelPrice] = {
    "gpt-6-luna": ModelPrice(input=0.10, cached_input=0.01, output=0.50),
    "gpt-6.1-sol": ModelPrice(input=2.00, cached_input=0.10, output=10.00),
    "gpt-6-astra": ModelPrice(input=10.00, cached_input=1.00, output=50.00),
    # The pretend model for local development (LLM_DEV_FAKE). Free.
    "fake": ModelPrice(input=0.0, cached_input=0.0, output=0.0),
}


def price_for(model: str) -> ModelPrice | None:
    """The price of a model id. Dated snapshots ("gpt-6-luna-2026-08-01") use the base price."""
    if model in PRICES:
        return PRICES[model]
    base = next((name for name in PRICES if model.startswith(f"{name}-")), None)
    return PRICES[base] if base else None


def cost_micro_usd(
    price: ModelPrice, *, input_tokens: int, cached_input_tokens: int, output_tokens: int
) -> int:
    """Cost in millionths of a dollar, rounded UP (never under-report a cost).

    1 USD per 1M tokens is exactly 1 micro-USD per token, so no unit conversion is needed.
    """
    cached = min(cached_input_tokens, input_tokens)
    exact = (
        (input_tokens - cached) * price.input
        + cached * price.cached_input
        + output_tokens * price.output
    )
    return math.ceil(round(exact, 6))
