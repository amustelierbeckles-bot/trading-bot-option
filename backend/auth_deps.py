"""Autenticación compartida: sesión httpOnly (frontend) o X-API-Key (server-side).

El frontend autentica con una cookie de sesión firmada (HttpOnly, no visible al JS).
Los llamadores server-side (scripts, automatización) siguen usando X-API-Key.
"""
import base64
import hashlib
import hmac
import os
import time
from typing import Optional

from fastapi import Header, HTTPException, Request

_COOKIE_NAME = "session"


def _signing_key() -> bytes:
    key = os.getenv("API_SECRET_KEY")
    if not key:
        raise HTTPException(status_code=503, detail="API key not configured")
    return key.encode()


def make_session_token(ttl_seconds: int = 7 * 24 * 3600) -> str:
    """Token firmado con expiración. Formato: base64(exp).hmac_sha256(exp)."""
    exp_b64 = base64.urlsafe_b64encode(str(int(time.time()) + ttl_seconds).encode())
    sig = hmac.new(_signing_key(), exp_b64, hashlib.sha256).hexdigest()
    return f"{exp_b64.decode()}.{sig}"


def _valid_session(token: Optional[str]) -> bool:
    if not token or "." not in token:
        return False
    exp_b64, sig = token.rsplit(".", 1)
    expected = hmac.new(_signing_key(), exp_b64.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return False
    try:
        exp = int(base64.urlsafe_b64decode(exp_b64.encode()))
    except (ValueError, TypeError):
        return False
    return time.time() < exp


def _valid_api_key(x_api_key: Optional[str]) -> bool:
    current = os.getenv("API_SECRET_KEY")
    if not current or not x_api_key:
        return False
    return hmac.compare_digest(x_api_key, current)


async def verify_session_or_key(
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> bool:
    """OK si la cookie de sesión es válida (frontend) o la X-API-Key es correcta."""
    if _valid_session(request.cookies.get(_COOKIE_NAME)):
        return True
    if _valid_api_key(x_api_key):
        return True
    raise HTTPException(status_code=401, detail="No autenticado")
