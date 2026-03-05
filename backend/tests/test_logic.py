import pytest
import sys
from pathlib import Path

# Asegurar importación
sys.path.append(str(Path(__file__).parent.parent))

from server import _conf_from_extreme, get_asset_price, TradingStrategy

def test_conf_from_extreme_logic():
    """
    Verifica que la función de confianza retorne valores lógicos.
    """
    # Caso 1: Valor en zona "mala" (neutral) -> confianza 0
    # low_good=30, high_good=70. Valor 50 está en medio.
    assert _conf_from_extreme(50, 10, 30, 70, 90) == 0.0

    # Caso 2: Valor extremo bajo (ej. RSI 20)
    # low_bad=10, low_good=30. 20 está justo en el medio del rango bajo.
    # ratio = (30 - 20) / (30 - 10) = 10 / 20 = 0.5
    # result = 0.60 + (0.82 - 0.60) * 0.5 = 0.60 + 0.11 = 0.71
    conf = _conf_from_extreme(20, 10, 30, 70, 90)
    assert 0.60 <= conf <= 0.82
    assert conf == 0.71

    # Caso 3: Valor extremo alto (ej. RSI 80)
    # high_good=70, high_bad=90. 80 está en el medio.
    conf_high = _conf_from_extreme(80, 10, 30, 70, 90)
    assert conf_high == 0.71

def test_get_asset_price_structure():
    """
    Verifica que el generador de precios retorne un float válido.
    """
    price = get_asset_price("OTC_EURUSD")
    assert isinstance(price, float)
    assert price > 0

def test_trading_strategy_base():
    """
    Verifica la clase base de estrategia.
    """
    strategy = TradingStrategy("Test Strategy", weight=1.5)
    assert strategy.name == "Test Strategy"
    assert strategy.weight == 1.5
    assert strategy.enabled is True
