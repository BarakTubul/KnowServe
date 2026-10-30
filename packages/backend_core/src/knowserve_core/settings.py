"""Typed settings (ARCH-12). Every key is listed in .env.example and the config contract."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def normalize_database_url(url: str) -> str:
    """Return an asyncpg SQLAlchemy URL.

    Providers such as Neon hand out ``postgresql://...?sslmode=require``. SQLAlchemy needs the
    ``+asyncpg`` driver, and asyncpg expects ``ssl=`` instead of ``sslmode=``.
    """
    parts = urlsplit(url)
    scheme = parts.scheme
    if scheme in ("postgres", "postgresql"):
        scheme = "postgresql+asyncpg"
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key == "sslmode":
            key = "ssl"
        query.append((key, value))
    return urlunsplit((scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KS_", env_file=".env", extra="ignore")

    env: Literal["local", "ci", "production"] = "local"
    log_level: str = "INFO"
    database_url: str

    api_allowed_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )
    enable_spike_endpoints: bool = False
    proxy_shared_secret: SecretStr | None = None

    qstash_url: str = "https://qstash.upstash.io"
    qstash_token: SecretStr | None = None
    qstash_current_signing_key: SecretStr | None = None
    qstash_next_signing_key: SecretStr | None = None
    worker_public_url: str | None = None

    dispatcher_oidc_audience: str | None = None
    dispatcher_oidc_service_account: str | None = None
    dispatcher_local_token: SecretStr | None = None

    outbox_lease_seconds: int = 60
    outbox_batch_size: int = 20
    job_lease_seconds: int = 120

    @field_validator("database_url")
    @classmethod
    def _normalize_url(cls, value: str) -> str:
        return normalize_database_url(value)

    @field_validator("api_allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @model_validator(mode="after")
    def _production_guards(self) -> Settings:
        if self.env == "production":
            if self.dispatcher_local_token is not None:
                raise ValueError("KS_DISPATCHER_LOCAL_TOKEN must not be set when KS_ENV=production")
            if "*" in self.api_allowed_origins:
                raise ValueError("KS_API_ALLOWED_ORIGINS must list explicit origins, not '*'")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # values come from the environment
