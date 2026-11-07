"""Test helpers shared by every slice (M1-01 fixtures). Not used by production code paths.

``mint_emulator_token`` builds an unsigned Firebase-style ID token like the Firebase Auth Emulator
issues (``alg: none``). The real verifier accepts such tokens only when ``KS_ENV`` is not
``production`` and ``KS_FIREBASE_AUTH_EMULATOR_HOST`` is set, so integration tests exercise the
real verification path without the network (AUTH-30).
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from typing import Any

DEFAULT_PROJECT_ID = "demo-knowserve"


def _b64(data: dict[str, Any]) -> str:
    raw = json.dumps(data, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def mint_emulator_token(
    uid: str,
    *,
    email: str | None = None,
    email_verified: bool = False,
    provider: str = "password",
    project_id: str = DEFAULT_PROJECT_ID,
    auth_time: datetime | None = None,
    issued_at: datetime | None = None,
    lifetime: timedelta = timedelta(hours=1),
    name: str | None = None,
) -> str:
    """Return an unsigned ID token; ``provider`` is password, google.com or anonymous."""
    now = datetime.now(UTC)
    iat = issued_at or now
    auth = auth_time or iat
    identities: dict[str, list[str]] = {}
    if email and provider == "password":
        identities["email"] = [email]
    if email and provider == "google.com":
        identities["google.com"] = [f"google-{uid}"]
        identities["email"] = [email]
    payload: dict[str, Any] = {
        "iss": f"https://securetoken.google.com/{project_id}",
        "aud": project_id,
        "auth_time": int(auth.timestamp()),
        "user_id": uid,
        "sub": uid,
        "iat": int(iat.timestamp()),
        "exp": int((iat + lifetime).timestamp()),
        "firebase": {"identities": identities, "sign_in_provider": provider},
    }
    if email:
        payload["email"] = email
        payload["email_verified"] = email_verified
    if name:
        payload["name"] = name
    return f"{_b64({'alg': 'none', 'typ': 'JWT'})}.{_b64(payload)}."


# --- M2 document fixtures (Owner-written; slices import these instead of writing rows by hand) ---

DEPARTMENT_IDS = {
    "human-resources": "5bb20871-4372-57f0-9e45-9e20db142d70",
    "finance": "4f3257da-409f-5643-b889-67eea4d34f21",
    "engineering": "2785b8aa-6102-5d05-b400-0fb9de71b614",
    "legal": "3174db2f-1584-5ddb-8fbd-60b4157086d3",
    "sales": "5e306cf1-a61b-54b2-ade8-717f9ff783b0",
}


async def make_document(
    session: Any,
    *,
    owner: str = "finance",
    allowed: tuple[str, ...] = ("finance",),
    status: str | None = "ready",
    deleted: bool = False,
    title: str = "Sample document",
    filename: str = "sample.pdf",
    page_count: int = 3,
    created_at: datetime | None = None,
) -> Any:
    """Insert a document with one revision and access rows; return the ``Document``.

    ``status=None`` leaves ``current_revision_id`` unset (no current revision). A non-ready
    status leaves ``page_count`` and ``ready_at`` empty, as the lifecycle does. The caller commits.
    """
    import uuid

    from sqlalchemy import update

    from .models import Document, DocumentDepartmentAccess, DocumentRevision

    doc = Document(
        id=uuid.uuid4(),
        title=title,
        filename=filename,
        owner_department_id=uuid.UUID(DEPARTMENT_IDS[owner]),
    )
    if created_at is not None:
        doc.created_at = created_at
    if deleted:
        doc.deleted_at = datetime.now(UTC)
    session.add(doc)
    await session.flush()
    for slug in allowed:
        session.add(
            DocumentDepartmentAccess(
                document_id=doc.id, department_id=uuid.UUID(DEPARTMENT_IDS[slug])
            )
        )
    if status is not None:
        rev = DocumentRevision(
            id=uuid.uuid4(),
            document_id=doc.id,
            storage_key=f"documents/{doc.id}/rev.pdf",
            status=status,
            page_count=page_count if status == "ready" else None,
            ready_at=datetime.now(UTC) if status == "ready" else None,
            size_bytes=1024,
            content_type="application/pdf",
        )
        session.add(rev)
        await session.flush()
        await session.execute(
            update(Document).where(Document.id == doc.id).values(current_revision_id=rev.id)
        )
        await session.flush()
    return doc
