"""
Circuit Breaker autónomo.

Se actualiza cada vez que se verifica un resultado en audit_service,
sin requerir intervención del usuario.

Estado:
  _cb_state["blocked"]            → bool
  _cb_state["blocked_until"]      → datetime | None
  _cb_state["consecutive_losses"] → int
  _cb_state["reason"]             → str
"""
import logging
from datetime import datetime, timedelta
from typing import Dict

logger = logging.getLogger(__name__)

_cb_state: Dict[str, object] = {
    "blocked":            False,
    "blocked_until":      None,
    "consecutive_losses": 0,
    "reason":             "",
}

CB_CONSECUTIVE_LIMIT = 3
CB_COOLDOWN_MINUTES  = 60


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
