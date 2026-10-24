"""ARCH-12: typed settings; Neon-style URLs are normalized for asyncpg."""

import pytest
from pydantic import ValidationError

from knowserve_core.settings import Settings, normalize_database_url


@pytest.mark.m0
def test_arch_12_neon_url_is_normalized_for_asyncpg() -> None:
    url = "postgresql://user:pw@ep-x.neon.tech/db?sslmode=require"
    assert (
        normalize_database_url(url) == "postgresql+asyncpg://user:pw@ep-x.neon.tech/db?ssl=require"
    )


@pytest.mark.m0
def test_arch_12_asyncpg_url_is_left_unchanged() -> None:
    url = "postgresql+asyncpg://u:p@localhost:5433/knowserve"
    assert normalize_database_url(url) == url


@pytest.mark.m0
def test_arch_12_missing_database_url_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KS_DATABASE_URL", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]


@pytest.mark.m0
def test_arch_12_origins_are_parsed_from_a_comma_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KS_DATABASE_URL", "postgresql://u:p@h/db")
    monkeypatch.setenv("KS_API_ALLOWED_ORIGINS", "https://app.example.test, http://localhost:5173")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.api_allowed_origins == ["https://app.example.test", "http://localhost:5173"]


@pytest.mark.m0
def test_arch_12_production_rejects_local_dispatcher_token_and_wildcard_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KS_DATABASE_URL", "postgresql://u:p@h/db")
    monkeypatch.setenv("KS_ENV", "production")
    monkeypatch.setenv("KS_DISPATCHER_LOCAL_TOKEN", "x")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]
    monkeypatch.delenv("KS_DISPATCHER_LOCAL_TOKEN")
    monkeypatch.setenv("KS_API_ALLOWED_ORIGINS", "*")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]
