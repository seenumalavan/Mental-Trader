import logging
from contextlib import asynccontextmanager
from typing import List, Optional, Union

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from auth import upstox_auth
from src.config import settings
from src.persistence.db import Database
from src.services.scalping_service import ScalperService
from src.utils.instruments import resolve_instruments
from src.utils.logging_config import configure_logging

logger = logging.getLogger("app")

# Request models
class StartTradingRequest(BaseModel):
    instruments: Optional[Union[str, List[str]]] = "nifty"
    
class InstrumentsRequest(BaseModel):
    instruments: Union[str, List[str]]

# Global service instance
print("DEBUG: Creating ScalperService instance...")
try:
    service = ScalperService()
    print("DEBUG: ScalperService created successfully")
except Exception as e:
    print(f"DEBUG: Failed to create ScalperService: {e}")
    service = None


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
    
    if service is None:
        logger.error("Service is None, cannot start trading system")
    else:
        # Initialize database
        try:
            db_ok = await initialize_database()
            if not db_ok:
                logger.warning("Database initialization failed, but continuing...")
        except Exception as e:
            logger.error(f"Database initialization error: {e}")
        
        # Initialize service on startup
        try:
            await service.start(["indices"])
            logger.info("Trading service started successfully")
        except Exception as e:
            logger.error(f"Failed to start trading service: {e}")
            # Don't raise - let the web interface start anyway for monitoring

    print("LIFESPAN: Startup complete, yielding...")
    yield
    
    # Shutdown
    print("LIFESPAN: Shutting down...")
    logger.info("Shutting down trading service...")
    
    if service is not None:
        try:
            await service.stop()
            logger.info("Trading service stopped successfully")
        except Exception as e:
            logger.error(f"Failed to stop trading service: {e}")
    
    print("LIFESPAN: Shutdown complete")


print("DEBUG: About to create FastAPI app...")

app = FastAPI(
    title="Mental Trader", 
    description="Algorithmic Trading System",
    version="1.0.0",
    lifespan=lifespan
)

app.include_router(upstox_auth.router)

print("DEBUG: FastAPI app created successfully")

@app.get("/")
async def root():
    """Root endpoint with system info."""
    return {
        "name": "Mental Trader",
        "version": "1.0.0",
        "description": "Algorithmic Trading System",
        "endpoints": {
            "health": "/health",
            "status": "/status", 
            "docs": "/docs",
            "control": "/control/"
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
        if service is None:
            return {"error": "Service not initialized"}
        return service.status()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting status: {e}")


@app.post("/control/start")
async def start_trading(request: StartTradingRequest = None):
    """
    Start the trading system with specified instruments.
    
    Examples:
    - {"instruments": "nifty"} - Trade all Nifty stocks
    - {"instruments": "indices"} - Trade all indices
    - {"instruments": ["nifty", "indices"]} - Trade both Nifty stocks and indices
    - {"instruments": "RELIANCE,TCS"} - Trade specific stocks
    - {"instruments": ["RELIANCE", "TCS"]} - Trade specific stocks (array format)
    """
    try:
        if service is None:
            raise HTTPException(status_code=500, detail="Service not initialized")
        
        instruments_input = "nifty"  # Default
        if request and request.instruments:
            instruments_input = request.instruments
            
        await service.start(instruments_input)
        
        # Show what instruments were resolved
        resolved = resolve_instruments(instruments_input)
        symbols = [item['symbol'] for item in resolved]
        
        return {
            "status": "started", 
            "message": "Trading system started successfully",
            "instruments_input": instruments_input,
            "resolved_symbols": symbols,
            "total_instruments": len(resolved)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start: {e}")

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
async def stop_trading():
    """Stop the trading system."""
    try:
        if service is None:
            raise HTTPException(status_code=500, detail="Service not initialized")
        await service.stop()
        return {"status": "stopped", "message": "Trading system stopped successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to stop: {e}")


@app.get("/config")
async def get_config():
    """Get current configuration (safe values only)."""
    from src.config import watchlist_symbols
    return {
        "watchlist": watchlist_symbols(),
        "ema_short": settings.EMA_SHORT,
        "ema_long": settings.EMA_LONG,
        "warmup_bars": settings.WARMUP_BARS,
        "app_port": settings.APP_PORT
    }
