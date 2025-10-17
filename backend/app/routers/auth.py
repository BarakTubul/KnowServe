import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from app.core.database import get_db
from app.models.user import User
from app.utils.hashing import hash_password, verify_password
from app.utils.jwt import create_access_token
from app.schemas import auth_schema

router = APIRouter(prefix="/auth", tags=["Auth"])
logger = logging.getLogger(__name__)


# ----------------------------
# Register Endpoint
# ----------------------------
@router.post("/register")
def register_user(request: auth_schema.RegisterRequest, db: Session = Depends(get_db)):
    try:
        # Check if user already exists
        existing_user = db.query(User).filter(User.email == request.email).first()
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="An account with this email already exists."
            )

        # Hash password (safe truncate)
        try:
            hashed_pw = hash_password(request.password)
        except Exception as e:
            logger.exception("Password hashing failed for email %s", request.email)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An unexpected error occurred. Please try again later."
            )

        new_user = User(
            name=request.name.strip(),
            email=request.email.lower(),
            password_hash=hashed_pw,
            role=request.role,
            department_id=request.department_id
        )

        db.add(new_user)
        db.commit()
        db.refresh(new_user)

        return {
            "message": "✅ User registered successfully",
            "user_id": new_user.id
        }

    except HTTPException:
        raise
    except SQLAlchemyError as e:
        db.rollback()
        logger.exception("Database error during registration for %s", request.email)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred. Please try again later."
        )
    except Exception as e:
        logger.exception("Unhandled error in register_user()")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred. Please try again later."
        )


# ----------------------------
# Login Endpoint
# ----------------------------
@router.post("/login")
def login_user(request: auth_schema.LoginRequest, db: Session = Depends(get_db)):
    try:
        user = db.query(User).filter(User.email == request.email.lower()).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password."
            )

        try:
            if not verify_password(request.password, user.password_hash):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid email or password."
                )
        except Exception as e:
            logger.exception("Password verification failed for %s", request.email)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An unexpected error occurred. Please try again later."
            )

        try:
            access_token = create_access_token(
                data={"sub": user.email, "role": user.role.value, "user_id": user.id}
            )
        except Exception as e:
            logger.exception("Token generation failed for %s", request.email)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An unexpected error occurred. Please try again later."
            )

        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user": {
                "id": user.id,
                "name": user.name,
                "email": user.email,
                "role": user.role.value
            }
        }

    except HTTPException:
        raise
    except SQLAlchemyError:
        logger.exception("Database error during login for %s", request.email)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred. Please try again later."
        )
    except Exception:
        logger.exception("Unhandled error in login_user()")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred. Please try again later."
        )
