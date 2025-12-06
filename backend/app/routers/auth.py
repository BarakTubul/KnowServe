# app/routers/auth.py

from fastapi import APIRouter, HTTPException
from app.controllers.auth_controller import AuthController
from app.pydantic_schemas.auth_schema import RegisterRequest, LoginRequest
import logging

router = APIRouter(tags=["Auth"])
logger = logging.getLogger(__name__)


@router.post("/register")
async def register_user(request: RegisterRequest):
    try:
        return await AuthController.register(request)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))

    except Exception:
        logger.exception("Unexpected error during registration")
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred. Please try again later.",
        )


@router.post("/login")
async def login_user(request: LoginRequest):
    try:
        return await AuthController.login(request)

    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    except Exception:
        logger.exception("Unexpected error during login")
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred. Please try again later.",
        )
