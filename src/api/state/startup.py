"""Capture and expose startup diagnostic events."""
from typing import List, Dict
from datetime import datetime

_startup_events: List[Dict] = []


def record_startup_event(kind: str, message: str, **extra):
    _startup_events.append({
        "ts": datetime.utcnow().isoformat(),
        "kind": kind,
        "message": message,
        **extra,
    })


def get_startup_events(limit: int = 100):
    return _startup_events[-limit:]

__all__ = ["record_startup_event", "get_startup_events"]
