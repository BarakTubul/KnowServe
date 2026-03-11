# app/controllers/auth_controller.py

from app.services.auth_service import AuthService
from app.pydantic_schemas.auth_schema import RegisterRequest, LoginRequest


class AuthController:

    @staticmethod
    async def register(request: RegisterRequest):
        return AuthService.register(
            name=request.name,
            email=request.email,
            password=request.password,
            role=request.role,
            department_id=request.department_id
        )

    @staticmethod
    async def login(request: LoginRequest):
        return AuthService.login(
            email=request.email,
            password=request.password
        )
