"""
Quality Score y helpers de análisis de señales.

Componentes del quality_score:
  - Confluencia ortogonal (diversidad de grupos)  → 30 %
  - Confianza promedio ponderada del ensemble      → 30 %
  - Fuerza del CCI (normalización sigmoidal)       → 15 %
  - Alineación con micro-tendencia del par         → 15 %
  - Bonus de consenso completo                     → 10 %
  - Bonus por datos reales                         → +5 % (extra)
"""
import math
from typing import Dict, List, Optional
from data_provider import IndicatorSet

# Mapa de grupos ortogonales por estrategia.
# Penaliza el consenso falso: 3 estrategias del mismo oscilador = 1 grupo.
_STRATEGY_GROUPS: Dict[str, str] = {
    "Range Breakout + ATR":  "breakout_volatility",  # anticorrelacionada con reversión
    "RSI + Bollinger Bands": "rsi_momentum",
    "CCI + Alligator":       "cci_reversal",
    "MACD + Stochastic":     "macd_stoch",
    "EMA Crossover":         "ema_trend",
}
_TOTAL_GROUPS = len(set(_STRATEGY_GROUPS.values()))  # 5 grupos distintos


def cci_sigmoid(cci_abs: float) -> float:
    """
    Normalización sigmoidal del CCI:
    - CCI 0    → 0.0
    - CCI 100  → 0.46
    - CCI 140  → 0.68  (zona de alta probabilidad)
    - CCI 200  → 0.88
    - CCI 300  → 0.97  (asintótico)
    """
    return 1.0 - math.exp(-cci_abs / 200.0)


def orthogonal_score(strategies_agreeing: List[str]) -> float:
    """
    Mide la DIVERSIDAD real del consenso, no solo la cantidad de estrategias.

    Retorna 0.0–1.0:
    - 1.0 → todas las estrategias provienen de grupos ortogonales distintos
    - 0.5 → consenso parcialmente diverso
    - 0.25 → consenso concentrado en un solo tipo de indicador
    """
    if not strategies_agreeing:
        return 0.0
    unique_groups = {_STRATEGY_GROUPS.get(s, f"unknown_{s}") for s in strategies_agreeing}
    return round(len(unique_groups) / _TOTAL_GROUPS, 4)


def quality_score(signal: dict, symbol: str = None,
                  ind: Optional[IndicatorSet] = None) -> float:
    """
    Quality Score ponderado con Consenso Ortogonal (0–1).
    Importa get_price_trend en tiempo de ejecución para evitar circular import.
    """
    from assets import get_price_trend

    confidence          = signal.get("confidence", 0)
    cci_abs             = abs(signal.get("cci", 0))
    strategies_agreeing = signal.get("strategies_agreeing", [])
    n_agreeing          = len(strategies_agreeing)
    n_total             = signal.get("n_total", max(n_agreeing, 1))
    signal_type         = signal.get("type", "")

    ortho_confluence = orthogonal_score(strategies_agreeing)
    cci_factor       = cci_sigmoid(cci_abs)
    consensus        = 1.0 if n_agreeing == n_total else 0.0

    trend_score = 0.5
    if symbol or ind:
        trend = get_price_trend(symbol, ind)
        if trend == "bullish" and signal_type == "CALL":    trend_score = 1.0
        elif trend == "bearish" and signal_type == "PUT":   trend_score = 1.0
        elif trend == "bullish" and signal_type == "PUT":   trend_score = 0.15
        elif trend == "bearish" and signal_type == "CALL":  trend_score = 0.15

    real_bonus = 0.05 if (ind and ind.is_real) else 0.0

    return round(
        ortho_confluence * 0.30 +
        confidence       * 0.30 +
        cci_factor       * 0.15 +
        trend_score      * 0.15 +
        consensus        * 0.10 +
        real_bonus,
        4
    )
