"""M1-01: configuration keys and their guards (AUTH-10, AUTH-28 successor, AUTH-30, AUTH-36)."""

import pytest
from pydantic import ValidationError

from knowserve_core.settings import Settings

pytestmark = pytest.mark.m1

DB = "postgresql+asyncpg://u:p@localhost/db"


def make(**kw: object) -> Settings:
    return Settings(_env_file=None, database_url=DB, **kw)  # type: ignore[call-arg]


def test_m1_defaults_match_the_approved_decisions() -> None:
    """OPEN-25 / OPEN-26: 24 h sessions, 48 h Demo retention, approved limits."""
    s = make()
    assert s.session_ttl_seconds == 24 * 3600
    assert s.demo_retention_seconds == 48 * 3600
    assert s.auth_max_age_seconds == 300
    assert (s.demo_start_limit, s.demo_start_window_seconds) == (5, 3600)
    assert (s.quota_demo_daily, s.quota_registered_daily, s.quota_admin_daily) == (20, 100, 100)
    assert s.ai_global_daily_quota == 100
    assert s.ai_kill_switch is False


def test_m1_limits_are_configurable_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every numeric limit is configuration, not code (AUTH-36)."""
    monkeypatch.setenv("KS_QUOTA_DEMO_DAILY", "7")
    monkeypatch.setenv("KS_AI_GLOBAL_DAILY_QUOTA", "250")
    monkeypatch.setenv("KS_DEMO_START_LIMIT", "9")
    s = make()
    assert (s.quota_demo_daily, s.ai_global_daily_quota, s.demo_start_limit) == (7, 250, 9)


def test_m1_production_refuses_the_firebase_emulator() -> None:
    """AUTH-30: the emulator accepts unsigned tokens, so it can never be set in production."""
    with pytest.raises(ValidationError, match="EMULATOR_HOST"):
        make(
            env="production",
            firebase_auth_emulator_host="localhost:9099",
            api_allowed_origins=["https://app.example.test"],
        )
    ok = make(env="local", firebase_auth_emulator_host="localhost:9099")
    assert ok.firebase_auth_emulator_host == "localhost:9099"
