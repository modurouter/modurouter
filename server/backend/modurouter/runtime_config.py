"""Non-secret routing policy shared by API processes and the worker."""
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings
from .models import RuntimeSettings
from .router import RoutingPreference

ProviderCode = Literal['openrouter', 'zenmux', 'openai', 'upstage']


class RoutingPolicy(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    enabled_providers: list[ProviderCode] = Field(max_length=4)
    model_allowlist: list[str] = Field(max_length=2000)
    tool_model_allowlist: list[str] = Field(max_length=2000)
    manual_model_allowlist: list[str] | None = Field(default=None, max_length=2000)
    allow_manual_selection: bool = True
    default_routing: RoutingPreference = Field(default_factory=RoutingPreference)
    input_price_cap_usd_per_m: Decimal = Field(ge=0, le=10000)
    output_price_cap_usd_per_m: Decimal = Field(ge=0, le=10000)
    user_daily_budget_usd: Decimal = Field(ge=0, le=100000)
    user_daily_request_limit: int = Field(ge=1, le=100000)
    guest_daily_request_limit: int = Field(ge=1, le=100000)
    max_input_tokens: int = Field(ge=512, le=32768)
    max_output_tokens: int = Field(ge=1, le=8192)
    max_model_calls_per_run: int = Field(ge=1, le=3)
    max_tool_calls_per_run: int = Field(ge=1, le=2)
    run_timeout_seconds: int = Field(ge=10, le=120)
    platform_concurrency: int = Field(ge=1, le=5)
    price_refresh_seconds: int = Field(ge=30, le=86400)
    price_stale_seconds: int = Field(ge=60, le=172800)

    @field_validator('model_allowlist', 'tool_model_allowlist', 'manual_model_allowlist')
    @classmethod
    def model_names(cls, values):
        if values is None:
            return None
        cleaned = sorted({value.strip() for value in values if value.strip()})
        for value in cleaned:
            provider, separator, model = value.partition('::')
            if len(value) > 290 or ',' in value or any(c.isspace() for c in value):
                raise ValueError('Invalid model identifier')
            if separator and (provider not in ('openrouter','zenmux','openai','upstage') or not model):
                raise ValueError('Invalid provider-qualified model')
        return cleaned

    @model_validator(mode='after')
    def coherent_policy(self):
        if len(set(self.enabled_providers)) != len(self.enabled_providers):
            raise ValueError('Duplicate provider')
        if self.price_stale_seconds < self.price_refresh_seconds:
            raise ValueError('Stale threshold must cover the refresh interval')
        if self.default_routing.mode == 'manual':
            if not self.allow_manual_selection or self.default_routing.provider not in self.enabled_providers:
                raise ValueError('Default model must be enabled')
            if self.manual_model_allowlist is not None and not any(value in self.manual_model_allowlist for value in (
                self.default_routing.model_id, f'{self.default_routing.provider}::{self.default_routing.model_id}')):
                raise ValueError('Default model must be selectable')
        return self

    @classmethod
    def from_settings(cls, settings: Settings):
        values = {name: getattr(settings, name) for name in cls.model_fields}
        values['enabled_providers'] = list(settings.configured_providers)
        for name in ('model_allowlist', 'tool_model_allowlist', 'manual_model_allowlist'):
            raw = getattr(settings, name)
            values[name] = None if raw is None else [s.strip() for s in raw.split(',') if s.strip()]
        return cls(**values)

    def apply(self, base: Settings) -> Settings:
        values = self.model_dump()
        for name in ('model_allowlist', 'tool_model_allowlist', 'manual_model_allowlist'):
            values[name] = None if values[name] is None else ','.join(values[name])
        return base.model_copy(update=values)


async def effective_settings(db: AsyncSession, base: Settings) -> Settings:
    stored = await db.get(RuntimeSettings, 'routing')
    return RoutingPolicy(**stored.values).apply(base) if stored else base
