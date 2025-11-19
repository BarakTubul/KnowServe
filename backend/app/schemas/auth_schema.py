from pydantic import BaseModel, EmailStr, field_validator
from app.models.user import UserRole


# ----------------------------
# Register Request Schema
# ----------------------------
class RegisterRequest(BaseModel):
    """Schema for user registration request."""

    name: str
    email: EmailStr
    password: str
    role: UserRole = UserRole.EMPLOYEE
    department_id: int | None = None

    # ✅ Normalize role input to lowercase
    @field_validator("role", mode="before")
    @classmethod
    def normalize_role(cls, v):
        if isinstance(v, str):
            v = v.lower().strip()
            try:
                return UserRole(v)
            except ValueError:
                raise ValueError(f"Invalid role '{v}'. Must be one of {[r.value for r in UserRole]}")
        return v

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str):
        """Ensure the password meets minimum security requirements."""
        if len(v) < 8 or not any(c.isdigit() for c in v) or not any(c.isupper() for c in v):
            raise ValueError("Password does not meet security requirements.")
        return v

    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "Alice Johnson",
                "email": "alice@example.com",
                "password": "SecurePass123",
                "role": "employee",  # ✅ lowercase in example
                "department_id": 2
            }
        }
    }


# ----------------------------
# Login Request Schema
# ----------------------------
class LoginRequest(BaseModel):
    """Schema for user login request."""

    email: EmailStr
    password: str

    model_config = {
        "json_schema_extra": {
            "example": {
                "email": "alice@example.com",
                "password": "SecurePass123"
            }
        }
    }
