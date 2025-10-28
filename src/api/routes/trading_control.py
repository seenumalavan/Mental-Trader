"""Trading control & instrument resolution routes."""
from typing import List, Optional, Union
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from src.api.dependencies.services import ServiceRegistry, get_service_registry
from src.api.dependencies.auth import get_token_info
from src.utils.instruments import resolve_instruments

router = APIRouter(prefix="/control", tags=["trading-control"])

class StartTradingRequest(BaseModel):
    service: str = "scalper"
    instruments: Optional[Union[str, List[str]]] = "nifty"

class StopTradingRequest(BaseModel):
    service: str = "scalper"

class InstrumentsRequest(BaseModel):
    instruments: Union[str, List[str]]

@router.post("/start")
async def start_trading(request: StartTradingRequest, registry: ServiceRegistry = Depends(get_service_registry), token_info: dict = Depends(get_token_info)):

    service_name = request.service or "scalper"
    service_instance = registry.get(service_name)

    # Stop other running services (prevent WS conflicts)
    for name in list(registry._services.keys()):  # internal access
        if name != service_name:
            other = registry._services[name]
            if other and getattr(other, "_running", False):
                try:
                    await other.stop()
                except Exception:  # pragma: no cover - defensive
                    pass

    instruments_input = request.instruments or "nifty"
    await service_instance.start(instruments_input)
    resolved = resolve_instruments(instruments_input)
    symbols = [item["symbol"] for item in resolved]

    return {
        "status": "started",
        "service": service_name,
        "message": f"{service_name.capitalize()} service started successfully",
        "instruments_input": instruments_input,
        "resolved_symbols": symbols,
        "total_instruments": len(resolved),
    }

@router.post("/stop")
async def stop_trading(request: StopTradingRequest, registry: ServiceRegistry = Depends(get_service_registry), token_info: dict = Depends(get_token_info)):
    service_name = request.service or "scalper"
    service_instance = registry.get(service_name)
    await service_instance.stop()
    return {"status": "stopped", "service": service_name, "message": f"{service_name.capitalize()} service stopped successfully"}

@router.post("/instruments/resolve", tags=["instrument-utils"], include_in_schema=True)
async def resolve_instruments_endpoint(request: InstrumentsRequest):
    try:
        resolved = resolve_instruments(request.instruments)
        return {"input": request.instruments, "resolved_count": len(resolved), "instruments": resolved}
    except Exception as e:  # pragma: no cover - defensive
        raise HTTPException(status_code=500, detail=f"Failed to resolve instruments: {e}")

__all__ = ["router"]
