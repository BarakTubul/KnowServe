"""One-time, idempotent Admin provisioning (AUTH-04, M1-05).

    python -m knowserve_api.admin_seed

Reads ``KS_DATABASE_URL``, ``KS_ADMIN_FIREBASE_UID`` and ``KS_ADMIN_EMAIL`` (nothing else, so it
runs in a migration-style job without the API, proxy or QStash settings). It binds the single Admin
to the Firebase ``uid``: it creates the ``users`` row with kind ``admin`` or promotes the existing
row of that uid. It refuses to run if another Admin with a different uid exists, or if the email
already belongs to another user. Running it twice changes nothing. No password is handled and no
HTTP route does this. It prints no secrets: only ``created``, ``promoted`` or ``unchanged``.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from knowserve_core import audit
from knowserve_core.db import create_engine, create_session_factory
from knowserve_core.models import User
from knowserve_core.settings import normalize_database_url

Outcome = Literal["created", "promoted", "unchanged"]


class ProvisioningError(Exception):
    """Provisioning refused; the message never contains the uid or the email."""


def normalize_email(value: str) -> str:
    return value.strip().lower()


async def provision_admin(
    factory: async_sessionmaker[AsyncSession], *, firebase_uid: str, email: str
) -> Outcome:
    uid = firebase_uid.strip()
    normalized = normalize_email(email)
    if not uid or not normalized or "@" not in normalized:
        raise ProvisioningError("A Firebase uid and a valid email are required")
    async with factory() as db, db.begin():
        other_admin = await db.scalar(
            select(User.id).where(User.kind == "admin", User.firebase_uid != uid)
        )
        if other_admin is not None:
            raise ProvisioningError("Another Admin is already provisioned; refusing to continue")
        email_owner = await db.scalar(
            select(User).where(User.email == normalized, User.firebase_uid != uid)
        )
        if email_owner is not None:
            raise ProvisioningError("The Admin email belongs to a different account")
        user = await db.scalar(select(User).where(User.firebase_uid == uid).with_for_update())
        outcome: Outcome
        if user is None:
            user = User(firebase_uid=uid, kind="admin", email=normalized)
            db.add(user)
            await db.flush()
            outcome = "created"
        elif user.kind == "demo":
            raise ProvisioningError("The Firebase uid belongs to a Demo identity")
        elif user.kind == "admin" and user.email == normalized:
            return "unchanged"
        else:
            user.kind = "admin"
            user.email = normalized
            outcome = "promoted"
        await audit.record(db, "admin.provisioned", user_id=user.id, outcome=outcome)
        return outcome


async def _run() -> int:
    url = os.environ.get("KS_DATABASE_URL")
    uid = os.environ.get("KS_ADMIN_FIREBASE_UID")
    email = os.environ.get("KS_ADMIN_EMAIL")
    if not (url and uid and email):
        print(
            "KS_DATABASE_URL, KS_ADMIN_FIREBASE_UID and KS_ADMIN_EMAIL must all be set",
            file=sys.stderr,
        )
        return 2
    engine = create_engine(normalize_database_url(url), null_pool=True)
    try:
        outcome = await provision_admin(
            create_session_factory(engine), firebase_uid=uid, email=email
        )
    except ProvisioningError as exc:
        print(f"admin provisioning refused: {exc}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()
    print(f"admin provisioning: {outcome}")
    return 0


def main() -> None:
    sys.exit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
