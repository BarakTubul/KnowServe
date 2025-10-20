# app/dependencies/auth.py
from fastapi import Header, HTTPException, status, Depends
from typing import Optional
from app.utils.jwt import decode_access_token
import json


# ------------------------------------------------------
#  Extract JWT manually from the Authorization header
# ------------------------------------------------------

def get_current_user(authorization: Optional[str] = Header(None)) -> dict:
    """
    Extracts and verifies the JWT token manually from the Authorization header.
    Expected format: 'Authorization: Bearer <token>'
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing",
        )

    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization format. Use 'Bearer <token>'",
        )

    token = authorization.split(" ")[1]
    payload = decode_access_token(token)

    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    # Parse payload if encoded as JSON string
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            pass

    return payload


# ------------------------------------------------------
#  Role-based access guards
# ------------------------------------------------------

def require_user(user: dict = Depends(get_current_user)):
    """Accessible to any authenticated user."""
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User authentication required.",
        )
    return user


def require_admin(user: dict = Depends(get_current_user)):
    """Restrict access to admin users only."""
    if user.get("role") != "ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this resource.",
        )
    return user
