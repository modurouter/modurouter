from datetime import timedelta
from decimal import Decimal

import pytest
from modurouter.config import Settings
from modurouter.db import utcnow
from modurouter.errors import AppError
from modurouter.models import SyncState
from modurouter.router import candidates, catalog_entry, price, sync_models


def model(identifier="test/model", prompt="0.00000025", completion="0.000001"):
    return {"id": identifier, "context_length": 8192,
            "pricing": {"prompt": prompt, "completion": completion, "request": "0"},
            "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]}}


@pytest.mark.parametrize("value", [None, "", "NaN", "Infinity", "-1", True])
def test_bad_prices_never_become_free(value):
    with pytest.raises(ValueError):
        price(value)


def test_units_and_extra_charges():
    entry = catalog_entry(model())
    assert entry["input_per_m"] == Decimal("0.25")
    assert entry["output_per_m"] == Decimal("1")
    raw = model()
    raw["pricing"]["unknown_surcharge"] = "0.1"
    with pytest.raises(ValueError):
        catalog_entry(raw)


@pytest.mark.parametrize("dimension", ["input_cache_read", "input_cache_write"])
def test_cache_prices_cannot_exceed_reserved_input_price(dimension):
    raw = model()
    raw["pricing"][dimension] = "0.01"
    with pytest.raises(ValueError, match="Cache surcharge"):
        catalog_entry(raw)


async def test_atomic_refresh_caps_allowlist_and_stale(database):
    config = Settings(_env_file=None, openrouter_api_key="test-key", model_allowlist="test/model,test/expensive",
        input_price_cap_usd_per_m="0.25", output_price_cap_usd_per_m="1")
    class Adapter:
        async def list_models(self):
            return [model(), model("test/expensive", "0.000000251"), model("test/unreviewed", "0", "0")]
    async with database() as db:
        assert await sync_models(db, Adapter(), config) == 3
        chosen = await candidates(db, config, 1000)
        assert [c.model_id for c in chosen] == ["test/model"]
        with pytest.raises(AppError, match="NO_ELIGIBLE_MODEL"):
            await candidates(db, config, 8000)
        await db.rollback()
        class Broken:
            async def list_models(self):
                raise RuntimeError("offline")
        with pytest.raises(RuntimeError):
            await sync_models(db, Broken(), config)
        assert len(await candidates(db, config, 1000)) == 1
        state = await db.get(SyncState, "openrouter")
        assert state.error_code == "PRICE_REFRESH_FAILED"
        state.last_success_at = utcnow() - timedelta(minutes=31)
        await db.commit()
        with pytest.raises(AppError, match="PRICE_DATA_STALE"):
            await candidates(db, config, 1000)
