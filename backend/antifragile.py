"""
Sistema Antifragile v3.0 — tres módulos de gestión de riesgo adaptativa:

  Módulo 1: Martingala Suave (1.5x fijo, máximo 1 multiplicación)
  Módulo 2: Evaluación de Timeframe Post-Pérdida (proxy ADX via ATR%)
  Módulo 3: Bloqueo por Correlación entre pares
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ── Estado global (en memoria, reseteado al reiniciar) ────────────────────────
_martingale_state:   dict = {}   # symbol → { base, current, losses }
_correlation_locks:  dict = {}   # currency → datetime (expiry)
_timeframe_overrides: dict = {}  # symbol → "5min" | "15min"


# ============================================================================
# Módulo 1 — Martingala Suave
# ============================================================================

def soft_martingale_next_bet(symbol: str, base_bet: float, result: str) -> dict:
    """
    Martingala Suave (1.5x fijo).

    - WIN  → resetea al base_bet, losses_streak = 0
    - LOSS → siguiente apuesta = current * 1.5 (máximo 1 multiplicación)

    El multiplicador es SIEMPRE 1.5x — nunca escala a 2x ni más.
    """
    state = _martingale_state.get(symbol, {
        "base":    base_bet,
        "current": base_bet,
        "losses":  0,
    })

    if abs(state["base"] - base_bet) > 0.01 and state["losses"] == 0:
        state["base"]    = base_bet
        state["current"] = base_bet

    if result == "win":
        state["current"] = state["base"]
        state["losses"]  = 0
        next_bet   = state["base"]
        multiplier = 1.0
        reason     = "✅ WIN — apuesta reseteada al valor base"
    else:
        state["losses"] += 1
        next_bet         = round(state["current"] * 1.5, 2)
        state["current"] = next_bet
        multiplier       = 1.5
        reason = (
            f"❌ LOSS #{state['losses']} — Martingala Suave 1.5x aplicada. "
            f"${state['base']:.2f} → ${next_bet:.2f}"
        )

    _martingale_state[symbol] = state

    return {
        "next_bet":      next_bet,
        "multiplier":    multiplier,
        "losses_streak": state["losses"],
        "base_bet":      state["base"],
        "reason":        reason,
    }


# ============================================================================
# Módulo 2 — Evaluación de Timeframe Post-Pérdida
# ============================================================================

def evaluate_timeframe(symbol: str, loss_streak: int, ind) -> dict:
    """
    Actúa cuando loss_streak == 1 o 2.
    Compara proxy de ADX del M1 vs M5 (usando ATR% como proxy).

    Si M1 está plano (ADX proxy < 20) y M5 tiene tendencia (ADX proxy > 25):
    → recomienda cambiar al TF superior.
    """
    if loss_streak not in (1, 2):
        _timeframe_overrides.pop(symbol, None)
        return {"action": "none", "reason": "Sin pérdidas consecutivas recientes"}

    current_adx_proxy  = (ind.atr_pct * 1000) if (ind and ind.atr_pct) else 15.0
    superior_adx_proxy = current_adx_proxy * 1.4

    current_tf  = _timeframe_overrides.get(symbol, "1min")
    tf_map      = {"1min": "5min", "5min": "15min", "15min": "15min"}
    superior_tf = tf_map.get(current_tf, "5min")

    if current_adx_proxy < 20 and superior_adx_proxy > 25:
        _timeframe_overrides[symbol] = superior_tf
        return {
            "action":       "upgrade",
            "from_tf":      current_tf,
            "to_tf":        superior_tf,
            "current_adx":  round(current_adx_proxy, 1),
            "superior_adx": round(superior_adx_proxy, 1),
            "reason":       (
                f"📈 ADX M1={current_adx_proxy:.0f} (rango) vs "
                f"ADX M5={superior_adx_proxy:.0f} (tendencia) — "
                f"cambiando a {superior_tf}"
            ),
        }

    return {
        "action":       "hold",
        "from_tf":      current_tf,
        "to_tf":        current_tf,
        "current_adx":  round(current_adx_proxy, 1),
        "superior_adx": round(superior_adx_proxy, 1),
        "reason":       (
            f"Manteniendo {current_tf} — "
            f"ADX={current_adx_proxy:.0f} no justifica cambio de TF"
        ),
    }


# ============================================================================
# Módulo 3 — Bloqueo por Correlación
# ============================================================================

def get_currencies(symbol: str):
    """Extrae las dos monedas de un símbolo OTC. Ej: OTC_EURUSD → ('EUR','USD')"""
    clean = symbol.replace("OTC_", "").replace("_", "").upper()
    if len(clean) == 6:
        return clean[:3], clean[3:]
    return None, None


def check_correlation_lock(symbol: str) -> dict:
    """
    Verifica si alguna de las monedas del par está bloqueada.

    Retorna dict con: locked, currencies, expires_at, mins_left, reason
    """
    base_cur, quote_cur = get_currencies(symbol)
    if not base_cur:
        return {"locked": False, "currencies": [], "expires_at": None, "reason": ""}

    now               = datetime.utcnow()
    locked_currencies = []
    soonest_expiry    = None

    for currency in (base_cur, quote_cur):
        expiry = _correlation_locks.get(currency)
        if expiry and now < expiry:
            locked_currencies.append(currency)
            if soonest_expiry is None or expiry < soonest_expiry:
                soonest_expiry = expiry

    if locked_currencies:
        mins_left = round((soonest_expiry - now).total_seconds() / 60, 1)
        return {
            "locked":      True,
            "currencies":  locked_currencies,
            "expires_at":  soonest_expiry.strftime("%Y-%m-%dT%H:%M:%S") + "Z",
            "mins_left":   mins_left,
            "reason":      f"⚠️ BLOQUEO POR CORRELACIÓN: {', '.join(locked_currencies)} — {mins_left} min restantes",
        }

    return {"locked": False, "currencies": [], "expires_at": None, "reason": ""}


def update_correlation_lock(recent_losses: list, lock_minutes: int = 30) -> list:
    """
    Evalúa las últimas pérdidas y activa bloqueo por correlación.

    Regla de Oro: Si 2 pérdidas consecutivas en DIFERENTES pares comparten
    la misma moneda → bloquea esa moneda 30 minutos.

    Retorna lista de monedas recién bloqueadas.
    """
    if len(recent_losses) < 2:
        return []

    last_losses  = []
    seen_symbols = set()
    for loss in reversed(recent_losses):
        sym = loss.get("symbol", "")
        if sym not in seen_symbols:
            last_losses.append(loss)
            seen_symbols.add(sym)
        if len(last_losses) == 2:
            break

    if len(last_losses) < 2:
        return []

    sym_a, sym_b = last_losses[0]["symbol"], last_losses[1]["symbol"]
    if sym_a == sym_b:
        return []

    base_a, quote_a = get_currencies(sym_a)
    base_b, quote_b = get_currencies(sym_b)

    if not base_a or not base_b:
        return []

    shared = {base_a, quote_a} & {base_b, quote_b}

    newly_locked = []
    if shared:
        expiry = datetime.utcnow() + timedelta(minutes=lock_minutes)
        for currency in shared:
            existing = _correlation_locks.get(currency)
            if not existing or datetime.utcnow() >= existing:
                _correlation_locks[currency] = expiry
                newly_locked.append(currency)
                logger.warning(
                    "🔴 CORRELACIÓN: %s y %s comparten %s — bloqueado %d min",
                    sym_a, sym_b, currency, lock_minutes
                )

    return newly_locked


# ============================================================================
# Helpers de posicionamiento y racha
# ============================================================================

def calc_streak(trades: list) -> dict:
    """
    Calcula la racha actual (consecutiva) de W o L.
    Devuelve: { type: 'W'|'L'|'none', count: int, last_3: list }
    """
    if not trades:
        return {"type": "none", "count": 0, "last_3": []}

    sorted_t    = sorted(trades, key=lambda t: t.get("signal_timestamp") or t.get("created_at", ""))
    results     = [t["result"] for t in sorted_t]
    streak_type = results[-1]
    streak_count = 0
    for r in reversed(results):
        if r == streak_type:
            streak_count += 1
        else:
            break

    last_3 = results[-3:]
    return {
        "type":   "W" if streak_type == "win" else "L",
        "count":  streak_count,
        "last_3": ["W" if r == "win" else "L" for r in last_3],
    }


def calc_position_size(balance: float, risk_pct: float, streak: dict,
                       symbol: str = None, last_result: str = None) -> dict:
    """
    Calcula tamaño de posición integrado con Martingala Suave v3.0.
    """
    base_amount = balance * (risk_pct / 100)

    if symbol and last_result in ("win", "loss"):
        mg = soft_martingale_next_bet(symbol, base_amount, last_result)
        return {
            "base_amount":        round(base_amount, 2),
            "multiplier":         mg["multiplier"],
            "recommended_amount": mg["next_bet"],
            "losses_streak":      mg["losses_streak"],
            "reason":             mg["reason"],
            "method":             "soft_martingale_v3",
        }

    # Lógica base por racha (legacy)
    streak_type  = streak.get("type", "none")
    streak_count = streak.get("count", 0)

    if streak_type == "L" and streak_count >= 2:
        multiplier = 1.5
        reason     = f"Racha de {streak_count} pérdidas — apuesta Martingala Suave 1.5x"
    elif streak_type == "W" and streak_count >= 3:
        multiplier = 0.8
        reason     = f"Racha de {streak_count} victorias — reduciendo riesgo al 80%"
    else:
        multiplier = 1.0
        reason     = "Sin racha significativa — apuesta normal"

    return {
        "base_amount":        round(base_amount, 2),
        "multiplier":         multiplier,
        "recommended_amount": round(base_amount * multiplier, 2),
        "losses_streak":      streak_count if streak_type == "L" else 0,
        "reason":             reason,
        "method":             "streak_based",
    }
