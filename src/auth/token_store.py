import json
import logging
import os
import pandas as pd
import threading
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_store_file = os.path.join(os.path.dirname(__file__), '../data/token_store.json')

def _ensure_file():
    d = os.path.dirname(_store_file)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)
    if not os.path.exists(_store_file):
        with open(_store_file, "w") as f:
            json.dump({}, f)

def save_token(token_data: dict):
    with _lock:
        _ensure_file()
        
        # Calculate custom expiry: next day's 3:30 AM IST or day after
        token_generated_at = pd.Timestamp.now(tz='Asia/Kolkata')
        
        # Create a time object for 3:30 AM
        expiry_time = pd.Timestamp('3:30').time()
        
        if token_generated_at.time() < expiry_time:
            # Token generated before 3:30 AM, expires at 3:30 AM next day
            expiry = token_generated_at.replace(hour=3, minute=30, second=0, microsecond=0) + pd.Timedelta(days=1)
        else:
            # Token generated at or after 3:30 AM, expires at 3:30 AM day after
            expiry = token_generated_at.replace(hour=3, minute=30, second=0, microsecond=0) + pd.Timedelta(days=2)
        
        obj = {
            "access_token": token_data.get("access_token"),
            "refresh_token": token_data.get("refresh_token"),
            "expiry": expiry.isoformat(),
            "generated_at": token_generated_at.isoformat()
        }
        
        with open(_store_file, "w") as f:
            json.dump(obj, f)
        logger.info("Token saved to %s, expires at %s IST", _store_file, expiry.isoformat())

def get_token() -> str:
    with _lock:
        _ensure_file()
        with open(_store_file, "r") as f:
            data = json.load(f)
    return data.get("access_token", "")

def get_token_expiry() -> dict:
    """Get token expiry information."""
    with _lock:
        _ensure_file()
        with open(_store_file, "r") as f:
            data = json.load(f)
    
    expiry = data.get("expiry")
    generated_at = data.get("generated_at")
    
    if not expiry:
        return {"has_token": False, "is_expired": True}
    
    try:
        exp_dt = pd.Timestamp.fromisoformat(expiry)
        gen_dt = pd.Timestamp.fromisoformat(generated_at) if generated_at else None
        now = pd.Timestamp.now(tz='Asia/Kolkata')
        is_expired = now >= exp_dt
        
        return {
            "has_token": True,
            "is_expired": is_expired,
            "expires_at": expiry,
            "generated_at": generated_at,
            "time_until_expiry": str(exp_dt - now) if not is_expired else None
        }
    except Exception:
        return {"has_token": False, "is_expired": True, "error": "Invalid expiry format"}