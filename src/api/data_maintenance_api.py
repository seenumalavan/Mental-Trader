"""Backward compatibility shim.

This module now re-exports the router and init function from the refactored
`api.routes.data_maintenance` module so existing imports continue to work.
"""

from src.api.routes.data_maintenance import (  # noqa: F401
    router,
    init_data_maintenance_service,
)

__all__ = ["router", "init_data_maintenance_service"]