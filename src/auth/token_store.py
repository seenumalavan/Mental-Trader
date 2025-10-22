import json
import logging
import os
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
        obj = {
            "access_token": token_data.get("access_token"),
            "refresh_token": token_data.get("refresh_token"),
            "expiry": None
        }
        expires_in = token_data.get("expires_in")
        if expires_in:
            expiry = datetime.utcnow() + timedelta(seconds=int(expires_in))
            obj["expiry"] = expiry.isoformat()
        elif token_data.get("expiry_iso"):
            obj["expiry"] = token_data.get("expiry_iso")
        with open(_store_file, "w") as f:
            json.dump(obj, f)
        logger.info("Token saved to %s", _store_file)

def get_token() -> str:
    with _lock:
        _ensure_file()
        with open(_store_file, "r") as f:
            data = json.load(f)
    return data.get("access_token", "")

def is_token_expired() -> bool:
    with _lock:
        _ensure_file()
        with open(_store_file, "r") as f:
            data = json.load(f)
    expiry = data.get("expiry")
    if not expiry:
        return True
    try:
        exp_dt = datetime.fromisoformat(expiry)
        return datetime.utcnow() >= exp_dt
    except Exception:
        return True