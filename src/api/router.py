"""Unified API router aggregator.

Adds all individual feature routers here to keep `app.py` clean.
"""
from fastapi import APIRouter

# External route modules (cannot move them per constraints)
from src.auth import upstox_auth  # noqa: F401

# Internal (refactored) route modules
from src.api.routes.data_maintenance import router as maintenance_router
from src.api.routes.system import router as system_router
from src.api.routes.trading_control import router as trading_control_router

api_router = APIRouter()
api_router.include_router(upstox_auth.router)
api_router.include_router(system_router)
api_router.include_router(trading_control_router)
api_router.include_router(maintenance_router)

__all__ = ["api_router"]
