import json
from datetime import timedelta
from decimal import Decimal

import httpx
import pytest
from modurouter import worker
from modurouter.billing import reserve, settle
from modurouter.config import Settings
from modurouter.db import utcnow
from modurouter.direct_catalog import direct_models
from modurouter.models import GenerationAttempt, SyncState, UsageLedger
from modurouter.providers import (
    OpenAIAdapter,
    UpstageAdapter,
    ZenMuxAdapter,
    create_adapters,
    usage_cost,
    zenmux_model,
)
from modurouter.router import candidates, catalog_entry, model_status, sync_models
from sqlalchemy import select
from test_billing import seed
from test_router import model


def config(**kwargs):
    return Settings(_env_file=None, openrouter_api_key="test-or", zenmux_api_key="test-zen",
                    openai_api_key="test-ai", upstage_api_key="test-up",
                    model_allowlist="test/model", input_price_cap_usd_per_m="1",
                    output_price_cap_usd_per_m="2", user_daily_budget_usd="1", **kwargs)


class Catalog:
    def __init__(self, code, raw=None):
        self.code = code
        self.raw = raw or model()

    async def list_models(self):
        return [self.raw]


async def test_registry_uses_only_configured_keys():
    adapters = create_adapters(Settings(_env_file=None, zenmux_api_key="test"))
    assert set(adapters) == {"zenmux"}
    await adapters["zenmux"].close()


async def test_independent_catalogs_staleness_and_removed_credentials(database):
    settings = config()
    async with database() as db:
        for code in settings.configured_providers:
            await sync_models(db, Catalog(code), settings)
        choices = await candidates(db, settings, 100)
        assert {c.provider_code for c in choices} == set(settings.configured_providers)
        await db.rollback()
        async with db.begin():
            (await db.get(SyncState, "openrouter")).last_success_at = utcnow() - timedelta(hours=1)
        choices = await candidates(db, settings, 100)
        assert {c.provider_code for c in choices} == {"zenmux", "openai", "upstage"}
        only_zen = Settings(_env_file=None, zenmux_api_key="test", model_allowlist="zenmux::test/model",
                           input_price_cap_usd_per_m="1", output_price_cap_usd_per_m="2")
        assert [c.provider_code for c in await candidates(db, only_zen, 100)] == ["zenmux"]
        status = await model_status(db, settings)
        assert not status["stale"]
        assert next(p for p in status["providers"] if p["provider"] == "openrouter")["stale"]


async def test_failed_sync_does_not_disable_other_provider(database):
    settings = config()
    class Broken(Catalog):
        async def list_models(self):
            raise RuntimeError("offline")
    async with database() as db:
        await sync_models(db, Catalog("openai"), settings)
        with pytest.raises(RuntimeError):
            await sync_models(db, Broken("zenmux"), settings)
        assert [c.provider_code for c in await candidates(db, settings, 100)] == ["openai"]
        assert (await db.get(SyncState, "zenmux")).error_code == "PRICE_REFRESH_FAILED"


def zen_model():
    return {"id": "test/model", "context_length": 1000000,
            "input_modalities": ["text"], "output_modalities": ["text"],
            "pricings": {"prompt": [{"value": 1, "unit": "perMTokens", "currency": "USD"},
                                    {"value": 2, "unit": "perMTokens", "currency": "USD",
                                     "conditions": {"prompt_tokens": {"gte": 200, "unit": "kTokens"}}}],
                        "completion": [{"value": 6, "unit": "perMTokens", "currency": "USD"}]}}


def test_zenmux_units_reserve_highest_tier_and_unknown_charges_fail_closed():
    raw = zen_model()
    normalized = zenmux_model(raw)
    assert catalog_entry(normalized)["input_per_m"] == 2
    assert catalog_entry(normalized)["output_per_m"] == 6
    raw["pricings"]["unknown"] = [{"value": 3, "unit": "perMTokens", "currency": "USD"}]
    with pytest.raises(ValueError):
        catalog_entry(zenmux_model(raw))


@pytest.mark.parametrize("bad", [None, True, -1, "NaN", "Infinity"])
def test_bad_zenmux_price_cannot_become_free(bad):
    raw = zen_model()
    raw["pricings"]["prompt"][0]["value"] = bad
    with pytest.raises((ValueError, ArithmeticError)):
        zenmux_model(raw)


@pytest.mark.parametrize("adapter_type,canonical,native,key,limit", [
    (OpenAIAdapter, "openai/gpt-4o-mini", "gpt-4o-mini", "test-ai", "max_completion_tokens"),
    (UpstageAdapter, "upstage/solar-pro-3", "solar-pro3", "test-up", "max_tokens"),
    (ZenMuxAdapter, "openai/gpt-4o-mini", "openai/gpt-4o-mini", "test-zen", "max_tokens"),
])
async def test_native_payload_and_key_isolation(adapter_type, canonical, native, key, limit):
    def reply(request):
        assert request.headers["Authorization"] == f"Bearer {key}"
        payload = json.loads(request.content)
        assert payload["model"] == native and payload[limit] == 42
        assert payload["stream_options"] == {"include_usage": True}
        if adapter_type == ZenMuxAdapter:
            assert payload["provider"]["routing"]["primary_factor"] == "price"
        else:
            assert "provider" not in payload
        return httpx.Response(200, text='data: {"choices":[]}\n\ndata: [DONE]\n\n')
    adapter = adapter_type(config(), httpx.AsyncClient(transport=httpx.MockTransport(reply)))
    try:
        assert len([event async for event in adapter.stream_chat(canonical, [], 42)]) == 1
    finally:
        await adapter.close()


def test_direct_cost_uses_cached_subset_and_counts_reasoning_once():
    raw = direct_models("openai", {"gpt-4o-mini"})[0]
    usage = {"prompt_tokens": 1000, "completion_tokens": 200,
             "prompt_tokens_details": {"cached_tokens": 400},
             "completion_tokens_details": {"reasoning_tokens": 150}}
    assert usage_cost("openai", usage, raw) == (Decimal("0.00024"), "calculated")
    assert usage_cost("openai", {"prompt_tokens": 1}, raw) is None
    usage["prompt_tokens_details"]["cached_tokens"] = 1001
    assert usage_cost("openai", usage, raw) is None
    assert direct_models("openai", {"unknown-model"}) == []


async def test_zenmux_delayed_bill_is_not_zero():
    replies = [{"data": {"nativeTokens": {"prompt_tokens": 100}}},
               {"data": {"usage": 0.012, "nativeTokens": {"prompt_tokens": 100, "completion_tokens": 50}}}]
    def reply(request):
        assert request.url.path == "/api/v1/management/generation"
        return httpx.Response(200, json=replies.pop(0))
    adapter = ZenMuxAdapter(config(), httpx.AsyncClient(transport=httpx.MockTransport(reply)))
    try:
        assert await adapter.get_generation_usage("gen") == {}
        assert (await adapter.get_generation_usage("gen"))["total_cost"] == "0.012"
    finally:
        await adapter.close()


async def test_same_generation_id_is_independent_per_provider(database):
    settings = config()
    run = (await seed(database, settings))[0]
    async with database() as db:
        for code in ("openrouter", "zenmux"):
            attempt = await reserve(db, run.id, "test/model", Decimal("0.02"), settings, code)
            assert await settle(db, attempt.id, Decimal("0.01"), 10, 10, "same-id", settings)
        rows = (await db.scalars(select(UsageLedger))).all()
        assert {r.provider_code for r in rows} == {"openrouter", "zenmux"}
        assert all(r.cost_usd == Decimal("0.01") for r in rows)


async def test_worker_uses_correct_provider_and_recovers_persisted_direct_usage(database, monkeypatch):
    settings = config()
    run = (await seed(database, settings))[0]
    raw = direct_models("openai", {"gpt-4o-mini"})[0]
    async with database() as db:
        direct = await reserve(db, run.id, raw["id"], Decimal("0.01"), settings, "openai", raw)
        zen = await reserve(db, run.id, "test/model", Decimal("0.01"), settings, "zenmux")
        async with db.begin():
            direct.created_at = zen.created_at = utcnow() - timedelta(minutes=10)
            direct.usage_data = {"prompt_tokens": 100, "completion_tokens": 100}
            zen.generation_id = "zen-id"
    class Lookup:
        async def get_generation_usage(self, identifier):
            assert identifier == "zen-id"
            return {"total_cost": "0.001", "native_tokens_prompt": 10, "native_tokens_completion": 20}
    monkeypatch.setattr(worker, "Session", database)
    monkeypatch.setattr(worker, "settings", settings)
    await worker.reconcile({"openai": object(), "zenmux": Lookup()})
    async with database() as db:
        assert (await db.get(GenerationAttempt, direct.id)).status == "settled"
        assert (await db.get(GenerationAttempt, zen.id)).status == "settled"
        ledger = await db.scalar(select(UsageLedger).where(UsageLedger.attempt_id == direct.id))
        assert ledger.cost_source == "calculated"
        assert ledger.cost_usd == Decimal("0.000075")
