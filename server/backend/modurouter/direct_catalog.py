"""Reviewed direct-provider text tariffs, USD per million tokens, excluding tax.

The direct model-list APIs do not expose prices. Do not substitute aggregator
prices or price unknown models at zero. Refresh these references before expiry.
"""
from datetime import date
from decimal import Decimal

REVIEWED_AT = "2026-09-18"
VALID_UNTIL = "2026-10-18"
MILLION = Decimal(1_000_000)

# canonical ID -> native ID, context, input, output, cached input, source
CATALOG = {
    "openai": {
        "openai/gpt-4o-mini": ("gpt-4o-mini", 128000, "0.15", "0.60", "0.075",
            "https://developers.openai.com/api/docs/models/gpt-4o-mini"),
        "openai/gpt-4.1-nano": ("gpt-4.1-nano", 1047576, "0.10", "0.40", "0.025",
            "https://developers.openai.com/api/docs/models/gpt-4.1-nano"),
        "openai/gpt-5-nano": ("gpt-5-nano", 400000, "0.05", "0.40", "0.005",
            "https://developers.openai.com/api/docs/models/gpt-5-nano"),
    },
    "upstage": {
        "upstage/solar-pro-3": ("solar-pro3", 131072, "0.15", "0.60", "0.015",
            "https://www.upstage.ai/pricing/api"),
        "upstage/solar-pro-2": ("solar-pro2", 65536, "0.15", "0.60", "0.015",
            "https://www.upstage.ai/pricing/api"),
    },
}


def direct_models(provider: str, available: set[str]) -> list[dict]:
    if date.today() >= date.fromisoformat(VALID_UNTIL):
        raise ValueError("Direct price reference requires review")
    result = []
    for model_id, (native, context, prompt, completion, cached, source) in CATALOG[provider].items():
        if native not in available:
            continue
        result.append({"id": model_id, "native_id": native, "context_length": context,
            "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
            "supported_parameters": ["max_tokens"],
            "pricing": {"prompt": str(Decimal(prompt) / MILLION),
                        "completion": str(Decimal(completion) / MILLION),
                        "input_cache_read": str(Decimal(cached) / MILLION)},
            "price_source": source, "price_kind": "reference", "price_reviewed_at": REVIEWED_AT,
            "price_valid_until": VALID_UNTIL})
    return result
