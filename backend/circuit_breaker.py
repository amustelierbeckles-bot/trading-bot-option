"""
Circuit Breaker autónomo.

Se actualiza cada vez que se verifica un resultado en audit_service,
sin requerir intervención del usuario.

Estado:
  _cb_state["blocked"]            → bool
  _cb_state["blocked_until"]      → datetime | None
  _cb_state["consecutive_losses"] → int
  _cb_state["reason"]             → str

Si Redis está enlazado (cb_bind_redis), el estado se persiste en la clave cb:state.
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_cb_state: Dict[str, object] = {
    "blocked":            False,
    "blocked_until":      None,
    "consecutive_losses": 0,
    "reason":             "",
}

# Cliente Redis async opcional (lo asigna server lifespan tras conectar).
_cb_redis: Optional[Any] = None

CB_CONSECUTIVE_LIMIT = 3
CB_COOLDOWN_MINUTES  = 60


def cb_bind_redis(redis) -> None:
    """Enlaza el cliente Redis async para persistir estado (None = solo RAM)."""
    global _cb_redis
    _cb_redis = redis


def _fire_async(factory) -> None:
    """Ejecuta factory() → corrutina y la programa si hay event loop (evita coroutines huérfanas)."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(factory())


def _schedule_cb_persist() -> None:
    if not _cb_redis:
        return
    r = _cb_redis
    _fire_async(lambda: cb_save_state(r))


async def cb_save_state(redis) -> None:
    """Persiste el estado del CB en Redis."""
    if not redis:
        return
    try:
        until = _cb_state.get("blocked_until")
        payload = {
            "blocked":            bool(_cb_state["blocked"]),
            "consecutive_losses": int(_cb_state["consecutive_losses"]),
            "blocked_until":      until.isoformat() if isinstance(until, datetime) else None,
            "reason":             str(_cb_state.get("reason") or ""),
        }
        await redis.set("cb:state", json.dumps(payload), ex=7200)
    except Exception:
        pass


async def cb_load_state(redis) -> None:
    """Restaura el estado del CB desde Redis al arrancar."""
    if not redis:
        return
    try:
        saved = await redis.get("cb:state")
        if not saved:
            return
        data = json.loads(saved)
        _cb_state["blocked"] = bool(data.get("blocked", False))
        _cb_state["consecutive_losses"] = int(data.get("consecutive_losses", 0))
        blocked_until = data.get("blocked_until")
        _cb_state["blocked_until"] = (
            datetime.fromisoformat(blocked_until) if blocked_until else None
        )
        _cb_state["reason"] = str(data.get("reason", ""))
        logger.info(
            "📥 Circuit Breaker | estado cargado desde Redis | blocked=%s",
            _cb_state["blocked"],
        )
    except Exception:
        pass


def cb_is_blocked() -> bool:
    """
    Retorna True si el Circuit Breaker está activo y el cooldown no expiró.
    Si el cooldown ya pasó, resetea el estado automáticamente.
    """
    if not _cb_state["blocked"]:
        return False
    until = _cb_state.get("blocked_until")
    if until and datetime.utcnow() >= until:
        _cb_state.update({"blocked": False, "blocked_until": None,
                           "consecutive_losses": 0, "reason": ""})
        logger.info("✅ Circuit Breaker: cooldown expirado — bot reanudado")
        _schedule_cb_persist()
        return False
    return True


def cb_record_result(outcome: str, symbol: str) -> None:
    """
    Actualiza el contador de pérdidas consecutivas del CB.

    - "win"  → resetea el contador (racha rota)
    - "loss" → incrementa; si llega a CB_CONSECUTIVE_LIMIT dispara el bloqueo
    """
    if _cb_state["blocked"]:
        return

    if outcome == "win":
        _cb_state["consecutive_losses"] = 0
        _schedule_cb_persist()
    elif outcome == "loss":
        _cb_state["consecutive_losses"] = int(_cb_state["consecutive_losses"]) + 1
        n = _cb_state["consecutive_losses"]
        logger.warning("⚠️  CB: %d pérdida(s) consecutiva(s) | %s", n, symbol)

        if n >= CB_CONSECUTIVE_LIMIT:
            until = datetime.utcnow() + timedelta(minutes=CB_COOLDOWN_MINUTES)
            _cb_state.update({
                "blocked":       True,
                "blocked_until": until,
                "reason":        (f"🛑 {n} pérdidas consecutivas — "
                                  f"bot pausado hasta {until.strftime('%H:%M')} UTC"),
            })
            logger.warning("🛑 CIRCUIT BREAKER ACTIVADO | %s | cooldown hasta %s UTC",
                           symbol, until.strftime("%H:%M"))
            from services.telegram_service import send_telegram

            _msg = (
                f"🔴 Circuit Breaker activado\n"
                f"{CB_CONSECUTIVE_LIMIT} pérdidas consecutivas.\n"
                f"Bot bloqueado por {CB_COOLDOWN_MINUTES} minutos."
            )
            _fire_async(lambda: send_telegram(_msg))
        _schedule_cb_persist()


def cb_get_state() -> dict:
    """Retorna una copia del estado actual del Circuit Breaker."""
    return {
        "blocked":            _cb_state["blocked"],
        "blocked_until":      _cb_state["blocked_until"].isoformat() if _cb_state.get("blocked_until") else None,
        "consecutive_losses": _cb_state["consecutive_losses"],
        "reason":             _cb_state["reason"],
    }


def cb_reset() -> None:
    """Resetea manualmente el Circuit Breaker."""
    _cb_state.update({"blocked": False, "blocked_until": None,
                       "consecutive_losses": 0, "reason": ""})
    logger.info("✅ Circuit Breaker reseteado manualmente")
    _schedule_cb_persist()
