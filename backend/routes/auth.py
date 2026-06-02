"""
Routes de autenticación de sesión (frontend).

  POST /api/auth/login   — valida contraseña, emite cookie de sesión HttpOnly
  POST /api/auth/logout  — borra la cookie de sesión
  GET  /api/auth/me      — devuelve si la sesión actual es válida

El frontend ya no embebe ninguna API key: autentica con esta cookie firmada.
"""
import hmac
import os

from fastapi import APIRouter, HTTPException, Request, Response

from auth_deps import _COOKIE_NAME, _valid_session, make_session_token
from schemas import LoginRequest

router = APIRouter()

_SESSION_TTL = 7 * 24 * 3600


@router.post("/api/auth/login")
async def login(body: LoginRequest, response: Response):
    """Valida la contraseña de acceso y emite la cookie de sesión."""
    expected = os.getenv("APP_PASSWORD")
    if not expected:
        raise HTTPException(status_code=503, detail="App password not configured")
    if not body.password or not hmac.compare_digest(body.password, expected):
        raise HTTPException(status_code=401, detail="Contraseña incorrecta")

    token = make_session_token(_SESSION_TTL)
    response.set_cookie(
        key=_COOKIE_NAME,
        value=token,
        max_age=_SESSION_TTL,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )
    return {"success": True}


@router.post("/api/auth/logout")
async def logout(response: Response):
    """Borra la cookie de sesión."""
    response.delete_cookie(key=_COOKIE_NAME, path="/")
    return {"success": True}


@router.get("/api/auth/me")
async def me(request: Request):
    """Indica si la cookie de sesión actual es válida."""
    return {"authenticated": _valid_session(request.cookies.get(_COOKIE_NAME))}
