"""ASGI entry point: uvicorn knowserve_api.main:create_app --factory --port $PORT."""

from .app import create_app

__all__ = ["create_app"]
