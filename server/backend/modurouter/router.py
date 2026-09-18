from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings
from .db import new_id, utcnow
from .errors import AppError
from .model_options import low_efforts
from .models import GenerationAttempt, PriceSnapshot, ProviderModel, SyncState

MILLION = Decimal(1_000_000)


class RoutingPreference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["auto", "free", "manual"] = "auto"
    provider: Literal["openrouter", "zenmux", "openai", "upstage"] | None = None
    model_id: str | None = Field(default=None, min_length=1, max_length=255)

    @model_validator(mode="after")
    def explicit_selection(self):
        if self.mode == "manual":
            if not self.provider or not self.model_id:
                raise ValueError("Direct selection requires provider and model_id")
        elif self.provider is not None or self.model_id is not None:
            raise ValueError("Provider and model_id require manual mode")
        return self


def price(value) -> Decimal:
    if value is None or isinstance(value, bool):
        raise ValueError("Missing price")
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("Invalid price") from None
    if not result.is_finite() or result < 0:
        raise ValueError("Invalid price")
    return result


def catalog_entry(raw: dict) -> dict:
    pricing = raw["pricing"]
    input_price = price(pricing.get("prompt")) * MILLION
    output_price = price(pricing.get("completion")) * MILLION
    # Unknown pricing dimensions must not silently become free.
    extras = {k: price(v) for k, v in pricing.items() if k not in ("prompt", "completion")}
    if any(v > 0 for k, v in extras.items() if k not in ("input_cache_read", "input_cache_write")):
        raise ValueError("Additional charges")
    if any(extras.get(dimension, Decimal(0)) * MILLION > input_price
           for dimension in ("input_cache_read", "input_cache_write")):
        raise ValueError("Cache surcharge")
    architecture = raw.get("architecture", {})
    if "text" not in architecture.get("input_modalities", []) or architecture.get("output_modalities") != ["text"]:
        raise ValueError("Unsupported modality")
    if not isinstance(raw.get("context_length"), int) or raw["context_length"] < 1:
        raise ValueError("Invalid context")
    if not raw.get("id") or len(raw["id"]) > 255:
        raise ValueError("Invalid model ID")
    return {"input_per_m": input_price, "output_per_m": output_price,
            "request_price": extras.get("request", Decimal(0))}


async def sync_models(db: AsyncSession, adapter, settings: Settings) -> int:
    provider = getattr(adapter, "code", "openrouter")
    try:
        raw_models = await adapter.list_models()
        valid = []
        seen = set()
        for raw in raw_models:
            try:
                prices = catalog_entry(raw)
                if raw["id"] in seen:
                    continue
                seen.add(raw["id"])
                valid.append((raw, prices))
            except (ValueError, KeyError, TypeError):
                continue
        if not valid:
            raise ValueError("No valid model prices")
        async with db.begin():
            state = await db.scalar(select(SyncState).where(
                SyncState.provider_code == provider).with_for_update())
            if state is None:
                state = SyncState(provider_code=provider)
                db.add(state)
            batch_id = new_id()
            now = utcnow()
            await db.execute(update(ProviderModel).where(ProviderModel.provider_code == provider).values(enabled=False))
            for raw, prices in valid:
                model = await db.scalar(select(ProviderModel).where(
                    ProviderModel.provider_code == provider, ProviderModel.model_id == raw["id"]))
                if model is None:
                    model = ProviderModel(provider_code=provider, model_id=raw["id"], context_length=raw["context_length"], capabilities={})
                    db.add(model)
                    await db.flush()
                model.enabled = True
                model.context_length = raw["context_length"]
                model.capabilities = {"parameters": raw.get("supported_parameters", []),
                                      "architecture": raw.get("architecture", {})}
                model.quality_status = "tools" if settings.model_allowed(provider, model.model_id, tools=True) else (
                    "chat" if settings.model_allowed(provider, model.model_id) else "unreviewed")
                db.add(PriceSnapshot(batch_id=batch_id, model_key=model.id, fetched_at=now, raw=raw, **prices))
            state.active_batch_id = batch_id
            state.last_success_at = now
            state.last_attempt_at = now
            state.error_code = None
        return len(valid)
    except Exception:
        await db.rollback()
        async with db.begin():
            state = await db.get(SyncState, provider)
            if state is None:
                state = SyncState(provider_code=provider)
                db.add(state)
            state.last_attempt_at = utcnow()
            state.error_code = "PRICE_REFRESH_FAILED"
        raise


def estimate_tokens(messages: list[dict]) -> int:
    """Language-aware estimate, not a provider tokenizer or a billing token count.

    Reserve two tokens per Hangul/CJK character, one per ASCII character, and
    UTF-8 byte length for other Unicode. Keep framing and 10% headroom. ASCII
    deliberately remains conservative for code, IDs and JSON source wrappers.
    """
    n = 32
    for message in messages:
        n += 32
        for char in str(message.get("content", "")):
            point = ord(char)
            if 0xAC00 <= point <= 0xD7A3 or 0x3400 <= point <= 0x9FFF:
                n += 2
            else:
                n += len(char.encode("utf-8"))
    return (n * 11 + 9) // 10


async def model_status(db: AsyncSession, settings: Settings) -> dict:
    states = {s.provider_code: s for s in (await db.scalars(select(SyncState))).all()}
    providers = []
    for code in settings.configured_providers:
        state = states.get(code)
        success = state.last_success_at if state else None
        stale = not success or (utcnow() - success).total_seconds() > settings.price_stale_seconds
        if code in ("openai", "upstage"):
            from .direct_catalog import VALID_UNTIL
            stale = stale or date.today() >= date.fromisoformat(VALID_UNTIL)
        providers.append({"provider": code, "last_success_at": success.isoformat() + "Z" if success else None,
                          "refresh_error": state.error_code if state else "PRICE_NOT_SYNCED",
                          "stale": bool(stale), "price_kind": "reference" if code in ("openai", "upstage") else "api"})
    healthy = [p for p in providers if not p["stale"]]
    return {"providers": providers, "stale": not healthy,
            "last_success_at": max((p["last_success_at"] for p in healthy), default=None),
            "refresh_error": None if healthy else "PRICE_DATA_STALE"}


@dataclass(frozen=True)
class Candidate:
    model_id: str
    input_per_m: Decimal
    output_per_m: Decimal
    estimated_usd: Decimal
    reserved_usd: Decimal
    provider_code: str
    price_data: dict
    context_length: int = 0


async def candidates(db: AsyncSession, settings: Settings, input_tokens: int,
                     needs_tools: bool = False, routing: RoutingPreference | None = None,
                     *, catalog: bool = False) -> list[Candidate]:
    routing = routing or RoutingPreference()
    if routing.mode == "manual" and not settings.allow_manual_selection:
        raise AppError("MANUAL_SELECTION_DISABLED", "관리자가 직접 모델 선택을 비활성화했습니다.", 403)
    states = (await db.scalars(select(SyncState).where(
        SyncState.provider_code.in_(settings.configured_providers)))).all()
    fresh = [state for state in states if state.last_success_at and state.active_batch_id
             and (utcnow() - state.last_success_at).total_seconds() <= settings.price_stale_seconds]
    if not fresh:
        raise AppError("PRICE_DATA_STALE", "모델 가격을 갱신 중입니다. 잠시 후 다시 시도해 주세요.", 503, True)
    rows = (await db.execute(select(ProviderModel, PriceSnapshot).join(
        PriceSnapshot, PriceSnapshot.model_key == ProviderModel.id).where(
            ProviderModel.enabled.is_(True), PriceSnapshot.batch_id.in_([s.active_batch_id for s in fresh]),
            ProviderModel.provider_code.in_([s.provider_code for s in fresh]),
            ProviderModel.context_length >= input_tokens + settings.max_output_tokens,
            PriceSnapshot.request_price == 0))).all()
    # Free endpoints stay free. Paid routes reserve the provider ceiling, since an endpoint's
    # price can be higher than the catalog's representative price.
    result = []
    for model, snapshot in rows:
        if (catalog or routing.mode != "auto") and not settings.selectable_model(model.provider_code, model.model_id):
            continue
        # Automatic routing keeps the reviewed quality pool. Explicit selection
        # opens the priced text catalog, while tool planning still requires review.
        if not catalog:
            if needs_tools and not settings.model_allowed(model.provider_code, model.model_id, tools=True):
                continue
            if routing.mode == "auto" and (
                not settings.model_allowed(model.provider_code, model.model_id, tools=needs_tools)
                or snapshot.input_per_m > settings.input_price_cap_usd_per_m
                or snapshot.output_per_m > settings.output_price_cap_usd_per_m
            ):
                continue
            if routing.mode == "free" and (snapshot.input_per_m != 0 or snapshot.output_per_m != 0):
                continue
            if routing.mode == "manual" and (model.provider_code != routing.provider or model.model_id != routing.model_id):
                continue
        expiry = snapshot.raw.get("price_valid_until")
        if expiry and date.today() >= date.fromisoformat(expiry):
            continue
        estimate = (input_tokens * snapshot.input_per_m + settings.max_output_tokens * snapshot.output_per_m) / MILLION
        ceiling = (input_tokens * settings.input_price_cap_usd_per_m + settings.max_output_tokens * settings.output_price_cap_usd_per_m) / MILLION
        reservation = ceiling if routing.mode == "auto" and not catalog and model.provider_code in ("openrouter", "zenmux") else estimate
        if snapshot.input_per_m == snapshot.output_per_m == 0:
            reservation = Decimal(0)
        result.append(Candidate(model.model_id, snapshot.input_per_m, snapshot.output_per_m,
                                estimate, reservation, model.provider_code, snapshot.raw, model.context_length))
    attempts = (await db.scalars(select(GenerationAttempt).where(
        GenerationAttempt.created_at > utcnow() - timedelta(hours=24)))).all()
    def reliability(candidate):
        subset = [a for a in attempts if a.model_id == candidate.model_id and a.provider_code == candidate.provider_code]
        success = [a for a in subset if a.status == "settled" and not a.error_code]
        ratio = len(success) / len(subset) if subset else 0
        latency = sum((a.finished_at - a.created_at).total_seconds() for a in success if a.finished_at) / max(len(success), 1)
        return (-ratio, latency)
    result.sort(key=lambda x: (x.estimated_usd, *reliability(x), x.model_id, x.provider_code))
    if not result and not catalog:
        if routing.mode == "manual":
            raise AppError("SELECTED_MODEL_UNAVAILABLE", "선택한 모델을 현재 사용할 수 없습니다. 가격 갱신 상태와 입력 길이, 자료 처리 지원 여부를 확인해 주세요.", 409)
        if routing.mode == "free":
            raise AppError("NO_FREE_MODEL", "현재 요청을 처리할 무료 모델이 없습니다. 자동으로 유료 모델을 사용하지 않습니다.", 503, True)
        raise AppError("NO_ELIGIBLE_MODEL", "현재 가격과 품질 조건에 맞는 모델이 없습니다.", 503, True)
    return result


async def model_catalog(db: AsyncSession, settings: Settings) -> dict:
    status = await model_status(db, settings)
    try:
        choices = await candidates(db, settings, 0, catalog=True)
    except AppError as exc:
        if exc.code != "PRICE_DATA_STALE":
            raise
        choices = []
    return {**status, "default_routing": settings.default_routing,
            "allow_manual_selection": settings.allow_manual_selection, "models": [
        {"provider": c.provider_code, "model_id": c.model_id,
         "name": c.price_data.get("name") or c.model_id,
         "efforts": low_efforts(c.provider_code, c.model_id, c.price_data),
         "input_per_m": str(c.input_per_m), "output_per_m": str(c.output_per_m),
         "is_free": c.input_per_m == c.output_per_m == 0,
         "context_length": c.price_data["context_length"],
         "supports_tools": settings.model_allowed(c.provider_code, c.model_id, tools=True),
         "auto_eligible": settings.model_allowed(c.provider_code, c.model_id)
             and c.input_per_m <= settings.input_price_cap_usd_per_m
             and c.output_per_m <= settings.output_price_cap_usd_per_m,
         "price_kind": c.price_data.get("price_kind", "api")}
        for c in choices]}
