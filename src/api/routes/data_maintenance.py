"""
Data Maintenance API routes (refactored into routes package).
"""
import logging
from typing import Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel

from src.services.maintenance.data_maintenance_service import DataMaintenanceService, MaintenanceStats  # noqa: F401

logger = logging.getLogger("data_maintenance_api")

router = APIRouter(prefix="/maintenance", tags=["data-maintenance"])

# Global service instance (set via init function to decouple creation)
data_maintenance_service: Optional[DataMaintenanceService] = None

def init_data_maintenance_service(service: DataMaintenanceService):
    """Attach a running DataMaintenanceService instance for endpoint handlers."""
    global data_maintenance_service
    data_maintenance_service = service

# Request/Response models
class MaintenanceRequest(BaseModel):
    symbols: Optional[List[str]] = None

class HealthReportResponse(BaseModel):  # noqa: D401
    total_symbols: int
    symbols_with_gaps: int
    total_gaps: int
    oldest_data_date: Optional[str]
    newest_data_date: Optional[str]
    data_coverage_days: int
    symbol_details: List[Dict]

class MaintenanceStatsResponse(BaseModel):  # noqa: D401
    gaps_filled: int
    candles_added: int
    candles_removed: int
    symbols_processed: int
    errors: List[str]

@router.get("/health")
async def maintenance_health():
    if not data_maintenance_service:
        raise HTTPException(status_code=503, detail="Data maintenance service not initialized")
    return {"status": "healthy", "service": "data_maintenance", "features": ["data_cleanup", "gap_filling", "health_reporting"]}

@router.post("/run", response_model=Dict[str, str])
async def run_maintenance(request: MaintenanceRequest, background_tasks: BackgroundTasks):
    if not data_maintenance_service:
        raise HTTPException(status_code=503, detail="Data maintenance service not initialized")
    try:
        background_tasks.add_task(data_maintenance_service.run_maintenance, request.symbols)
        return {"message": "Data maintenance started in background", "symbols": request.symbols or "all", "status": "running"}
    except Exception as e:  # pragma: no cover - defensive
        logger.error(f"Error starting maintenance: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start maintenance: {str(e)}")

@router.get("/health-report")
async def get_health_report(symbols: Optional[List[str]] = Query(None)):
    if not data_maintenance_service:
        raise HTTPException(status_code=503, detail="Data maintenance service not initialized")
    try:
        report = await data_maintenance_service.get_data_health_report(symbols)
        if report["oldest_data_date"]:
            report["oldest_data_date"] = report["oldest_data_date"].isoformat()
        if report["newest_data_date"]:
            report["newest_data_date"] = report["newest_data_date"].isoformat()
        return report
    except Exception as e:  # pragma: no cover - defensive
        logger.error(f"Error getting health report: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get health report: {str(e)}")

@router.post("/cleanup")
async def cleanup_old_data(symbols: Optional[List[str]] = None, retention_days: Optional[int] = None):
    if not data_maintenance_service:
        raise HTTPException(status_code=503, detail="Data maintenance service not initialized")
    try:
        if retention_days is not None:
            original_retention = data_maintenance_service.data_retention_days
            data_maintenance_service.data_retention_days = retention_days
        total_removed = 0
        processed_symbols = symbols or await data_maintenance_service._get_all_symbols()
        for symbol in processed_symbols:
            instrument_keys = await data_maintenance_service._get_instrument_keys_for_symbol(symbol)
            for instrument_key in instrument_keys:
                removed = await data_maintenance_service._cleanup_old_data(symbol, instrument_key)
                total_removed += removed
        if retention_days is not None:
            data_maintenance_service.data_retention_days = original_retention
        return {"message": f"Cleaned up {total_removed} old candles", "symbols_processed": len(processed_symbols), "retention_days": retention_days or data_maintenance_service.data_retention_days}
    except Exception as e:  # pragma: no cover - defensive
        logger.error(f"Error during cleanup: {e}")
        raise HTTPException(status_code=500, detail=f"Cleanup failed: {str(e)}")

@router.post("/fill-gaps")
async def fill_data_gaps(symbols: Optional[List[str]] = None):
    if not data_maintenance_service:
        raise HTTPException(status_code=503, detail="Data maintenance service not initialized")
    try:
        processed_symbols = symbols or await data_maintenance_service._get_all_symbols()
        total_gaps_filled = 0
        total_candles_added = 0
        for symbol in processed_symbols:
            instrument_keys = await data_maintenance_service._get_instrument_keys_for_symbol(symbol)
            for instrument_key in instrument_keys:
                gaps_filled, candles_added = await data_maintenance_service._fill_data_gaps(symbol, instrument_key)
                total_gaps_filled += gaps_filled
                total_candles_added += candles_added
        return {"message": f"Filled {total_gaps_filled} gaps, added {total_candles_added} candles", "symbols_processed": len(processed_symbols), "gaps_filled": total_gaps_filled, "candles_added": total_candles_added}
    except Exception as e:  # pragma: no cover - defensive
        logger.error(f"Error filling gaps: {e}")
        raise HTTPException(status_code=500, detail=f"Gap filling failed: {str(e)}")

@router.get("/config")
async def get_maintenance_config():
    if not data_maintenance_service:
        raise HTTPException(status_code=503, detail="Data maintenance service not initialized")
    return {"data_retention_days": data_maintenance_service.data_retention_days, "gap_fill_enabled": data_maintenance_service.gap_fill_enabled, "cleanup_enabled": data_maintenance_service.cleanup_enabled, "maintenance_interval_hours": data_maintenance_service.maintenance_interval_hours, "service_running": data_maintenance_service._running}

@router.post("/config")
async def update_maintenance_config(data_retention_days: Optional[int] = None, gap_fill_enabled: Optional[bool] = None, cleanup_enabled: Optional[bool] = None, maintenance_interval_hours: Optional[int] = None):
    if not data_maintenance_service:
        raise HTTPException(status_code=503, detail="Data maintenance service not initialized")
    try:
        updates = {}
        if data_retention_days is not None:
            data_maintenance_service.data_retention_days = data_retention_days
            updates["data_retention_days"] = data_retention_days
        if gap_fill_enabled is not None:
            data_maintenance_service.gap_fill_enabled = gap_fill_enabled
            updates["gap_fill_enabled"] = gap_fill_enabled
        if cleanup_enabled is not None:
            data_maintenance_service.cleanup_enabled = cleanup_enabled
            updates["cleanup_enabled"] = cleanup_enabled
        if maintenance_interval_hours is not None:
            data_maintenance_service.maintenance_interval_hours = maintenance_interval_hours
            updates["maintenance_interval_hours"] = maintenance_interval_hours
        logger.info(f"Updated maintenance config: {updates}")
        return {"message": "Configuration updated", "updates": updates}
    except Exception as e:  # pragma: no cover - defensive
        logger.error(f"Error updating config: {e}")
        raise HTTPException(status_code=500, detail=f"Config update failed: {str(e)}")

__all__ = ["router", "init_data_maintenance_service"]
