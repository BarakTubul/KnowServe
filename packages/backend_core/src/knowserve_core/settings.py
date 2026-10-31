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
    Libpq-only options such as ``channel_binding`` are dropped because asyncpg rejects them.
    """
    parts = urlsplit(url)
    scheme = parts.scheme
    if scheme in ("postgres", "postgresql"):
        scheme = "postgresql+asyncpg"
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key == "channel_binding":
            continue
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
    job_handler_timeout_seconds: int = Field(default=90, ge=1)
    # Total processing attempts per job (QStash deliveries included). Reconcile with QStash's
    # retry count: UNVERIFIED against a live QStash (docs/contracts/jobs-outbox.md).
    job_max_attempts: int = Field(default=4, ge=1)
    publish_timeout_seconds: float = Field(default=5.0, gt=0)
    publish_grace_seconds: int = Field(default=120, ge=0)
    # Must exceed QStash's longest default retry gap (about e^7.5 s = 1808 s, measured live) so a
    # job that still has a scheduled retry is not labelled stuck. Used only by `queued_stuck` and by the
    # requeue guard for queued jobs; the other recovery states do not depend on it.
    stuck_after_seconds: int = Field(default=2400, ge=1)

    # The batch dispatcher (multi-row dispatch_pending) is the optional scheduled-recovery path.
    # It is not mounted unless this is true (default false in M0).
    enable_recovery_dispatcher: bool = False

    # Operator test surface for the isolated spike (never public, never behind Pages).
    enable_spike_job_ops: bool = False
    enable_spike_failure_hooks: bool = False
    spike_operator_emails: Annotated[list[str], NoDecode] = Field(default_factory=list)
    spike_oidc_audience: str | None = None

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

    @field_validator("spike_operator_emails", mode="before")
    @classmethod
    def _split_emails(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip().lower() for item in value.split(",") if item.strip()]
        if isinstance(value, list):
            return [str(item).strip().lower() for item in value if str(item).strip()]
        return value

    @model_validator(mode="after")
    def _spike_job_guards(self) -> Settings:
        # Not coupled to job ops here: the Worker receives only the hooks flag (it registers the
        # test-only handlers) while the API receives both. The hooks are reachable only through the
        # operator routes, which exist only with job ops; Terraform enforces the pairing.
        if self.enable_spike_job_ops and not (
            self.spike_operator_emails and self.spike_oidc_audience
        ):
            raise ValueError(
                "KS_ENABLE_SPIKE_JOB_OPS needs KS_SPIKE_OPERATOR_EMAILS and KS_SPIKE_OIDC_AUDIENCE"
            )
        if self.job_handler_timeout_seconds >= self.job_lease_seconds:
            raise ValueError("KS_JOB_HANDLER_TIMEOUT_SECONDS must be below KS_JOB_LEASE_SECONDS")
        return self

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
