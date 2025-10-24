import logging
from contextlib import asynccontextmanager
from typing import List, Optional, Union

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from auth import upstox_auth
from src.auth.token_store import get_token_expiry
from src.config import settings
from src.persistence.db import Database
from src.services.scalping_service import ScalperService
from src.services.intraday_service import IntradayService
from src.services.sentiment_service import SentimentService
from src.engine.sentiment_filter import SentimentFilter
from src.api.sentiment_api import router as sentiment_router, init_sentiment_services
from src.utils.instruments import resolve_instruments
from src.utils.logging_config import configure_logging

logger = logging.getLogger("app")

# Request models
class StartTradingRequest(BaseModel):
    service: str = "scalper"  # Default to scalper
    instruments: Optional[Union[str, List[str]]] = "nifty"
    
class StopTradingRequest(BaseModel):
    service: str = "scalper"  # Default to scalper
    
class InstrumentsRequest(BaseModel):
    instruments: Union[str, List[str]]

# Global service instances
print("DEBUG: Creating service instances...")
services = {}
try:
    services['scalper'] = ScalperService()
    print("DEBUG: ScalperService created successfully")
except Exception as e:
    print(f"DEBUG: Failed to create ScalperService: {e}")
    services['scalper'] = None

try:
    services['intraday'] = IntradayService()
    print("DEBUG: IntradayService created successfully")
except Exception as e:
    print(f"DEBUG: Failed to create IntradayService: {e}")
    services['intraday'] = None

# Sentiment services
try:
    sentiment_svc = SentimentService()
    sentiment_filt = SentimentFilter(sentiment_svc)
    services['sentiment'] = sentiment_svc
    services['sentiment_filter'] = sentiment_filt
    print("DEBUG: Sentiment services created successfully")
except Exception as e:
    print(f"DEBUG: Failed to create sentiment services: {e}")
    services['sentiment'] = None
    services['sentiment_filter'] = None


async def initialize_database():
    """Initialize database tables if needed."""
    try:
        db = Database(settings.DATABASE_URL)
        await db.connect()
        logger.info("Database initialized successfully")
        await db.disconnect()
        return True
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context manager."""
    # Startup
    print("LIFESPAN: Starting up...")
    configure_logging()
    logger.info("Starting Mental Trader Web Interface...")
    
    # Check if any services are available
    if not any(svc for svc in services.values() if svc is not None):
        logger.error("No services available, cannot start trading system")
    else:
        # Initialize database
        try:
            db_ok = await initialize_database()
            if not db_ok:
                logger.warning("Database initialization failed, but continuing...")
        except Exception as e:
            logger.error(f"Database initialization error: {e}")
        
        # Initialize services on startup (only scalper for now, intraday can be started manually)
        # if services.get('scalper'):
        #     try:
        #         await services['scalper'].start(["indices"])
        #         logger.info("Scalper service started successfully")
        #     except Exception as e:
        #         logger.error(f"Failed to start scalper service: {e}")

        # Initialize sentiment services
        if services.get('sentiment') and settings.SENTIMENT_ENABLE:
            try:
                await services['sentiment'].start()
                init_sentiment_services(services['sentiment'], services['sentiment_filter'])
                logger.info("Sentiment services started successfully")
            except Exception as e:
                logger.error(f"Failed to start sentiment services: {e}")

    print("LIFESPAN: Startup complete, yielding...")
    yield
    
    # Shutdown
    print("LIFESPAN: Shutting down...")
    logger.info("Shutting down trading services...")
    
    for service_name, service_instance in services.items():
        if service_instance is not None:
            try:
                if service_name == 'sentiment':
                    await service_instance.stop()
                elif hasattr(service_instance, 'stop'):
                    await service_instance.stop()
                logger.info(f"{service_name.capitalize()} service stopped successfully")
            except Exception as e:
                logger.error(f"Failed to stop {service_name} service: {e}")
    
    print("LIFESPAN: Shutdown complete")


print("DEBUG: About to create FastAPI app...")

app = FastAPI(
    title="Mental Trader", 
    description="Algorithmic Trading System",
    version="1.0.0",
    lifespan=lifespan
)

app.include_router(upstox_auth.router)
app.include_router(sentiment_router)

print("DEBUG: FastAPI app created successfully")

@app.get("/")
async def root():
    """Root endpoint with system info."""
    token_info = get_token_expiry()
    
    return {
        "name": "Mental Trader",
        "version": "1.0.0",
        "description": "Multi-Service Algorithmic Trading System",
        "services": ["scalper", "intraday"],
        "auth": {
            "has_token": token_info.get("has_token", False),
            "token_expired": token_info.get("is_expired", True),
            "login_url": "/auth/login" if token_info.get("is_expired", True) else None
        },
        "endpoints": {
            "health": "/health",
            "status": "/status", 
            "docs": "/docs",
            "auth": "/auth/",
            "control": "/control/",
            "sentiment": "/sentiment/"
        }
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "timestamp": "2025-10-15"}


@app.get("/status")
async def get_status():
    """Get trading system status."""
    try:
        status_data = {}
        for service_name, service_instance in services.items():
            if service_instance is not None:
                status_data[service_name] = service_instance.status()
            else:
                status_data[service_name] = {"error": f"{service_name} service not initialized"}
        return status_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting status: {e}")


@app.post("/control/start")
async def start_trading(request: StartTradingRequest = None):
    """
    Start a trading service with specified instruments.
    
    Examples:
    - {"service": "scalper", "instruments": "nifty"} - Start scalper with Nifty stocks
    - {"service": "intraday", "instruments": "indices"} - Start intraday with indices
    - {"service": "scalper", "instruments": ["nifty", "indices"]} - Start scalper with both
    - {"service": "intraday", "instruments": "RELIANCE,TCS"} - Start intraday with specific stocks
    """
    try:
        # Check token status first
        token_info = get_token_expiry()
        
        if not token_info.get("has_token", False):
            raise HTTPException(
                status_code=401, 
                detail="No access token found. Please authenticate first by visiting /auth/login"
            )
        
        if token_info.get("is_expired", True):
            raise HTTPException(
                status_code=401, 
                detail="Access token has expired. Please re-authenticate by visiting /auth/login"
            )
        
        service_name = "scalper"  # Default
        if request and request.service:
            service_name = request.service
            
        if service_name not in services or services[service_name] is None:
            raise HTTPException(status_code=400, detail=f"Service '{service_name}' not available")
        
        service_instance = services[service_name]
        
        # Stop any other running services to prevent WebSocket conflicts
        for name, svc in services.items():
            if name != service_name and svc and svc._running:
                logger.info(f"Stopping {name} service to prevent WebSocket conflicts")
                try:
                    await svc.stop()
                except Exception as e:
                    logger.warning(f"Error stopping {name} service: {e}")
        
        instruments_input = "nifty"  # Default
        if request and request.instruments:
            instruments_input = request.instruments
            
        await service_instance.start(instruments_input)
        
        # Show what instruments were resolved
        resolved = resolve_instruments(instruments_input)
        symbols = [item['symbol'] for item in resolved]
        
        return {
            "status": "started", 
            "service": service_name,
            "message": f"{service_name.capitalize()} service started successfully",
            "instruments_input": instruments_input,
            "resolved_symbols": symbols,
            "total_instruments": len(resolved)
        }
    except HTTPException:
        raise
    except Exception as e:
        service_name = service_name if 'service_name' in locals() else "unknown"
        raise HTTPException(status_code=500, detail=f"Failed to start {service_name}: {e}")

@app.post("/instruments/resolve")
async def resolve_instruments_endpoint(request: InstrumentsRequest):
    """
    Resolve instruments to see what symbols and keys will be used.
    
    Examples:
    - {"instruments": "nifty"} - Shows all Nifty stocks
    - {"instruments": "indices"} - Shows all indices  
    - {"instruments": ["nifty", "indices"]} - Shows both categories
    - {"instruments": "RELIANCE,TCS"} - Shows specific stocks
    """
    try:
        resolved = resolve_instruments(request.instruments)
        return {
            "input": request.instruments,
            "resolved_count": len(resolved),
            "instruments": resolved
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to resolve instruments: {e}")


@app.post("/control/stop")
async def stop_trading(request: StopTradingRequest = None):
    """Stop a trading service."""
    try:
        service_name = "scalper"  # Default
        if request and request.service:
            service_name = request.service
            
        if service_name not in services or services[service_name] is None:
            raise HTTPException(status_code=400, detail=f"Service '{service_name}' not available")
        
        service_instance = services[service_name]
        await service_instance.stop()
        return {"status": "stopped", "service": service_name, "message": f"{service_name.capitalize()} service stopped successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to stop {service_name}: {e}")


@app.get("/config")
async def get_config():
    """Get current configuration (safe values only)."""
    return {
        "ema_short": settings.EMA_SHORT,
        "ema_long": settings.EMA_LONG,
        "warmup_bars": settings.WARMUP_BARS,
        "app_port": settings.APP_PORT
    }
