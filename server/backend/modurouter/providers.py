import json
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Protocol

import httpx

from .config import Settings
from .direct_catalog import CATALOG, direct_models
from .errors import AppError


class ProviderError(AppError):
    def __init__(self, status: int, retryable: bool = False, *, not_billable: bool = False):
        code = "PROVIDER_ACCOUNT_ERROR" if status in (401, 402, 403) else "PROVIDER_UNAVAILABLE"
        super().__init__(code, "모델 서비스에 연결하지 못했습니다.", 503, retryable)
        self.provider_status = status
        self.not_billable = not_billable


class ProviderAdapter(Protocol):
    async def list_models(self) -> list[dict]: ...
    def stream_chat(self, model: str, messages: list[dict], max_tokens: int) -> AsyncIterator[dict]: ...
    async def get_generation_usage(self, generation_id: str) -> dict: ...


class OpenRouterAdapter:
    code = "openrouter"
    base_url = "https://openrouter.ai/api/v1"

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(90, connect=10),
                                                follow_redirects=False, trust_env=False)

    @property
    def headers(self):
        return {"Authorization": f"Bearer {self.api_key}",
                "HTTP-Referer": self.settings.web_origin, "X-OpenRouter-Title": "Modurouter"}

    @property
    def api_key(self):
        return getattr(self.settings, f"{self.code}_api_key").get_secret_value()

    async def list_models(self):
        response = await self.client.get(f"{self.base_url}/models")
        response.raise_for_status()
        data = response.json().get("data")
        if not isinstance(data, list) or not data:
            raise ValueError("Invalid model catalog")
        return data

    def payload(self, model: str, messages: list[dict], max_tokens: int):
        return {"model": model, "messages": messages, "stream": True,
                   "stream_options": {"include_usage": True}, "max_tokens": max_tokens,
                   "provider": {"sort": "price", "require_parameters": True,
                       "max_price": {"prompt": float(self.settings.input_price_cap_usd_per_m),
                                     "completion": float(self.settings.output_price_cap_usd_per_m),
                                     "request": 0}}}

    async def stream_chat(self, model: str, messages: list[dict], max_tokens: int):
        if not self.api_key:
            raise ProviderError(401, not_billable=True)
        payload = self.payload(model, messages, max_tokens)
        try:
            async with self.client.stream("POST", f"{self.base_url}/chat/completions",
                                          headers=self.headers, json=payload) as response:
                generation_id = response.headers.get("X-Generation-Id")
                if generation_id and len(generation_id) <= 255:
                    yield {"id": generation_id, "choices": []}
                if response.status_code != 200:
                    status = response.status_code
                    raise ProviderError(status, status == 429 or status >= 500, not_billable=True)
                async for line in response.aiter_lines():
                    if len(line) > 256_000:
                        raise ProviderError(502)
                    if not line.startswith("data:"):
                        continue
                    value = line[5:].strip()
                    if value == "[DONE]":
                        return
                    try:
                        event = json.loads(value)
                    except (ValueError, TypeError):
                        raise ProviderError(502) from None
                    if not isinstance(event, dict):
                        raise ProviderError(502)
                    if "error" in event:
                        error = event["error"]
                        code = error.get("code", 502) if isinstance(error, dict) else 502
                        status = int(code) if str(code).isdigit() else 502
                        raise ProviderError(status, status == 429 or status >= 500)
                    yield event
                # EOF without the SSE terminator is an interrupted answer, even after deltas.
                raise ProviderError(502, True)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            # No HTTP request reached the provider. Read/write timeouts below
            # are ambiguous and retain their reservation for reconciliation.
            raise ProviderError(503, True, not_billable=True) from None
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError):
            raise ProviderError(503, True) from None

    async def get_generation_usage(self, generation_id: str):
        response = await self.client.get(f"{self.base_url}/generation", headers=self.headers,
                                         params={"id": generation_id})
        response.raise_for_status()
        return response.json()["data"]

    async def close(self):
        await self.client.aclose()


def positive_price(value) -> Decimal:
    if value is None or isinstance(value, bool):
        raise ValueError("Missing price")
    result = Decimal(str(value))
    if not result.is_finite() or result < 0:
        raise ValueError("Invalid price")
    return result


def zenmux_model(raw: dict) -> dict:
    """Use the highest tier for reservations, never the first/cheapest tier.

    The harness sends text only, no hosted tools, no explicit cache creation.
    Unsupported nonzero billing dimensions exclude a model from routing.
    """
    pricing = {}
    unused = {"web_search", "image", "audio", "video", "audio_and_video", "audio_input",
              "audio_cache_read", "input_cache_write", "input_cache_write_5_min", "input_cache_write_1_h"}
    for dimension, tiers in raw["pricings"].items():
        if dimension in unused:
            continue
        if not isinstance(tiers, list) or not tiers:
            raise ValueError("Missing price tiers")
        values = []
        for tier in tiers:
            unit = "perCount" if dimension == "request" else "perMTokens"
            if tier.get("currency") != "USD" or tier.get("unit") != unit:
                raise ValueError("Unsupported price unit")
            values.append(positive_price(tier.get("value")))
        pricing[dimension] = str(max(values) / (1 if dimension == "request" else 1_000_000))
    return {**raw, "pricing": pricing,
            "architecture": {"input_modalities": raw.get("input_modalities", []),
                             "output_modalities": raw.get("output_modalities", [])},
            "price_kind": "api", "price_source": "https://zenmux.ai/api/v1/models"}


class ZenMuxAdapter(OpenRouterAdapter):
    code = "zenmux"
    base_url = "https://zenmux.ai/api/v1"

    @property
    def headers(self):
        return {"Authorization": f"Bearer {self.api_key}"}

    async def list_models(self):
        models = await super().list_models()
        result = []
        for raw in models:
            try:
                result.append(zenmux_model(raw))
            except (KeyError, ValueError, TypeError, ArithmeticError):
                continue
        return result

    def payload(self, model, messages, max_tokens):
        return {"model": model, "messages": messages, "stream": True,
                "stream_options": {"include_usage": True}, "max_tokens": max_tokens,
                "provider": {"routing": {"type": "priority", "primary_factor": "price"}}}

    async def get_generation_usage(self, generation_id):
        response = await self.client.get(f"{self.base_url}/management/generation",
                                        headers=self.headers, params={"id": generation_id})
        response.raise_for_status()
        data = response.json()
        data = data.get("data", data)
        usage = data.get("usage")
        if usage is None:
            return {}  # Billing data is asynchronous, normally 3-5 minutes.
        tokens = data.get("nativeTokens") or {}
        return {"total_cost": str(positive_price(usage)),
                "native_tokens_prompt": tokens.get("prompt_tokens"),
                "native_tokens_completion": tokens.get("completion_tokens")}


class DirectAdapter(OpenRouterAdapter):
    @property
    def headers(self):
        return {"Authorization": f"Bearer {self.api_key}"}

    async def list_models(self):
        response = await self.client.get(f"{self.base_url}/models", headers=self.headers)
        response.raise_for_status()
        return direct_models(self.code, {m["id"] for m in response.json()["data"]})

    def payload(self, model, messages, max_tokens):
        native = CATALOG[self.code][model][0]
        result = {"model": native, "messages": messages, "stream": True,
                  "stream_options": {"include_usage": True}}
        result["max_completion_tokens" if self.code == "openai" else "max_tokens"] = max_tokens
        if self.code == "openai":
            result["service_tier"] = "default"
            if native.startswith("gpt-5"):
                result["reasoning_effort"] = "minimal"
        return result

    async def get_generation_usage(self, generation_id):
        # These APIs have no per-request billing lookup for non-stored chat.
        return {}


class OpenAIAdapter(DirectAdapter):
    code = "openai"
    base_url = "https://api.openai.com/v1"


class UpstageAdapter(DirectAdapter):
    code = "upstage"
    base_url = "https://api.upstage.ai/v1"


def create_adapters(settings: Settings) -> dict[str, OpenRouterAdapter]:
    types = (OpenRouterAdapter, ZenMuxAdapter, OpenAIAdapter, UpstageAdapter)
    return {adapter.code: adapter(settings) for adapter in types
            if adapter.code in settings.configured_providers}


def usage_cost(provider: str, usage: dict | None, price_data: dict) -> tuple[Decimal, str] | None:
    if not usage:
        return None
    if provider in ("openrouter", "zenmux"):
        value = usage.get("cost")
        return (positive_price(value), "provider") if value is not None else None
    # Token counts include reasoning tokens in completion_tokens. Cached tokens
    # are a subset of prompt_tokens, and must not be charged a second time.
    prompt, completion = usage.get("prompt_tokens"), usage.get("completion_tokens")
    cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
    if any(not isinstance(n, int) or isinstance(n, bool) or n < 0 for n in (prompt, completion, cached)) or cached > prompt:
        return None
    pricing = price_data["pricing"]
    cost = ((prompt - cached) * positive_price(pricing["prompt"])
            + cached * positive_price(pricing.get("input_cache_read", pricing["prompt"]))
            + completion * positive_price(pricing["completion"]))
    return cost, "calculated"
