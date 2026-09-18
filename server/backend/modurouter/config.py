from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore", case_sensitive=False, hide_input_in_errors=True)

    environment: str = "development"
    web_origin: str = "http://localhost:3000"
    api_public_url: str = "http://localhost:3000"
    db_host: str = "127.0.0.1"
    db_port: int = 3306
    db_name: str = "modurouter"
    db_user: str = "modurouter"
    db_password: SecretStr = SecretStr("")
    session_secret: SecretStr = SecretStr("")
    google_client_id: str = ""
    admin_username: str = ""
    admin_password: SecretStr = SecretStr("")
    google_client_secret: SecretStr = SecretStr("")
    openrouter_api_key: SecretStr = SecretStr("")
    zenmux_api_key: SecretStr = SecretStr("")
    openai_api_key: SecretStr = SecretStr("")
    upstage_api_key: SecretStr = SecretStr("")
    enabled_providers: list[str] | None = None
    manual_model_allowlist: str | None = None
    allow_manual_selection: bool = True
    default_routing: dict = Field(default_factory=lambda: {"mode": "auto"})
    model_allowlist: str = ""
    tool_model_allowlist: str = ""
    input_price_cap_usd_per_m: Decimal = Field(default=Decimal("0"), ge=0)
    output_price_cap_usd_per_m: Decimal = Field(default=Decimal("0"), ge=0)
    user_daily_budget_usd: Decimal = Field(default=Decimal("0"), ge=0)
    user_daily_request_limit: int = Field(default=50, ge=1)
    guest_daily_request_limit: int = Field(default=30, ge=1)
    max_output_tokens: int = Field(default=1024, ge=1, le=8192)
    max_input_tokens: int = Field(default=16384, ge=512, le=32768)
    max_model_calls_per_run: int = Field(default=3, ge=1, le=3)
    max_tool_calls_per_run: int = Field(default=2, ge=1, le=2)
    run_timeout_seconds: int = Field(default=120, ge=10, le=120)
    platform_concurrency: int = Field(default=5, ge=1, le=5)
    price_refresh_seconds: int = 600
    price_stale_seconds: int = 1800
    session_days: int = 7
    upload_directory: Path = ROOT / "server/.runtime/uploads"
    max_upload_bytes: int = 10 * 1024 * 1024
    attachment_ttl_hours: int = 24

    @model_validator(mode="after")
    def production_configuration(self):
        if self.environment == "production":
            if not self.web_origin.startswith("https://") or not self.api_public_url.startswith("https://"):
                raise ValueError("Production origins must use HTTPS")
            if len(self.session_secret.get_secret_value()) < 32:
                raise ValueError("SESSION_SECRET must contain at least 32 characters")
            if not self.db_password.get_secret_value():
                raise ValueError("DB_PASSWORD is required")
        return self

    @property
    def database_url(self) -> URL:
        return URL.create("mysql+asyncmy", username=self.db_user,
                          password=self.db_password.get_secret_value(), host=self.db_host,
                          port=self.db_port, database=self.db_name, query={"charset": "utf8mb4"})

    @property
    def google_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret.get_secret_value())

    @property
    def admin_configured(self) -> bool:
        return bool(self.admin_username and self.admin_password.get_secret_value())

    @property
    def allowed_models(self) -> set[str]:
        return {x.strip() for x in self.model_allowlist.split(",") if x.strip()}

    @property
    def allowed_tool_models(self) -> set[str]:
        return {x.strip() for x in self.tool_model_allowlist.split(",") if x.strip()}

    @property
    def configured_providers(self) -> tuple[str, ...]:
        return tuple(code for code in ("openrouter", "zenmux", "openai", "upstage")
                     if getattr(self, f"{code}_api_key").get_secret_value()
                     and (self.enabled_providers is None or code in self.enabled_providers))

    def model_allowed(self, provider: str, model: str, *, tools: bool = False) -> bool:
        allowed = self.allowed_tool_models if tools else self.allowed_models
        return model in allowed or f"{provider}::{model}" in allowed

    def selectable_model(self, provider: str, model: str) -> bool:
        if self.manual_model_allowlist is None:
            return True
        allowed = {s.strip() for s in self.manual_model_allowlist.split(",") if s.strip()}
        return model in allowed or f"{provider}::{model}" in allowed


@lru_cache
def get_settings() -> Settings:
    return Settings()
