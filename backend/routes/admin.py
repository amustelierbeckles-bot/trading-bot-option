"""
Routes de administración, salud y notificaciones.

  GET  /
  GET  /api/health
  POST /api/admin/test-email
  GET  /api/data-provider/status
  GET  /api/notifications/config
  POST /api/notifications/test
  POST /api/whatsapp/test
"""
import asyncio
import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header, Request

from circuit_breaker import cb_get_state
from market_session import get_market_session

router = APIRouter()


# ── Auth helpers (duplicados aquí para que las rutas sean autónomas) ──────────
async def _verify_api_key(x_api_key: Optional[str] = Header(None, alias="X-API-Key")):
    current_key = os.getenv("API_SECRET_KEY", None)
    if not current_key:
        return True
    if not x_api_key:
        raise HTTPException(status_code=401, detail="X-API-Key header required",
                            headers={"WWW-Authenticate": "ApiKey"})
    import hmac
    if not hmac.compare_digest(x_api_key, current_key):
        raise HTTPException(status_code=403, detail="Invalid API key")
    return True


@router.get("/")
async def root(request: Request):
    return {
        "name":       "Trading Bot API",
        "version":    "3.0.0",
        "status":     "online",
        "strategies": len(request.app.state.strategies),
    }


@router.get("/api/health")
async def health_check(request: Request):
    now     = datetime.utcnow()
    session = get_market_session(now.hour, now.minute)
    cb      = cb_get_state()
    return {
        "status":              "healthy",
        "timestamp":           now.isoformat(),
        "strategies_loaded":   len(request.app.state.strategies),
        "market_session":      session["display"],
        "session_active":      session["active"],
        "session_description": session["description"],
        "circuit_breaker":     cb,
        "session_pairs":       len(session["pairs"]),
    }


@router.post("/api/admin/test-email")
async def test_email(request: Request, _: bool = Depends(_verify_api_key)):
    """Envía un email de prueba con los datos reales de las últimas 24h."""
    email_svc = getattr(request.app.state, "email_service", None)
    if not email_svc:
        raise HTTPException(
            status_code=503,
            detail="Email service no disponible (MongoDB desconectado o RESEND_API_KEY no configurada)",
        )
    result = await email_svc.send_test_email()
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Error desconocido"))
    return result


@router.get("/api/data-provider/status")
async def data_provider_status(request: Request):
    """Estado del proveedor de datos y uso de la API."""
    provider = request.app.state.data_provider
    return {
        "status": "real" if provider.is_configured else "simulated",
        **provider.stats(),
        "message": (
            "Datos de mercado REALES activos (Twelve Data)"
            if provider.is_configured
            else "Modo simulado activo. Configura TWELVE_DATA_API_KEY para datos reales."
        ),
    }


@router.get("/api/notifications/config")
async def get_notifications_config():
    tg_token  = os.getenv("TELEGRAM_BOT_TOKEN", "")
    tg_chatid = os.getenv("TELEGRAM_CHAT_ID", "")
    return {
        "telegram": {
            "enabled":     os.getenv("TELEGRAM_ENABLED", "false").lower() == "true",
            "token_set":   bool(tg_token and len(tg_token) > 10),
            "chat_id_set": bool(tg_chatid and tg_chatid != "your_chat_id_here"),
            "only_fire":   os.getenv("TELEGRAM_ONLY_FIRE", "false").lower() == "true",
        },
        "whatsapp": {
            "enabled":    os.getenv("WHATSAPP_ENABLED", "false").lower() == "true",
            "phone":      os.getenv("WHATSAPP_PHONE", ""),
            "apikey_set": bool(os.getenv("WHATSAPP_APIKEY", "") not in ("", "your_callmebot_apikey_here")),
        },
        "frontend_url": os.getenv("FRONTEND_URL", "http://localhost:3000"),
    }


async def _run_notification_test(app=None) -> dict:
    from services.telegram_service import send_signal_telegram
    from datetime import datetime

    test_signal = {
        "id":                  "test_signal_001",
        "symbol":              "OTC_EURUSD",
        "asset_name":          "EUR/USD OTC",
        "type":                "CALL",
        "quality_score":       0.82,
        "cci":                 145.0,
        "payout":              92.0,
        "session":             "TEST",
        "entry_price":         1.0823,
        "timestamp":           datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S") + "Z",
        "strategies_agreeing": ["CCI + Alligator", "RSI + Bollinger Bands", "MACD + Stochastic"],
        "reason":              "RSI sobrevendido + CCI alcista extremo",
    }
    telegram_enabled = os.getenv("TELEGRAM_ENABLED", "false").lower() == "true"
    channel  = "Telegram" if telegram_enabled else "Ninguno configurado"
    msg_id   = await send_signal_telegram(test_signal, app=app)
    ok       = msg_id is not None
    return {
        "sent":    ok,
        "channel": channel,
        "msg_id":  msg_id,
        "message": "Señal de prueba enviada con botones interactivos" if ok else "Error — verifica config en .env",
    }


@router.post("/api/notifications/test")
async def test_notifications(request: Request):
    return await _run_notification_test(app=request.app)


@router.post("/api/whatsapp/test")
async def test_whatsapp(request: Request):
    return await _run_notification_test(app=request.app)
