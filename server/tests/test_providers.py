import httpx
import pytest
from modurouter.config import Settings
from modurouter.providers import OpenRouterAdapter, ProviderError


async def test_generation_header_is_available_before_stream_content():
    def reply(request):
        assert request.url.path == "/api/v1/chat/completions"
        return httpx.Response(200, headers={"X-Generation-Id": "gen-header"},
                              text='data: {"id":"gen-body","choices":[{"delta":{"content":"답변"}}]}\n\ndata: [DONE]\n\n')

    client = httpx.AsyncClient(transport=httpx.MockTransport(reply))
    adapter = OpenRouterAdapter(Settings(_env_file=None, openrouter_api_key="test-key"), client)
    try:
        events = [event async for event in adapter.stream_chat("test/model",
                  [{"role": "user", "content": "질문"}], 10)]
    finally:
        await adapter.close()
    assert events[0] == {"id": "gen-header", "choices": []}
    assert events[1]["id"] == "gen-body"
    assert events[1]["choices"][0]["delta"]["content"] == "답변"


@pytest.mark.parametrize("body", [
    'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n',
    'data: []\n\ndata: [DONE]\n\n',
    'data: {"error":"unavailable"}\n\n',
])
async def test_incomplete_or_invalid_stream_is_not_a_success(body):
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, text=body)))
    adapter = OpenRouterAdapter(Settings(_env_file=None, openrouter_api_key="test-key"), client)
    try:
        with pytest.raises(ProviderError):
            _ = [event async for event in adapter.stream_chat("test/model", [], 10)]
    finally:
        await adapter.close()


@pytest.mark.parametrize("failure,not_billable", [
    (httpx.ConnectError("connect"), True),
    (httpx.ConnectTimeout("connect"), True),
    (httpx.ReadTimeout("read"), False),
    (httpx.WriteError("write"), False),
])
async def test_transport_failures_distinguish_unsubmitted_from_ambiguous(failure, not_billable):
    def reply(request):
        raise failure
    client = httpx.AsyncClient(transport=httpx.MockTransport(reply))
    adapter = OpenRouterAdapter(Settings(_env_file=None, openrouter_api_key="test-key"), client)
    try:
        with pytest.raises(ProviderError) as error:
            _ = [event async for event in adapter.stream_chat("test/model", [], 10)]
        assert error.value.not_billable is not_billable
    finally:
        await adapter.close()


@pytest.mark.parametrize("status", [400, 401, 429, 500, 503])
async def test_http_rejection_has_no_billable_generation(status):
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(status)))
    adapter = OpenRouterAdapter(Settings(_env_file=None, openrouter_api_key="test-key"), client)
    try:
        with pytest.raises(ProviderError) as error:
            _ = [event async for event in adapter.stream_chat("test/model", [], 10)]
        assert error.value.not_billable
    finally:
        await adapter.close()


async def test_error_response_preserves_generation_header_for_reconciliation():
    client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda _: httpx.Response(503, headers={"X-Generation-Id": "gen-error"})))
    adapter = OpenRouterAdapter(Settings(_env_file=None, openrouter_api_key="test-key"), client)
    events = []
    try:
        with pytest.raises(ProviderError):
            async for event in adapter.stream_chat("test/model", [], 10):
                events.append(event)
        assert events == [{"id": "gen-error", "choices": []}]
    finally:
        await adapter.close()
