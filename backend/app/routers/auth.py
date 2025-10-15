from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from app.core.database import get_db
from app.models.user import User, UserRole
from app.utils.hashing import hash_password, verify_password
from app.utils.jwt import create_access_token

router = APIRouter(prefix="/auth", tags=["Auth"])

# ----------------------------
# Pydantic Schemas
# ----------------------------
class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str
    role: UserRole = UserRole.EMPLOYEE
    department_id: int | None = None

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

# ----------------------------
# Register Endpoint
# ----------------------------
@router.post("/register")
def register_user(request: RegisterRequest, db: Session = Depends(get_db)):
    # Check if user already exists
    existing_user = db.query(User).filter(User.email == request.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this email already exists."
        )

    # Hash password
    hashed_pw = hash_password(request.password)

    # Create user
    new_user = User(
        name=request.name,
        email=request.email,
        password_hash=hashed_pw,
        role=request.role,
        department_id=request.department_id
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return {"message": "✅ User registered successfully", "user_id": new_user.id}

# ----------------------------
# Login Endpoint
# ----------------------------
@router.post("/login")
def login_user(request: LoginRequest, db: Session = Depends(get_db)):
    # Find user by email
    user = db.query(User).filter(User.email == request.email).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password."
        )

    # Verify password
    if not verify_password(request.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password."
        )

    # Create JWT token
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
            "role": user.role.value
        }
    }
