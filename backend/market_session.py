"""
Detección de sesión de mercado y ventanas de operación.

Sesiones en UTC:
  london   08:00–16:00 UTC  → alta volatilidad EUR/GBP, ideal RangeBreakout
  newyork  13:00–21:00 UTC  → solapamiento NY+Londres 13–16h, tendencias fuertes
  asia     00:00–08:00 UTC  → baja volatilidad, lateralización, JPY/AUD

Ventanas de operación del usuario (UTC-5):
  Mañana:    09:30–12:00 UTC-5 → 14:30–17:00 UTC → london+newyork
  Madrugada: 00:00–02:00 UTC-5 → 05:00–07:00 UTC → london temprano
"""

ALL_20_PAIRS = [
    "OTC_EURUSD", "OTC_GBPUSD", "OTC_USDJPY", "OTC_USDCHF",
    "OTC_AUDUSD", "OTC_NZDUSD", "OTC_USDCAD", "OTC_EURJPY",
    "OTC_EURGBP", "OTC_EURAUD", "OTC_EURCAD", "OTC_EURCHF",
    "OTC_GBPJPY", "OTC_GBPAUD", "OTC_GBPCAD", "OTC_GBPCHF",
    "OTC_AUDJPY", "OTC_AUDCAD", "OTC_CADJPY", "OTC_CHFJPY",
]


def get_market_session(utc_hour: int, utc_minute: int = 0) -> dict:
    """
    Detecta la sesión de mercado activa y sus características.

    Retorna dict con:
      name         : str   — "london" | "newyork" | "asia" | "off"
      display      : str   — etiqueta legible
      active       : bool  — si el bot debe escanear
      quality_boost: float — bonificación de umbral en esta sesión
      pairs        : list  — pares a escanear
      description  : str
      utc5_display : str   — hora local UTC-5
    """
    # UTC → UTC-5 en minutos totales
    utc5_total = (utc_hour * 60 + utc_minute) - 300
    if utc5_total < 0:
        utc5_total += 1440
    utc5_hour = utc5_total // 60
    utc5_min  = utc5_total % 60
    t = utc5_total

    MORNING_START = 9 * 60 + 30    # 570 min UTC-5 → 14:30 UTC
    MORNING_END   = 12 * 60         # 720 min UTC-5 → 17:00 UTC
    NIGHT_START   = 0               #   0 min UTC-5 → 05:00 UTC
    NIGHT_END     = 2 * 60          # 120 min UTC-5 → 07:00 UTC

    # Sesión UTC real para etiquetas consistentes con /v1/stats
    utc_t = utc_hour * 60 + utc_minute
    if 480 <= utc_t < 780:          # 08:00–13:00 UTC
        session_type = "london"
    elif 780 <= utc_t < 1260:       # 13:00–21:00 UTC
        session_type = "newyork"
    elif utc_t < 480 or utc_t >= 1260:
        session_type = "asia"
    else:
        session_type = "off"

    if MORNING_START <= t < MORNING_END:
        return {
            "name":          session_type,
            "display":       "Mañana (09:30–12:00)",
            "active":        True,
            "quality_boost": 0.06,
            "pairs":         ALL_20_PAIRS,
            "description":   f"Ventana mañana — {session_type} activa, 20 pares",
            "utc5_display":  f"{utc5_hour:02d}:{utc5_min:02d} UTC-5",
        }

    if NIGHT_START <= t < NIGHT_END:
        return {
            "name":          session_type,
            "display":       "Madrugada (00:00–02:00)",
            "active":        True,
            "quality_boost": 0.03,
            "pairs":         ALL_20_PAIRS,
            "description":   f"Ventana madrugada — {session_type} activa, 20 pares",
            "utc5_display":  f"{utc5_hour:02d}:{utc5_min:02d} UTC-5",
        }

    # Fuera de ventanas → PAUSADO
    if t < NIGHT_END:
        mins_next, next_w = NIGHT_END - t, "02:00 (fin madrugada)"
    elif t < MORNING_START:
        mins_next, next_w = MORNING_START - t, "09:30 (mañana)"
    else:
        mins_next, next_w = (1440 - t), "00:00 (madrugada)"

    return {
        "name":          "off",
        "display":       "Fuera de ventana",
        "active":        False,
        "quality_boost": 0.0,
        "pairs":         [],
        "description":   (
            f"Bot pausado — próxima ventana: {next_w} UTC-5 "
            f"(en ~{mins_next} min) · 0 créditos consumidos"
        ),
        "utc5_display":  f"{utc5_hour:02d}:{utc5_min:02d} UTC-5",
    }
