"""System & metadata routes (root, health, status, config)."""
from datetime import datetime
from fastapi import APIRouter, Depends
from src.auth.token_store import get_token_expiry
from src.config import settings
from src.api.dependencies.services import ServiceRegistry, get_service_registry
from src.api.state.startup import get_startup_events

router = APIRouter()

@router.get("/")
async def root(registry: ServiceRegistry = Depends(get_service_registry)):
    token_info = get_token_expiry()
    return {
        "name": "Mental Trader",
        "version": "1.0.0",
        "description": "Multi-Service Algorithmic Trading System",
        "services": list(registry._services.keys()),
        "auto_start": {
            "scalper": settings.AUTO_START_SCALPER,
            "scalper_instruments": settings.AUTO_START_SCALPER_INSTRUMENTS,
            "intraday": settings.AUTO_START_INTRADAY,
            "intraday_instruments": settings.AUTO_START_INTRADAY_INSTRUMENTS,
        },
        "auth": {
            "has_token": token_info.get("has_token", False),
            "token_expired": token_info.get("is_expired", True),
            "login_url": "/auth/login" if token_info.get("is_expired", True) else None,
        },
        "endpoints": {
            "health": "/health",
            "status": "/status",
            "startup_events": "/startup/log",
            "docs": "/docs",
            "auth": "/auth/",
            "maintenance": "/maintenance/",
            "control": "/control/",
        },
    }

@router.get("/health")
async def health():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

@router.get("/status")
async def status(registry: ServiceRegistry = Depends(get_service_registry)):
    return registry.all_status()

@router.get("/startup/log")
async def startup_log(limit: int = 100):
    return {"events": get_startup_events(limit)}

@router.get("/config")
async def get_config():
    return {
        "ema_short": settings.EMA_SHORT,
        "ema_long": settings.EMA_LONG,
        "warmup_bars": settings.WARMUP_BARS,
        "app_port": settings.APP_PORT,
    }

__all__ = ["router"]
