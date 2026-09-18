import json
from decimal import Decimal

import httpx
import pytest
from modurouter.config import Settings
from modurouter.errors import AppError
from modurouter.model_options import catalog_view, effective_effort, low_efforts, select_routes
from modurouter.providers import OpenAIAdapter, OpenRouterAdapter
from modurouter.router import Candidate
from modurouter.run_input import RunInput
from pydantic import ValidationError


def route(model="openai/gpt-5-nano", provider="openai", raw=None):
    return Candidate(model, Decimal(".05"), Decimal(".4"), Decimal(".0004"), Decimal(".0004"), provider, raw or {})


def test_only_low_efforts_accepted():
    for effort in ("high", "medium", "xhigh", "none"):
        with pytest.raises(ValidationError):
            RunInput(message="hello", reasoning_effort=effort)
    assert RunInput(message="hi", reasoning_effort="minimal").reasoning_effort == "minimal"


def test_selection_never_falls_back_to_another_named_model():
    choices = [route(), route("openai/gpt-4o-mini")]
    assert select_routes(choices, "openai/gpt-4o-mini", "low") == choices[1:]
    with pytest.raises(AppError):
        select_routes(choices, "unlisted/expensive", "low")


def test_nonreasoning_models_do_not_receive_unsupported_parameter():
    assert effective_effort(route("openai/gpt-4o-mini"), "low") is None
    assert effective_effort(route(), None) == "minimal"
    assert low_efforts("openrouter", "test/model", {"supported_parameters": ["reasoning"]}) == ["low"]


def test_catalog_groups_routes_without_inventing_models():
    catalog = catalog_view([route(), route(provider="openrouter", raw={"supported_parameters": ["reasoning"]})])
    assert len(catalog["models"]) == 1
    assert catalog["models"][0]["efforts"] == ["minimal", "low"]
    assert catalog["models"][0]["providers"] == ["openai", "openrouter"]


@pytest.mark.parametrize("adapter_type,effort,expected", [
    (OpenAIAdapter, "minimal", "minimal"), (OpenAIAdapter, "low", "low"),
    (OpenRouterAdapter, "low", {"effort": "low", "exclude": True}),
])
async def test_effort_sent_to_provider_and_token_limit_preserved(adapter_type, effort, expected):
    def reply(request):
        body = json.loads(request.content)
        assert body.get("reasoning_effort", body.get("reasoning")) == expected
        assert body.get("max_completion_tokens", body.get("max_tokens")) == 128
        return httpx.Response(200, text="data: [DONE]\n\n")
    adapter = adapter_type(Settings(_env_file=None, openai_api_key="test", openrouter_api_key="test"),
                           httpx.AsyncClient(transport=httpx.MockTransport(reply)))
    try:
        _ = [e async for e in adapter.stream_chat("openai/gpt-5-nano", [], 128, reasoning_effort=effort)]
    finally:
        await adapter.close()
