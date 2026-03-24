import pytest
from strategies import CCIAlligatorStrategy, RangeBreakoutStrategy, MACDStochasticStrategy
from scoring import orthogonal_score as _orthogonal_score, _TOTAL_GROUPS


class MockIndicatorSet:
    """IndicatorSet mínimo para tests unitarios de estrategias."""
    def __init__(self, cci=0, trend="neutral", is_real=True,
                 rsi=50, price=1.0820, ema21=1.0800,
                 atr=0.0010, atr_pct=0.09, macd_hist=0.0, stoch_k=50):
        self.cci       = cci
        self.trend     = trend
        self.is_real   = is_real
        self.rsi       = rsi
        self.stoch_k   = stoch_k
        self.macd_line = 0.0
        self.macd_hist = macd_hist
        self.ema9      = price
        self.ema21     = ema21
        self.price     = price
        self.atr       = atr
        self.atr_pct   = atr_pct
        self.bb_upper  = price + atr * 2
        self.bb_lower  = price - atr * 2


# ── CCI + Alligator ───────────────────────────────────────────────────────────

def test_cci_alligator_strategy():
    """Verifica la lógica de la estrategia CCI + Alligator."""
    strategy = CCIAlligatorStrategy()

    ind_put = MockIndicatorSet(cci=150, trend="bearish")
    signal_put = strategy.generate_signal(ind_put)
    assert signal_put is not None
    assert signal_put["type"] == "PUT"
    assert signal_put["confidence"] > 0.60
    assert "CCI sobrecomprado" in signal_put["reason"]

    ind_call = MockIndicatorSet(cci=-150, trend="bullish")
    signal_call = strategy.generate_signal(ind_call)
    assert signal_call is not None
    assert signal_call["type"] == "CALL"
    assert "CCI sobrevendido" in signal_call["reason"]

    ind_normal = MockIndicatorSet(cci=-50, trend="neutral")
    assert strategy.generate_signal(ind_normal) is None


def test_cci_alligator_fallback():
    """Verifica que la estrategia no lance excepción sin indicadores."""
    strategy = CCIAlligatorStrategy()
    result = strategy.generate_signal(None)
    assert result is None or isinstance(result, dict)


# ── Range Breakout + ATR ──────────────────────────────────────────────────────

def test_range_breakout_call():
    """
    CALL: precio rompe por encima de EMA21 + ATR*1.2, MACD hist positivo,
    tendencia alcista.
    """
    strategy = RangeBreakoutStrategy()
    # ema21=1.0800, atr=0.0010, breakout_band=0.0012
    # → umbral superior = 1.0812  → price=1.0820 lo rompe
    ind = MockIndicatorSet(
        price=1.0820, ema21=1.0800, atr=0.0010, atr_pct=0.09,
        macd_hist=0.0003, trend="bullish", cci=50,
    )
    signal = strategy.generate_signal(ind)
    assert signal is not None, "Debería generar señal CALL"
    assert signal["type"] == "CALL"
    assert 0.55 < signal["confidence"] < 0.85
    assert "Breakout alcista" in signal["reason"]


def test_range_breakout_put():
    """
    PUT: precio rompe por debajo de EMA21 - ATR*1.2, MACD hist negativo,
    tendencia bajista.
    """
    strategy = RangeBreakoutStrategy()
    # ema21=1.0800, atr=0.0010, breakout_band=0.0012
    # → umbral inferior = 1.0788  → price=1.0775 lo rompe
    ind = MockIndicatorSet(
        price=1.0775, ema21=1.0800, atr=0.0010, atr_pct=0.09,
        macd_hist=-0.0003, trend="bearish", cci=-80,
    )
    signal = strategy.generate_signal(ind)
    assert signal is not None, "Debería generar señal PUT"
    assert signal["type"] == "PUT"
    assert "Breakout bajista" in signal["reason"]


def test_range_breakout_no_signal_inside_range():
    """
    Sin señal cuando el precio está dentro del rango normal (no hay breakout).
    """
    strategy = RangeBreakoutStrategy()
    ind = MockIndicatorSet(
        price=1.0805, ema21=1.0800, atr=0.0010, atr_pct=0.09,
        macd_hist=0.0001, trend="bullish",
    )
    assert strategy.generate_signal(ind) is None


def test_range_breakout_no_signal_low_volatility():
    """
    Sin señal cuando la volatilidad es insuficiente (mercado lateral).
    """
    strategy = RangeBreakoutStrategy()
    ind = MockIndicatorSet(
        price=1.0820, ema21=1.0800, atr=0.0003, atr_pct=0.02,  # ATR% < 0.04
        macd_hist=0.0003, trend="bullish",
    )
    assert strategy.generate_signal(ind) is None, \
        "No debe generar señal en mercado con ATR% < MIN_ATR_PCT"


def test_range_breakout_no_signal_unconfirmed_macd():
    """
    Sin señal cuando el precio rompe pero MACD no confirma la dirección.
    """
    strategy = RangeBreakoutStrategy()
    ind = MockIndicatorSet(
        price=1.0820, ema21=1.0800, atr=0.0010, atr_pct=0.09,
        macd_hist=-0.0002,   # ← MACD negativo mientras precio sube: divergencia
        trend="bullish",
    )
    assert strategy.generate_signal(ind) is None, \
        "Sin confirmación de MACD no debe generar CALL aunque el precio rompa"


def test_range_breakout_no_signal_simulated_data():
    """La estrategia requiere datos reales (is_real=False → None)."""
    strategy = RangeBreakoutStrategy()
    ind = MockIndicatorSet(is_real=False, price=1.0820, ema21=1.0800)
    assert strategy.generate_signal(ind) is None


# ── MACD + Stochastic ─────────────────────────────────────────────────────────

def test_macd_stoch_agotamiento_alcista_es_put():
    """Stoch >= 95 con MACD positivo = agotamiento = PUT (no CALL)."""
    strategy = MACDStochasticStrategy()
    ind = MockIndicatorSet(stoch_k=96.0, macd_hist=0.0005, cci=10)
    sig = strategy.generate_signal(ind)
    assert sig is not None
    assert sig["type"] == "PUT"
    assert "agotamiento alcista extremo" in sig["reason"]
    assert "MACD hist > 0" in sig["reason"]
    assert sig["confidence"] >= strategy.min_confidence


def test_macd_stoch_agotamiento_bajista_es_call():
    """Stoch <= 5 con MACD negativo = agotamiento = CALL (no PUT)."""
    strategy = MACDStochasticStrategy()
    ind = MockIndicatorSet(stoch_k=3.0, macd_hist=-0.0005, cci=-10)
    sig = strategy.generate_signal(ind)
    assert sig is not None
    assert sig["type"] == "CALL"
    assert "agotamiento bajista extremo" in sig["reason"]
    assert "MACD hist < 0" in sig["reason"]
    assert sig["confidence"] >= strategy.min_confidence


def test_macd_stoch_sobrevendido_macd_alcista_es_call():
    """Stoch < 20 + histograma MACD > 0 → CALL (zona clásica)."""
    strategy = MACDStochasticStrategy()
    ind = MockIndicatorSet(stoch_k=15.0, macd_hist=0.0003, cci=0)
    sig = strategy.generate_signal(ind)
    assert sig is not None
    assert sig["type"] == "CALL"
    assert "sobrevendido" in sig["reason"]
    assert sig["confidence"] >= strategy.min_confidence


def test_macd_stoch_sobrecomprado_macd_bajista_es_put():
    """Stoch > 80 + histograma MACD < 0 → PUT (zona clásica)."""
    strategy = MACDStochasticStrategy()
    ind = MockIndicatorSet(stoch_k=85.0, macd_hist=-0.0003, cci=0)
    sig = strategy.generate_signal(ind)
    assert sig is not None
    assert sig["type"] == "PUT"
    assert "sobrecomprado" in sig["reason"]
    assert sig["confidence"] >= strategy.min_confidence


# ── Orthogonal Score ──────────────────────────────────────────────────────────

def test_total_groups_is_five():
    """Con el reemplazo de KeltnerRSI → RangeBreakout, ahora hay 5 grupos ortogonales."""
    assert _TOTAL_GROUPS == 5, (
        f"Se esperaban 5 grupos ortogonales, se encontraron {_TOTAL_GROUPS}. "
        "Verificar _STRATEGY_GROUPS en server.py."
    )


def test_orthogonal_score_diverse():
    """
    3 estrategias de grupos distintos: {cci_reversal, ema_trend, macd_stoch}
    = 3/5 = 0.60
    """
    strategies = ["CCI + Alligator", "EMA Crossover", "MACD + Stochastic"]
    score = _orthogonal_score(strategies)
    assert score == 0.60, f"Esperado 0.60, obtenido {score}"


def test_orthogonal_score_redundant():
    """
    RSIBollinger solo (rsi_momentum) → 1 grupo / 5 = 0.20
    """
    strategies = ["RSI + Bollinger Bands"]
    score = _orthogonal_score(strategies)
    assert score == 0.20, f"Esperado 0.20, obtenido {score}"


def test_orthogonal_score_mixed():
    """
    RSIBollinger + RangeBreakout + CCI = 3 grupos distintos / 5 = 0.60
    (breakout_volatility + rsi_momentum + cci_reversal)
    """
    strategies = ["RSI + Bollinger Bands", "Range Breakout + ATR", "CCI + Alligator"]
    score = _orthogonal_score(strategies)
    assert score == 0.60, f"Esperado 0.60, obtenido {score}"


def test_orthogonal_score_maximum():
    """
    Las 5 estrategias de grupos distintos = 5/5 = 1.0
    """
    strategies = [
        "Range Breakout + ATR",  # breakout_volatility
        "RSI + Bollinger Bands", # rsi_momentum
        "CCI + Alligator",       # cci_reversal
        "MACD + Stochastic",     # macd_stoch
        "EMA Crossover",         # ema_trend
    ]
    score = _orthogonal_score(strategies)
    assert score == 1.0, f"Esperado 1.0, obtenido {score}"


def test_orthogonal_score_empty():
    """Lista vacía → 0.0 sin errores."""
    assert _orthogonal_score([]) == 0.0
