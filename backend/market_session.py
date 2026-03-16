"""
Detección de sesión de mercado y ventanas de operación.

Sesiones en UTC:
  london   08:00–16:00 UTC  → alta volatilidad EUR/GBP, ideal RangeBreakout
  newyork  13:00–21:00 UTC  → solapamiento NY+Londres 13–16h, tendencias fuertes
  asia     00:00–08:00 UTC  → baja volatilidad, lateralización, JPY/AUD

Ventanas de operación del usuario (hora local DST-aware):
  Mañana:    09:30–12:00 hora local  (UTC-4 en verano / UTC-5 en invierno)
  Madrugada: 00:00–02:00 hora local

El offset UTC se calcula AUTOMÁTICAMENTE según las reglas DST de Cuba/Eastern:
  - Horario de verano (DST): 2do domingo de marzo → 1er domingo de noviembre → UTC-4
  - Horario estándar:        1er domingo de noviembre → 2do domingo de marzo  → UTC-5
"""

from datetime import datetime, timedelta

ALL_20_PAIRS = [
    "OTC_EURUSD", "OTC_GBPUSD", "OTC_USDJPY", "OTC_USDCHF",
    "OTC_AUDUSD", "OTC_NZDUSD", "OTC_USDCAD", "OTC_EURJPY",
    "OTC_EURGBP", "OTC_EURAUD", "OTC_EURCAD", "OTC_EURCHF",
    "OTC_GBPJPY", "OTC_GBPAUD", "OTC_GBPCAD", "OTC_GBPCHF",
    "OTC_AUDJPY", "OTC_AUDCAD", "OTC_CADJPY", "OTC_CHFJPY",
]


def _get_local_offset_hours() -> int:
    """
    Calcula el offset local respecto a UTC de forma DST-aware.

    Reglas de Cuba/Eastern (idénticas a las de telegram_service.py):
      DST activo:  2do domingo de marzo   → 1er domingo de noviembre → UTC-4
      DST inactivo: resto del año                                     → UTC-5

    Retorna -4 o -5.
    """
    now_utc   = datetime.utcnow()
    year      = now_utc.year
    dst_start = datetime(year, 3, 8)  + timedelta(days=(6 - datetime(year, 3, 8).weekday())  % 7)
    dst_end   = datetime(year, 11, 1) + timedelta(days=(6 - datetime(year, 11, 1).weekday()) % 7)
    return -4 if dst_start <= now_utc < dst_end else -5


def get_market_session(utc_hour: int, utc_minute: int = 0) -> dict:
    """
    Detecta la sesión de mercado activa y sus características.

    Las ventanas de operación están definidas en hora LOCAL (DST-aware).
    El offset se recalcula en cada llamada, así el cambio de horario
    se aplica automáticamente sin reiniciar el bot.

    Retorna dict con:
      name          : str   — "london" | "newyork" | "asia" | "off"
      display       : str   — etiqueta legible
      active        : bool  — si el bot debe escanear ahora
      quality_boost : float — bonificación de umbral en esta sesión
      pairs         : list  — pares a escanear
      description   : str
      local_display : str   — hora local con etiqueta DST correcta
      tz_label      : str   — "UTC-4" o "UTC-5"
    """
    # ── Offset DST dinámico ───────────────────────────────────────────────────
    offset_h  = _get_local_offset_hours()          # -4 o -5
    tz_label  = f"UTC{offset_h}"                   # "UTC-4" o "UTC-5"

    # UTC → hora local en minutos totales
    local_total = (utc_hour * 60 + utc_minute) + (offset_h * 60)
    if local_total < 0:
        local_total += 1440
    local_total %= 1440
    local_hour = local_total // 60
    local_min  = local_total % 60

    # ── Ventanas de operación en hora LOCAL (no cambian con el DST) ───────────
    MORNING_START = 9 * 60 + 30    # 09:30 hora local
    MORNING_END   = 12 * 60        # 12:00 hora local
    NIGHT_START   = 0              # 00:00 hora local
    NIGHT_END     = 2 * 60         # 02:00 hora local

    t = local_total

    # ── Sesión UTC real (para etiquetas consistentes con /v1/stats) ───────────
    utc_t = utc_hour * 60 + utc_minute
    if 480 <= utc_t < 780:
        session_type = "london"
    elif 780 <= utc_t < 1260:
        session_type = "newyork"
    else:
        session_type = "asia"

    local_display = f"{local_hour:02d}:{local_min:02d} {tz_label}"

    # ── Ventana mañana 09:30–12:00 hora local ─────────────────────────────────
    if MORNING_START <= t < MORNING_END:
        return {
            "name":          session_type,
            "display":       f"Mañana (09:30–12:00 {tz_label})",
            "active":        True,
            "quality_boost": 0.06,
            "pairs":         ALL_20_PAIRS,
            "description":   f"Ventana mañana — {session_type} activa, 20 pares",
            "local_display": local_display,
            "tz_label":      tz_label,
        }

    # ── Ventana madrugada 00:00–02:00 hora local ──────────────────────────────
    if NIGHT_START <= t < NIGHT_END:
        return {
            "name":          session_type,
            "display":       f"Madrugada (00:00–02:00 {tz_label})",
            "active":        True,
            "quality_boost": 0.03,
            "pairs":         ALL_20_PAIRS,
            "description":   f"Ventana madrugada — {session_type} activa, 20 pares",
            "local_display": local_display,
            "tz_label":      tz_label,
        }

    # ── Fuera de ventanas → PAUSADO ───────────────────────────────────────────
    if t < NIGHT_END:
        mins_next = NIGHT_END - t
        next_w    = f"02:00 (fin madrugada {tz_label})"
    elif t < MORNING_START:
        mins_next = MORNING_START - t
        next_w    = f"09:30 mañana ({tz_label})"
    else:
        mins_next = 1440 - t
        next_w    = f"00:00 madrugada ({tz_label})"

    return {
        "name":          "off",
        "display":       "Fuera de ventana",
        "active":        False,
        "quality_boost": 0.0,
        "pairs":         [],
        "description":   (
            f"Bot pausado — próxima ventana: {next_w} "
            f"(en ~{mins_next} min) · 0 créditos consumidos"
        ),
        "local_display": local_display,
        "tz_label":      tz_label,
    }
