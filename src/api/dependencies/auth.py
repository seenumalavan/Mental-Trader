"""Authentication related dependency helpers."""
from fastapi import HTTPException
from src.auth.token_store import get_token_expiry


def get_token_info():
    token_info = get_token_expiry()
    if not token_info.get("has_token", False):
        raise HTTPException(status_code=401, detail="No access token found. Please authenticate at /auth/login")
    if token_info.get("is_expired", True):
        raise HTTPException(status_code=401, detail="Access token expired. Re-authenticate at /auth/login")
    return token_info

__all__ = ["get_token_info"]
