"""Typed settings (ARCH-12). Every key is listed in .env.example and the config contract."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from .ingestion_contract import EMBEDDING_DIMENSIONS


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
    # Pepper for the keyed hash of the client address in rate-limit keys (SEC-18, OPEN-28 Q9).
    # Optional here so the Worker needs no value; the API requires it when KS_ENV=production and
    # uses a random per-process pepper otherwise.
    ip_hash_pepper: SecretStr | None = None

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
    # job that still has a scheduled retry is not labelled stuck. Used only by `queued_stuck` and
    # by the requeue guard for queued jobs; the other recovery states do not depend on it.
    stuck_after_seconds: int = Field(default=2400, ge=1)

    # The batch dispatcher (multi-row dispatch_pending) is the optional scheduled-recovery path.
    # It is not mounted unless this is true (default false in M0).
    enable_recovery_dispatcher: bool = False

    # Operator test surface for the isolated spike (never public, never behind Pages).
    enable_spike_job_ops: bool = False
    enable_spike_failure_hooks: bool = False
    spike_operator_emails: Annotated[list[str], NoDecode] = Field(default_factory=list)
    spike_oidc_audience: str | None = None

    # --- M1 auth and limits (docs/contracts/config-and-deploy.md; defaults are OPEN-25/26) ---
    # Firebase project id the ID token audience must match. Locally the Auth Emulator uses a
    # `demo-` project id.
    firebase_project_id: str | None = None
    # Host of the Firebase Auth Emulator (for example `localhost:9099`). Refused in production.
    firebase_auth_emulator_host: str | None = None
    session_cookie_name: str = "ks_session"
    # Absolute lifetime of every session kind (AUTH-10). Never extended by use.
    session_ttl_seconds: int = Field(default=24 * 3600, ge=60)
    # A sign-in older than this cannot start a session (AUTH-30, ADR 0004).
    auth_max_age_seconds: int = Field(default=300, ge=30)
    # Unconverted Demo data is kept this long from creation (AUTH-35).
    demo_retention_seconds: int = Field(default=48 * 3600, ge=3600)
    demo_cleanup_batch_size: int = Field(default=500, ge=1)
    demo_start_limit: int = Field(default=5, ge=1)
    demo_start_window_seconds: int = Field(default=3600, ge=1)
    # Daily AI question limits per user, counted per UTC day (AUTH-36); chat applies them in M4.
    quota_demo_daily: int = Field(default=20, ge=0)
    quota_registered_daily: int = Field(default=100, ge=0)
    quota_admin_daily: int = Field(default=100, ge=0)
    # Global usage guard, an operational guard and not a spending cap (OPEN-26 N1).
    ai_global_daily_quota: int = Field(default=100, ge=0)
    ai_kill_switch: bool = False
    # One-time Admin provisioning (AUTH-04). Not secrets: the Firebase uid and email.
    admin_firebase_uid: str | None = None
    admin_email: str | None = None

    # --- M2 documents (docs/contracts/config-and-deploy.md) ---
    # `filesystem` for local development, `fake` for tests, `r2` in production (Q6).
    object_store: Literal["filesystem", "fake", "r2"] = "filesystem"
    object_store_path: str = ".local/objects"
    r2_endpoint: str | None = None
    r2_bucket: str | None = None
    r2_access_key_id: SecretStr | None = None
    r2_secret_access_key: SecretStr | None = None
    # Library list page size (DOC-01, Q3).
    documents_page_default: int = Field(default=20, ge=1)
    documents_page_max: int = Field(default=50, ge=1)

    # --- M3 upload and ingestion (docs/contracts/config-and-deploy.md; defaults are OPEN-31 D1) ---
    # Stop switch for new uploads (D14). Reads, access changes, delete and retry keep working.
    uploads_enabled: bool = True
    upload_max_pdf_bytes: int = Field(default=20 * 1024 * 1024, ge=1)
    upload_max_pdf_pages: int = Field(default=300, ge=1)
    upload_max_zip_bytes: int = Field(default=25 * 1024 * 1024, ge=1)
    upload_max_zip_files: int = Field(default=20, ge=1)
    upload_max_zip_uncompressed_bytes: int = Field(default=100 * 1024 * 1024, ge=1)
    upload_max_zip_ratio: int = Field(default=20, ge=1)
    upload_max_manifest_bytes: int = Field(default=256 * 1024, ge=1)
    # Documents `queued` or `processing` at once, and new documents per UTC day.
    upload_max_in_flight: int = Field(default=10, ge=1)
    upload_max_per_day: int = Field(default=50, ge=1)
    chunk_size_tokens: int = Field(default=512, ge=16)
    chunk_overlap_tokens: int = Field(default=64, ge=0)
    # `openai` calls the provider; `fake` is deterministic and refused in production.
    embedding_provider: Literal["openai", "fake"] = "openai"
    embedding_model: str = "text-embedding-3-small"
    # Must equal the width of `document_chunks.embedding` (migration 0004).
    embedding_dimensions: int = Field(default=1536, ge=1)
    embedding_batch_size: int = Field(default=64, ge=1)
    embedding_timeout_seconds: float = Field(default=30.0, gt=0)
    openai_api_key: SecretStr | None = None
    # Hard limit for the child process that extracts PDF text (D11).
    pdf_extraction_timeout_seconds: int = Field(default=60, ge=1)
    # Status stream: keepalive comment interval and the length after which the server ends the
    # stream so the client reconnects.
    sse_keepalive_seconds: int = Field(default=15, ge=1)
    sse_max_seconds: int = Field(default=120, ge=1)

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
        # No handler-timeout < lease rule since M3-00a: the lease heartbeat keeps a long job claimed.
        return self

    @model_validator(mode="after")
    def _ingestion_limits(self) -> Settings:
        if self.chunk_overlap_tokens >= self.chunk_size_tokens:
            raise ValueError("KS_CHUNK_OVERLAP_TOKENS must be below KS_CHUNK_SIZE_TOKENS")
        if self.embedding_dimensions != EMBEDDING_DIMENSIONS:
            raise ValueError(
                f"KS_EMBEDDING_DIMENSIONS must be {EMBEDDING_DIMENSIONS}, the width of the "
                "document_chunks.embedding column; a different width needs a new migration"
            )
        if self.upload_max_zip_bytes > self.upload_max_zip_uncompressed_bytes:
            raise ValueError("KS_UPLOAD_MAX_ZIP_BYTES must not exceed the uncompressed total")
        return self

    @model_validator(mode="after")
    def _production_guards(self) -> Settings:
        if self.env == "production":
            if self.dispatcher_local_token is not None:
                raise ValueError("KS_DISPATCHER_LOCAL_TOKEN must not be set when KS_ENV=production")
            if "*" in self.api_allowed_origins:
                raise ValueError("KS_API_ALLOWED_ORIGINS must list explicit origins, not '*'")
            # The emulator accepts unsigned tokens, so it must never be reachable in production.
            if self.firebase_auth_emulator_host:
                raise ValueError(
                    "KS_FIREBASE_AUTH_EMULATOR_HOST must not be set when KS_ENV=production"
                )
            # Fake embeddings would index meaningless vectors, so they never run in production.
            if self.embedding_provider == "fake":
                raise ValueError("KS_EMBEDDING_PROVIDER=fake is not allowed when KS_ENV=production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # values come from the environment
