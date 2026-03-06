import pytest
from server import CCIAlligatorStrategy, _orthogonal_score, IndicatorSet

class MockIndicatorSet:
    def __init__(self, cci=0, trend="neutral", is_real=True):
        self.cci = cci
        self.trend = trend
        self.is_real = is_real
        # Valores dummy para otros indicadores
        self.rsi = 50
        self.stoch_k = 50
        self.macd_line = 0
        self.macd_hist = 0
        self.ema9 = 100
        self.ema21 = 100
        self.price = 100
        self.bb_upper = 105
        self.bb_lower = 95

def test_cci_alligator_strategy():
    """
    Verifica la lógica de la estrategia CCI + Alligator.
    """
    strategy = CCIAlligatorStrategy()
    
    # Caso 1: CCI > 100 (sobrecompra) + Tendencia Bajista -> PUT
    ind_put = MockIndicatorSet(cci=150, trend="bearish")
    signal_put = strategy.generate_signal(ind_put)
    
    assert signal_put is not None
    assert signal_put["type"] == "PUT"
    assert signal_put["confidence"] > 0.60
    assert "CCI sobrecomprado" in signal_put["reason"]

    # Caso 2: CCI < -100 (sobreventa) + Tendencia Alcista -> CALL
    ind_call = MockIndicatorSet(cci=-150, trend="bullish")
    signal_call = strategy.generate_signal(ind_call)
    
    assert signal_call is not None
    assert signal_call["type"] == "CALL"
    assert "CCI sobrevendido" in signal_call["reason"]

    # Caso 3: CCI Normal (-50) -> Ninguna señal
    ind_normal = MockIndicatorSet(cci=-50, trend="neutral")
    assert strategy.generate_signal(ind_normal) is None

def test_orthogonal_score_diverse():
    """
    Verifica que 3 estrategias de grupos distintos reciban un score alto.
    CCI (cci_reversal) + EMA (ema_trend) + MACD (macd_stoch) = 3 grupos / 4 total = 0.75
    """
    strategies = ["CCI + Alligator", "EMA Crossover", "MACD + Stochastic"]
    score = _orthogonal_score(strategies)
    assert score == 0.75, f"Esperado 0.75, obtenido {score}"

def test_orthogonal_score_redundant():
    """
    Verifica que estrategias del mismo grupo (rsi_momentum) no sumen doble.
    KeltnerRSI + RSIBollinger son el mismo grupo → 1 grupo / 4 total = 0.25
    """
    strategies = ["Keltner Channel + RSI", "RSI + Bollinger Bands"]
    score = _orthogonal_score(strategies)
    assert score == 0.25, f"Esperado 0.25, obtenido {score}"

def test_orthogonal_score_mixed():
    """
    Verifica el caso mixto: 2 del mismo grupo + 1 distinto = 2 grupos / 4 = 0.50
    Aunque hay 3 estrategias, la diversidad real es solo 50%.
    """
    strategies = ["Keltner Channel + RSI", "RSI + Bollinger Bands", "CCI + Alligator"]
    score = _orthogonal_score(strategies)
    assert score == 0.50, f"Esperado 0.50, obtenido {score}"

def test_orthogonal_score_maximum():
    """
    Verifica que 4 estrategias de grupos distintos = score máximo 1.0
    """
    strategies = [
        "Keltner Channel + RSI",  # rsi_momentum
        "CCI + Alligator",        # cci_reversal
        "MACD + Stochastic",      # macd_stoch
        "EMA Crossover",          # ema_trend
    ]
    score = _orthogonal_score(strategies)
    assert score == 1.0, f"Esperado 1.0, obtenido {score}"

def test_orthogonal_score_empty():
    """
    Verifica que una lista vacía retorne 0.0 sin errores.
    """
    assert _orthogonal_score([]) == 0.0

def test_cci_alligator_fallback():
    """
    Verifica que la estrategia funcione en modo simulado (sin indicadores reales).
    """
    strategy = CCIAlligatorStrategy()
    
    # Simula sin indicadores (None)
    # Debería usar fallback aleatorio, pero retornar algo o nada sin crashear
    try:
        result = strategy.generate_signal(None)
        # El resultado es aleatorio, así que solo verificamos que no lance excepción
        assert result is None or isinstance(result, dict)
    except Exception as e:
        pytest.fail(f"La estrategia falló en modo fallback: {e}")
