import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from app.core.database import get_db
from app.models.user import User,UserRole
from app.utils.hashing import hash_password, verify_password
from app.utils.jwt import create_access_token
from app.schemas import auth_schema

router = APIRouter( tags=["Auth"])
logger = logging.getLogger(__name__)


# ----------------------------
# Register Endpoint
# ----------------------------
@router.post("/register")
def register_user(request: auth_schema.RegisterRequest, db: Session = Depends(get_db)):
    try:
        # Normalize role to lowercase (important!)
        role_value = request.role.lower() if isinstance(request.role, str) else request.role.value
        role_enum = UserRole(role_value)

        # -------------------------------
        # 1️⃣ Check if user already exists
        # -------------------------------
        existing_user = db.query(User).filter(User.email == request.email.lower()).first()
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="An account with this email already exists."
            )

        # -------------------------------
        # 2️⃣ Prevent duplicate Admin
        # -------------------------------
        if role_enum == UserRole.ADMIN:
            existing_admin = db.query(User).filter(User.role == UserRole.ADMIN).first()
            if existing_admin:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="An admin account already exists. You cannot register another admin."
                )

        # -------------------------------
        # 3️⃣ Prevent duplicate Manager per Department
        # -------------------------------
        if role_enum == UserRole.MANAGER:
            existing_manager = db.query(User).filter(
                User.role == UserRole.MANAGER,
                User.department_id == request.department_id
            ).first()
            if existing_manager:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="This department already has a manager."
                )

        # -------------------------------
        # 4️⃣ Hash password safely
        # -------------------------------
        try:
            hashed_pw = hash_password(request.password)
        except Exception:
            logger.exception("Password hashing failed for email %s", request.email)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An unexpected error occurred. Please try again later."
            )

        # -------------------------------
        # 5️⃣ Create new user
        # -------------------------------
        new_user = User(
            name=request.name.strip(),
            email=request.email.lower(),
            password_hash=hashed_pw,
            role=role_enum,
            department_id=request.department_id,
        )

        db.add(new_user)
        db.commit()
        db.refresh(new_user)

        return {
            "message": "✅ User registered successfully",
            "user_id": new_user.id,
        }

    except HTTPException:
        raise
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Database error during registration for %s", request.email)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred. Please try again later.",
        )
    except Exception:
        logger.exception("Unhandled error in register_user()")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred. Please try again later.",
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
                detail="Invalid email or password.",
            )

        if not verify_password(request.password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password.",
            )

        access_token = create_access_token(
            data={"sub": user.email, "role": user.role.value, "user_id": user.id}
        )

        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user": {
                "id": user.id,
                "name": user.name,
                "email": user.email,
                "role": user.role.value,
            },
        }

    except HTTPException:
        raise
    except SQLAlchemyError:
        logger.exception("Database error during login for %s", request.email)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred. Please try again later.",
        )
    except Exception:
        logger.exception("Unhandled error in login_user()")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred. Please try again later.",
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
