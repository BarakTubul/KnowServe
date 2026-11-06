"""M1-01: the emulator-style token factory is accepted by the real Firebase Admin verifier.

This is what lets every slice's integration tests run the real verification path without a network
or the emulator process (AUTH-30). It never touches production code or settings.
"""

from datetime import UTC, datetime, timedelta

import firebase_admin
import pytest
from firebase_admin import auth

from knowserve_core.testing import DEFAULT_PROJECT_ID, mint_emulator_token

pytestmark = pytest.mark.m1


@pytest.fixture(scope="module")
def admin_app():
    import os

    os.environ["FIREBASE_AUTH_EMULATOR_HOST"] = "localhost:9099"
    app = firebase_admin.initialize_app(
        options={"projectId": DEFAULT_PROJECT_ID}, name="m1-token-fixture"
    )
    yield app
    firebase_admin.delete_app(app)
    os.environ.pop("FIREBASE_AUTH_EMULATOR_HOST", None)


def test_m1_minted_token_round_trips_through_the_admin_verifier(admin_app) -> None:
    token = mint_emulator_token("uid-1", email="a@example.test", email_verified=True)
    claims = auth.verify_id_token(token, app=admin_app)
    assert claims["uid"] == "uid-1"
    assert claims["email_verified"] is True
    assert claims["firebase"]["sign_in_provider"] == "password"


def test_m1_minted_tokens_carry_provider_and_times(admin_app) -> None:
    old = datetime.now(UTC) - timedelta(minutes=30)
    token = mint_emulator_token(
        "uid-2", provider="anonymous", auth_time=old, issued_at=datetime.now(UTC)
    )
    claims = auth.verify_id_token(token, app=admin_app)
    assert claims["firebase"]["sign_in_provider"] == "anonymous"
    assert claims["auth_time"] < claims["iat"]  # a stale sign-in with a fresh token (conversion)


def test_m1_wrong_project_audience_is_rejected(admin_app) -> None:
    token = mint_emulator_token("uid-3", project_id="some-other-project")
    with pytest.raises(auth.InvalidIdTokenError):
        auth.verify_id_token(token, app=admin_app)
