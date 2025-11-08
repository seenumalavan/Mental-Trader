import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from src.config import settings

from src.persistence.db import Database
from src.services.strategies.scalping_service import ScalperService
from src.services.strategies.intraday_service import IntradayService
from src.services.strategies.opening_range_options_service import OpeningRangeOptionsService
from src.services.maintenance.data_maintenance_service import DataMaintenanceService
from src.api.data_maintenance_api import init_data_maintenance_service
from src.api.router import api_router
from src.api.dependencies.services import service_registry
from src.utils.logging_config import configure_logging
from src.auth.token_store import get_token_expiry
from src.api.state.startup import record_startup_event

logger = logging.getLogger("app")

print("DEBUG: Initializing service registry...")
def _bootstrap_services():
    created = {}
    try:
        created['scalper'] = ScalperService()
        print("DEBUG: ScalperService created")
    except Exception as e:  # pragma: no cover - defensive
        print(f"DEBUG: Failed to create ScalperService: {e}")
        created['scalper'] = None
    try:
        created['intraday'] = IntradayService()
        print("DEBUG: IntradayService created")
    except Exception as e:  # pragma: no cover - defensive
        print(f"DEBUG: Failed to create IntradayService: {e}")
        created['intraday'] = None
    try:
        created['data_maintenance'] = DataMaintenanceService()
        print("DEBUG: DataMaintenanceService created")
    except Exception as e:  # pragma: no cover - defensive
        print(f"DEBUG: Failed to create DataMaintenanceService: {e}")
        created['data_maintenance'] = None
    # Opening range service (optional)
    try:
        if settings.OPENING_RANGE_ENABLED:
            created['opening_range'] = OpeningRangeOptionsService()
            print("DEBUG: OpeningRangeOptionsService created")
        else:
            created['opening_range'] = None
            print("DEBUG: OpeningRangeOptionsService skipped (disabled)")
    except Exception as e:  # pragma: no cover
        print(f"DEBUG: Failed to create OpeningRangeOptionsService: {e}")
        created['opening_range'] = None
    for name, svc in created.items():
        service_registry.register(name, svc)
    return created


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
    created = _bootstrap_services()
    if not any(svc for svc in created.values() if svc is not None):
        logger.error("No services available, cannot start trading system")
    else:
        # Initialize database
        try:
            db_ok = await initialize_database()
            if not db_ok:
                logger.warning("Database initialization failed, but continuing...")
        except Exception as e:
            logger.error(f"Database initialization error: {e}")
        
        # Optional auto-start for scalper service if configured and auth token valid
        if settings.AUTO_START_SCALPER:
            token_info = get_token_expiry()
            scalper = service_registry._services.get('scalper')
            if scalper and token_info.get('has_token') and not token_info.get('is_expired', True):
                try:
                    instruments = settings.AUTO_START_SCALPER_INSTRUMENTS
                    await scalper.start(instruments)
                    logger.info("AUTO_START_SCALPER: Scalper service started (%s)", instruments)
                    record_startup_event("auto_start", "scalper_started", instruments=instruments)
                except Exception as e:  # pragma: no cover - defensive
                    logger.error(f"AUTO_START_SCALPER failed: {e}")
                    record_startup_event("auto_start_error", "scalper_failed", error=str(e))
            else:
                logger.warning("AUTO_START_SCALPER enabled but scalper unavailable or token invalid")
                record_startup_event("auto_start_skip", "scalper_not_started", reason="unavailable_or_token_invalid")

        # Optional auto-start for intraday service
        if settings.AUTO_START_INTRADAY:
            token_info = get_token_expiry()
            intraday = service_registry._services.get('intraday')
            if intraday and token_info.get('has_token') and not token_info.get('is_expired', True):
                instruments = settings.AUTO_START_INTRADAY_INSTRUMENTS
                try:
                    await intraday.start(instruments)
                    logger.info("AUTO_START_INTRADAY: Intraday service started (%s)", instruments)
                    record_startup_event("auto_start", "intraday_started", instruments=instruments)
                except Exception as e:  # pragma: no cover - defensive
                    logger.error(f"AUTO_START_INTRADAY failed: {e}")
                    record_startup_event("auto_start_error", "intraday_failed", error=str(e))
            else:
                logger.warning("AUTO_START_INTRADAY enabled but intraday unavailable or token invalid")
                record_startup_event("auto_start_skip", "intraday_not_started", reason="unavailable_or_token_invalid")

        # Initialize API services
        dm = service_registry._services.get('data_maintenance')
        if dm:
            init_data_maintenance_service(dm)
            try:
                await dm.start()
                logger.info("Data maintenance service started successfully")
            except Exception as e:  # pragma: no cover - defensive
                logger.error(f"Failed to start data maintenance service: {e}")
        # Optional auto-start opening range service
        if settings.OPENING_RANGE_ENABLED:
            token_info = get_token_expiry()
            ors = service_registry._services.get('opening_range')
            if ors and token_info.get('has_token') and not token_info.get('is_expired', True):
                try:
                    await ors.start(settings.AUTO_START_INTRADAY_INSTRUMENTS)
                    logger.info("OPENING_RANGE_ENABLED: Opening range service started")
                    record_startup_event("auto_start", "opening_range_started")
                except Exception as e:  # pragma: no cover
                    logger.error(f"Opening range auto start failed: {e}")
                    record_startup_event("auto_start_error", "opening_range_failed", error=str(e))
            else:
                logger.warning("Opening range enabled but service unavailable or token invalid")

    print("LIFESPAN: Startup complete, yielding...")
    yield
    
    # Shutdown
    print("LIFESPAN: Shutting down...")
    logger.info("Shutting down trading services...")
    
    for service_name, service_instance in service_registry._services.items():  # internal iteration
        if service_instance is not None:
            try:
                await service_instance.stop()
                logger.info(f"{service_name.capitalize()} service stopped successfully")
            except Exception as e:  # pragma: no cover - defensive
                logger.error(f"Failed to stop {service_name} service: {e}")
    
    print("LIFESPAN: Shutdown complete")


print("DEBUG: About to create FastAPI app...")

app = FastAPI(
    title="Mental Trader",
    description="Algorithmic Trading System",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(api_router)

print("DEBUG: FastAPI app created successfully (modular routes)")
