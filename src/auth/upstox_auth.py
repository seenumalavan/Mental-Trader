import logging
from datetime import datetime, timedelta

import upstox_client
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse
from upstox_client.rest import ApiException

from src.auth.token_store import save_token
from src.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.get("/login")
async def login():
    """Initiate OAuth redirect to Upstox authorization screen."""
    cid = getattr(settings, "UPSTOX_API_KEY", None)
    redirect_uri = getattr(settings, "UPSTOX_REDIRECT_URI", None)
    auth_url = getattr(settings, "UPSTOX_AUTH_URL", None)
    if not cid or not redirect_uri or not auth_url:
        return JSONResponse({"error": "OAuth client not configured"}, status_code=500)
    url = f"{auth_url}?client_id={cid}&redirect_uri={redirect_uri}&response_type=code"
    logger.info("Redirecting to Upstox auth dialog: %s", url)
    return RedirectResponse(url)

@router.get("/callback")
async def callback(request: Request):
    code = request.query_params.get("code")
    error = request.query_params.get("error")
    if error:
        return JSONResponse({"error": error}, status_code=400)
    if not code:
        return JSONResponse({"error": "Missing code parameter"}, status_code=400)

    try:
        # Use Upstox SDK for token exchange
        cid = getattr(settings, "UPSTOX_API_KEY", None)
        csecret = getattr(settings, "UPSTOX_API_SECRET", None)
        redirect_uri = getattr(settings, "UPSTOX_REDIRECT_URI", None)
        if not all([cid, csecret, redirect_uri]):
            return JSONResponse({"error": "OAuth secrets not configured"}, status_code=500)
        api_instance = upstox_client.LoginApi()
        api_version = '2.0'
        grant_type = 'authorization_code'
        api_response = api_instance.token(
            api_version=api_version,
            code=code,
            client_id=cid,
            client_secret=csecret,
            redirect_uri=redirect_uri,
            grant_type=grant_type
        )
        # Convert SDK response to dict format expected by save_token
        data = {
            'access_token': api_response.access_token
        }
        save_token(data)
        
        # Get expiry information from token store
        from src.auth.token_store import get_token_expiry
        token_info = get_token_expiry()
        
        logger.info("Access token saved; expires at %s IST", token_info.get("expires_at"))
        return JSONResponse({
            "status": "success", 
            "expires": token_info.get("expires_at"),
            "generated_at": token_info.get("generated_at")
        })
    except ApiException as e:
        logger.error("Token exchange failed via SDK: %s", e)
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        logger.exception("Token exchange exception: %s", e)
        return JSONResponse({"error": str(e)}, status_code=500)

@router.get("/token/status")
async def token_status():
    """Check current token status and expiry."""
    try:
        from src.auth.token_store import get_token_expiry
        token_info = get_token_expiry()
        return JSONResponse(token_info)
    except Exception as e:
        logger.exception("Token status check failed: %s", e)
        return JSONResponse({"error": str(e)}, status_code=500)