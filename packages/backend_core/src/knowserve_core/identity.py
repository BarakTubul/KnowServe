"""The authenticated identity every protected route works with (contract: auth-session.md).

``get_identity``, ``require_admin``, ``require_registered`` and ``require_active_department`` are
the FastAPI dependencies built on this type; they live in ``knowserve_api.auth`` (M1-02a).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

IdentityKind = Literal["demo", "registered", "admin"]
SignInProvider = Literal["password", "google.com", "anonymous"]


@dataclass(frozen=True)
class Identity:
    kind: IdentityKind
    user_id: uuid.UUID
    firebase_uid: str
    session_id: uuid.UUID
    sign_in_provider: str
    email: str | None
    display_name: str | None
    active_department_id: uuid.UUID | None
    expires_at: datetime
    csrf_token: str

    @property
    def is_admin(self) -> bool:
        return self.kind == "admin"
