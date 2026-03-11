from fastapi import APIRouter, HTTPException, Response, Depends
from app.controllers.auth_controller import AuthController
from app.pydantic_schemas.auth_schema import RegisterRequest, LoginRequest
from app.utils.auth import get_current_user
import logging

router = APIRouter(tags=["Auth"])
logger = logging.getLogger(__name__)


@router.post("/register")
async def register_user(request: RegisterRequest, response: Response):
    try:
        # In this flow, we might just register, or register & auto-login.
        # AuthController.register returns {"message": ...}
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
async def login_user(request: LoginRequest, response: Response):
    try:
        data = await AuthController.login(request)
        
        # Set HttpOnly Cookie
        response.set_cookie(
            key="token",
            value=data["access_token"],
            httponly=True,
            max_age=86400,
            samesite="strict",
            secure=False  # Set to True in production with HTTPS
        )
        
        return data

    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    except Exception:
        logger.exception("Unexpected error during login")
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred. Please try again later.",
        )

@router.post("/logout")
async def logout_user(response: Response):
    response.delete_cookie("token", path="/", httponly=True, samesite="strict")
    return {"message": "Logged out successfully"}

@router.get("/me", summary="Get Current User Profile")
async def get_me(current_user: dict = Depends(get_current_user)):
    """
    Returns the parsed payload from the HttpOnly JWT Cookie.
    Used by the frontend SPA to rehydrate User State on hard browser refreshes.
    """
    return {"user": current_user}
