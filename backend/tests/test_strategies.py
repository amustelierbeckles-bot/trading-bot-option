import pytest
from server import CCIAlligatorStrategy, IndicatorSet

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
