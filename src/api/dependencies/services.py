"""Service registry and dependency providers for FastAPI routes."""
from __future__ import annotations
from typing import Any, Dict, Optional
from fastapi import HTTPException

class ServiceRegistry:
    def __init__(self) -> None:
        self._services: Dict[str, Any] = {}

    def register(self, name: str, service: Any) -> None:
        self._services[name] = service

    def get(self, name: str) -> Any:
        if name not in self._services or self._services[name] is None:
            raise HTTPException(status_code=400, detail=f"Service '{name}' not available")
        return self._services[name]

    def all_status(self) -> Dict[str, Dict[str, Any]]:
        status: Dict[str, Dict[str, Any]] = {}
        for name, svc in self._services.items():
            if svc is None:
                status[name] = {"error": f"{name} service not initialized"}
            else:
                try:
                    status[name] = svc.status() if hasattr(svc, "status") else {"state": "unknown"}
                except Exception as e:  # pragma: no cover - defensive
                    status[name] = {"error": str(e)}
        return status

service_registry = ServiceRegistry()

# FastAPI dependency providers

def get_service_registry() -> ServiceRegistry:
    return service_registry

__all__ = ["ServiceRegistry", "service_registry", "get_service_registry"]
