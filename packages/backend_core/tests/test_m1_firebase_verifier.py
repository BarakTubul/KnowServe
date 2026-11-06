"""M1-02a: the real Firebase token verifier (AUTH-07, AUTH-30, SEC-13), no network.

Two modes are exercised. Emulator mode uses ``mint_emulator_token`` (unsigned tokens, like the
Firebase Auth Emulator) with a fake clock. Real mode signs RS256 tokens with a throwaway key and
replaces only the HTTP fetch of Google's certificates, so signature, key lookup and the key-outage
path run through the real Admin SDK code.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from firebase_admin import _token_gen
from google.auth import crypt as google_crypt
from google.auth import exceptions as google_exceptions
from google.auth import jwt as google_jwt

from knowserve_core.clock import FakeClock
from knowserve_core.firebase_tokens import InvalidToken, StaleSignIn, VerifierUnavailable
from knowserve_core.firebase_verifier import EMULATOR_ENV_VAR, FirebaseTokenVerifier
from knowserve_core.settings import Settings
from knowserve_core.testing import DEFAULT_PROJECT_ID, mint_emulator_token

pytestmark = pytest.mark.m1

KID = "test-key-1"


@pytest.fixture(autouse=True)
def _restore_emulator_env() -> Iterator[None]:
    """The verifier exports the SDK's emulator variable (process-wide); never leak it."""
    saved = os.environ.get(EMULATOR_ENV_VAR)
    yield
    if saved is None:
        os.environ.pop(EMULATOR_ENV_VAR, None)
    else:
        os.environ[EMULATOR_ENV_VAR] = saved


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": "postgresql+asyncpg://u:p@localhost/db",
        "firebase_project_id": DEFAULT_PROJECT_ID,
        "firebase_auth_emulator_host": "localhost:9099",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def emulator_verifier(monkeypatch: pytest.MonkeyPatch, clock: FakeClock) -> Iterator[Any]:
    monkeypatch.setenv(EMULATOR_ENV_VAR, "localhost:9099")  # restored by monkeypatch afterwards
    verifier = FirebaseTokenVerifier(make_settings(), clock)
    yield verifier
    verifier.close()


def emulator_token(clock: FakeClock, uid: str = "uid-1", **kwargs: Any) -> str:
    kwargs.setdefault("issued_at", clock.now())
    return mint_emulator_token(uid, **kwargs)


def b64(data: dict[str, Any]) -> str:
    raw = json.dumps(data, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def unsigned_token(payload: dict[str, Any]) -> str:
    return f"{b64({'alg': 'none', 'typ': 'JWT'})}.{b64(payload)}."


def claims_at(clock: FakeClock, **overrides: Any) -> dict[str, Any]:
    now = int(clock.now().timestamp())
    claims: dict[str, Any] = {
        "iss": f"https://securetoken.google.com/{DEFAULT_PROJECT_ID}",
        "aud": DEFAULT_PROJECT_ID,
        "sub": "uid-1",
        "user_id": "uid-1",
        "iat": now,
        "auth_time": now,
        "exp": now + 3600,
        "firebase": {"identities": {}, "sign_in_provider": "password"},
    }
    claims.update(overrides)
    return claims


# --- emulator mode: claims, freshness, error mapping -------------------------------------------


async def test_auth_30_valid_token_returns_claims(emulator_verifier, clock: FakeClock) -> None:
    token = emulator_token(clock, email="a@example.test", email_verified=True, name="Ada")
    verified = await emulator_verifier.verify(token)
    assert verified.uid == "uid-1"
    assert verified.email == "a@example.test"
    assert verified.email_verified is True
    assert verified.sign_in_provider == "password"
    assert verified.name == "Ada"
    assert verified.auth_time == verified.issued_at == clock.now().replace(microsecond=0)


@pytest.mark.parametrize("provider", ["anonymous", "google.com", "password", "github.com"])
async def test_auth_30_provider_is_not_decided_by_the_verifier(
    emulator_verifier, clock: FakeClock, provider: str
) -> None:
    """Endpoints decide which providers they accept; the verifier only reports it."""
    verified = await emulator_verifier.verify(emulator_token(clock, provider=provider))
    assert verified.sign_in_provider == provider


async def test_auth_07_expired_token_is_invalid(emulator_verifier, clock: FakeClock) -> None:
    token = emulator_token(clock, lifetime=timedelta(minutes=10))
    clock.advance(minutes=10, seconds=1)
    with pytest.raises(InvalidToken):
        await emulator_verifier.verify(token)


async def test_auth_07_expired_and_stale_token_is_invalid_not_stale(
    emulator_verifier, clock: FakeClock
) -> None:
    token = emulator_token(clock)
    clock.advance(hours=3)
    for fresh in (True, False):
        with pytest.raises(InvalidToken):
            await emulator_verifier.verify(token, require_fresh=fresh)


async def test_auth_07_wrong_audience_is_invalid(emulator_verifier, clock: FakeClock) -> None:
    with pytest.raises(InvalidToken):
        await emulator_verifier.verify(emulator_token(clock, project_id="other-project"))


async def test_auth_07_wrong_issuer_is_invalid(emulator_verifier, clock: FakeClock) -> None:
    token = unsigned_token(claims_at(clock, iss="https://securetoken.google.com/other-project"))
    with pytest.raises(InvalidToken):
        await emulator_verifier.verify(token)


@pytest.mark.parametrize(
    "token",
    [
        "",
        "not-a-jwt",
        "a.b.c",
        "...",
        "e30.e30.",
        "x" * 9000,
    ],
)
async def test_auth_07_malformed_tokens_are_invalid(emulator_verifier, token: str) -> None:
    with pytest.raises(InvalidToken):
        await emulator_verifier.verify(token)


async def test_auth_07_claims_missing_or_wrong_type_are_invalid(
    emulator_verifier, clock: FakeClock
) -> None:
    for broken in (
        {"auth_time": None},
        {"iat": "yesterday"},
        {"exp": None},
        {"firebase": {}},
        {"firebase": None},
        {"sub": ""},
    ):
        claims = claims_at(clock, **broken)
        if broken.get("sub") == "":
            claims["user_id"] = ""
        with pytest.raises(InvalidToken):
            await emulator_verifier.verify(unsigned_token(claims))


async def test_auth_07_token_issued_in_the_future_is_invalid(
    emulator_verifier, clock: FakeClock
) -> None:
    future = clock.now() + timedelta(minutes=5)
    with pytest.raises(InvalidToken):
        await emulator_verifier.verify(emulator_token(clock, issued_at=future))


async def test_auth_30_stale_sign_in_is_reported_only_for_a_valid_token(
    emulator_verifier, clock: FakeClock
) -> None:
    """Old auth_time with a fresh iat: stale when fresh is required, fine for conversion."""
    old = clock.now() - timedelta(minutes=30)
    token = emulator_token(clock, auth_time=old)
    with pytest.raises(StaleSignIn):
        await emulator_verifier.verify(token)
    with pytest.raises(StaleSignIn):
        await emulator_verifier.verify(token, require_fresh=True)
    verified = await emulator_verifier.verify(token, require_fresh=False)  # conversion (ADR 0004)
    assert verified.uid == "uid-1"


async def test_auth_30_stale_wrong_audience_token_is_invalid_not_stale(
    emulator_verifier, clock: FakeClock
) -> None:
    old = clock.now() - timedelta(minutes=30)
    token = emulator_token(clock, auth_time=old, project_id="other-project")
    with pytest.raises(InvalidToken):
        await emulator_verifier.verify(token)


async def test_auth_30_iat_outside_the_window_is_stale_in_both_modes(
    emulator_verifier, clock: FakeClock
) -> None:
    token = emulator_token(clock)
    clock.advance(seconds=301)
    for fresh in (True, False):
        with pytest.raises(StaleSignIn):
            await emulator_verifier.verify(token, require_fresh=fresh)


async def test_auth_30_freshness_boundary_is_exactly_the_window(
    emulator_verifier, clock: FakeClock
) -> None:
    token = emulator_token(clock)
    clock.advance(seconds=300)
    assert (await emulator_verifier.verify(token)).uid == "uid-1"
    clock.advance(seconds=1)
    with pytest.raises(StaleSignIn):
        await emulator_verifier.verify(token)


async def test_auth_30_window_comes_from_settings(
    monkeypatch: pytest.MonkeyPatch, clock: FakeClock
) -> None:
    monkeypatch.setenv(EMULATOR_ENV_VAR, "localhost:9099")
    verifier = FirebaseTokenVerifier(make_settings(auth_max_age_seconds=60), clock)
    token = emulator_token(clock)
    clock.advance(seconds=61)
    with pytest.raises(StaleSignIn):
        await verifier.verify(token)
    verifier.close()


# --- emulator guards ---------------------------------------------------------------------------


def test_auth_30_emulator_is_refused_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(EMULATOR_ENV_VAR, raising=False)
    settings = make_settings().model_copy(update={"env": "production"})  # bypasses the validator
    with pytest.raises(RuntimeError, match="production"):
        FirebaseTokenVerifier(settings)


def test_auth_30_settings_validator_also_refuses_the_emulator_in_production() -> None:
    with pytest.raises(ValueError, match="EMULATOR_HOST"):
        make_settings(env="production")


def test_auth_30_raw_emulator_variable_without_the_setting_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(EMULATOR_ENV_VAR, "localhost:9099")
    with pytest.raises(RuntimeError, match=EMULATOR_ENV_VAR):
        FirebaseTokenVerifier(make_settings(firebase_auth_emulator_host=None))


def test_auth_30_emulator_setting_exports_the_sdk_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(EMULATOR_ENV_VAR, raising=False)
    verifier = FirebaseTokenVerifier(make_settings(firebase_auth_emulator_host="localhost:9199"))
    assert os.environ[EMULATOR_ENV_VAR] == "localhost:9199"
    assert verifier.emulated


# --- real mode: signatures through the SDK, certificate fetch replaced -------------------------


class _Response:
    status = 200
    headers: dict[str, str] = {}

    def __init__(self, certs: dict[str, str]) -> None:
        self.data = json.dumps(certs).encode()


def _new_key() -> tuple[google_crypt.RSASigner, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return google_crypt.RSASigner.from_string(private_pem, KID), public_pem.decode()


@pytest.fixture(scope="module")
def signing_key() -> tuple[google_crypt.RSASigner, str]:
    return _new_key()


@pytest.fixture
def real_verifier(
    monkeypatch: pytest.MonkeyPatch, signing_key: tuple[google_crypt.RSASigner, str]
) -> Iterator[FirebaseTokenVerifier]:
    monkeypatch.delenv(EMULATOR_ENV_VAR, raising=False)
    certs = {KID: signing_key[1]}

    def fake_fetch(self: Any, url: str, *args: Any, **kwargs: Any) -> _Response:
        return _Response(certs)

    monkeypatch.setattr(_token_gen.CertificateFetchRequest, "__call__", fake_fetch)
    verifier = FirebaseTokenVerifier(make_settings(firebase_auth_emulator_host=None))
    yield verifier
    verifier.close()


def signed_token(
    signer: google_crypt.RSASigner, payload: dict[str, Any], kid: str | None = KID
) -> str:
    return google_jwt.encode(signer, payload, key_id=kid).decode()


def real_claims(**overrides: Any) -> dict[str, Any]:
    return claims_at(FakeClock(datetime.now(UTC)), **overrides)


async def test_auth_07_real_mode_accepts_a_correctly_signed_token(
    real_verifier, signing_key
) -> None:
    verified = await real_verifier.verify(signed_token(signing_key[0], real_claims()))
    assert verified.uid == "uid-1"
    assert verified.sign_in_provider == "password"


async def test_auth_07_real_mode_forged_signature_is_invalid(real_verifier) -> None:
    other_signer, _ = _new_key()  # same kid, different private key
    with pytest.raises(InvalidToken):
        await real_verifier.verify(signed_token(other_signer, real_claims()))


async def test_auth_07_real_mode_unknown_key_id_is_invalid(real_verifier, signing_key) -> None:
    with pytest.raises(InvalidToken):
        await real_verifier.verify(signed_token(signing_key[0], real_claims(), kid="other-kid"))


async def test_auth_07_real_mode_wrong_audience_and_issuer_are_invalid(
    real_verifier, signing_key
) -> None:
    signer = signing_key[0]
    for broken in ({"aud": "other"}, {"iss": "https://securetoken.google.com/other"}):
        with pytest.raises(InvalidToken):
            await real_verifier.verify(signed_token(signer, real_claims(**broken)))


async def test_auth_07_real_mode_expired_token_is_invalid(real_verifier, signing_key) -> None:
    now = int(time.time())
    claims = real_claims(iat=now - 7200, auth_time=now - 7200, exp=now - 3600)
    with pytest.raises(InvalidToken):
        await real_verifier.verify(signed_token(signing_key[0], claims))


async def test_auth_30_real_mode_forged_token_with_old_auth_time_is_invalid_not_stale(
    real_verifier,
) -> None:
    other_signer, _ = _new_key()
    old = int(time.time()) - 3600
    token = signed_token(other_signer, real_claims(auth_time=old, exp=int(time.time()) + 3600))
    with pytest.raises(InvalidToken):
        await real_verifier.verify(token)


async def test_auth_30_real_mode_valid_token_with_old_auth_time_is_stale(
    real_verifier, signing_key
) -> None:
    claims = real_claims(auth_time=int(time.time()) - 3600)
    token = signed_token(signing_key[0], claims)
    with pytest.raises(StaleSignIn):
        await real_verifier.verify(token)
    assert (await real_verifier.verify(token, require_fresh=False)).uid == "uid-1"


async def test_auth_30_real_mode_refuses_unsigned_tokens(real_verifier) -> None:
    now = datetime.now(UTC)
    with pytest.raises(InvalidToken):
        await real_verifier.verify(mint_emulator_token("uid-1", issued_at=now))


async def test_auth_30_real_mode_fails_closed_if_the_emulator_variable_appears(
    real_verifier, signing_key, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(EMULATOR_ENV_VAR, "localhost:9099")
    with pytest.raises(VerifierUnavailable):
        await real_verifier.verify(signed_token(signing_key[0], real_claims()))


async def test_sec_13_key_fetch_failure_fails_closed(
    monkeypatch: pytest.MonkeyPatch, signing_key
) -> None:
    monkeypatch.delenv(EMULATOR_ENV_VAR, raising=False)

    def outage(self: Any, url: str, *args: Any, **kwargs: Any) -> _Response:
        raise google_exceptions.TransportError("connection refused")

    monkeypatch.setattr(_token_gen.CertificateFetchRequest, "__call__", outage)
    verifier = FirebaseTokenVerifier(make_settings(firebase_auth_emulator_host=None))
    try:
        with pytest.raises(VerifierUnavailable):
            await verifier.verify(signed_token(signing_key[0], real_claims()))
    finally:
        verifier.close()


async def test_sec_13_non_200_key_response_fails_closed(
    monkeypatch: pytest.MonkeyPatch, signing_key
) -> None:
    monkeypatch.delenv(EMULATOR_ENV_VAR, raising=False)

    def bad_gateway(self: Any, url: str, *args: Any, **kwargs: Any) -> _Response:
        response = _Response({})
        response.status = 502
        return response

    monkeypatch.setattr(_token_gen.CertificateFetchRequest, "__call__", bad_gateway)
    verifier = FirebaseTokenVerifier(make_settings(firebase_auth_emulator_host=None))
    try:
        with pytest.raises(VerifierUnavailable):
            await verifier.verify(signed_token(signing_key[0], real_claims()))
    finally:
        verifier.close()


async def test_sec_13_missing_project_id_fails_closed(
    monkeypatch: pytest.MonkeyPatch, signing_key
) -> None:
    monkeypatch.delenv(EMULATOR_ENV_VAR, raising=False)
    verifier = FirebaseTokenVerifier(
        make_settings(firebase_auth_emulator_host=None, firebase_project_id=None)
    )
    with pytest.raises(VerifierUnavailable):
        await verifier.verify(signed_token(signing_key[0], real_claims()))


async def test_auth_30_blocking_key_fetch_does_not_block_the_event_loop(
    monkeypatch: pytest.MonkeyPatch, signing_key
) -> None:
    monkeypatch.delenv(EMULATOR_ENV_VAR, raising=False)

    def slow_outage(self: Any, url: str, *args: Any, **kwargs: Any) -> _Response:
        time.sleep(0.3)
        raise google_exceptions.TransportError("slow")

    monkeypatch.setattr(_token_gen.CertificateFetchRequest, "__call__", slow_outage)
    verifier = FirebaseTokenVerifier(make_settings(firebase_auth_emulator_host=None))
    ticks = 0

    async def ticker() -> None:
        nonlocal ticks
        for _ in range(20):
            await asyncio.sleep(0.01)
            ticks += 1

    try:
        results = await asyncio.gather(
            verifier.verify(signed_token(signing_key[0], real_claims())),
            ticker(),
            return_exceptions=True,
        )
    finally:
        verifier.close()
    assert isinstance(results[0], VerifierUnavailable)
    assert ticks == 20


def test_auth_30_each_verifier_uses_its_own_firebase_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(EMULATOR_ENV_VAR, raising=False)
    first = FirebaseTokenVerifier(make_settings(firebase_auth_emulator_host=None))
    second = FirebaseTokenVerifier(make_settings(firebase_auth_emulator_host=None))
    assert first._app_name != second._app_name  # pyright: ignore[reportPrivateUsage]
