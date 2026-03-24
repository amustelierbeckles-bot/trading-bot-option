"""
Precios base, generador de precios simulados, nombres y URLs de activos OTC.
"""
import random
from typing import Dict, Optional
from data_provider import IndicatorSet

ASSET_PRICES: Dict[str, float] = {
    # Actualizado: marzo 2026
    "OTC_EURUSD": 1.0820,
    "OTC_GBPUSD": 1.2940,
    "OTC_USDJPY": 149.50,
    "OTC_USDCHF": 0.8850,
    "OTC_AUDUSD": 0.6280,
    "OTC_USDCAD": 1.3950,
    "OTC_NZDUSD": 0.5720,
    "OTC_EURJPY": 161.80,
    "OTC_EURGBP": 0.8360,
    "OTC_EURAUD": 1.7230,
    "OTC_EURCAD": 1.5094,
    "OTC_EURCHF": 0.9576,
    "OTC_GBPJPY": 193.50,
    "OTC_GBPAUD": 2.0605,
    "OTC_GBPCAD": 1.8051,
    "OTC_GBPCHF": 1.1452,
    "OTC_AUDJPY": 93.89,
    "OTC_AUDCAD": 0.8761,
    "OTC_CADJPY": 107.17,
    "OTC_CHFJPY": 168.93,
}

# Estado del generador de precios con momentum persistente
_price_state: Dict[str, Dict] = {}


def get_asset_price(symbol: str) -> float:
    """Genera precio simulado con momentum mean-reverting persistente."""
    base = ASSET_PRICES.get(symbol, 1.0000)
    state = _price_state.get(symbol)

    if not state:
        state = {"price": base, "momentum": 0.0, "ticks": 0}
        _price_state[symbol] = state

    drift       = (base - state["price"]) * 0.003
    noise       = random.gauss(0, base * 0.0003)
    momentum    = state["momentum"] * 0.85 + drift + noise
    new_price   = state["price"] + momentum

    state["price"]    = round(new_price, 5)
    state["momentum"] = momentum
    state["ticks"]   += 1

    return state["price"]


def get_price_trend(symbol: str, ind: Optional[IndicatorSet] = None) -> str:
    """Retorna tendencia: usa indicadores reales si están disponibles."""
    if ind and ind.is_real:
        return ind.trend
    state = _price_state.get(symbol)
    if not state:
        return "neutral"
    m         = state["momentum"]
    threshold = ASSET_PRICES.get(symbol, 1.0) * 0.0001
    if m > threshold:  return "bullish"
    if m < -threshold: return "bearish"
    return "neutral"


def get_asset_name(symbol: str) -> str:
    """Convierte símbolo OTC a nombre legible. Ej: OTC_EURUSD → EUR/USD OTC"""
    mapping = {
        "OTC_EURUSD": "EUR/USD OTC", "OTC_GBPUSD": "GBP/USD OTC",
        "OTC_USDJPY": "USD/JPY OTC", "OTC_USDCHF": "USD/CHF OTC",
        "OTC_AUDUSD": "AUD/USD OTC", "OTC_USDCAD": "USD/CAD OTC",
        "OTC_NZDUSD": "NZD/USD OTC", "OTC_EURJPY": "EUR/JPY OTC",
        "OTC_EURGBP": "EUR/GBP OTC", "OTC_EURAUD": "EUR/AUD OTC",
        "OTC_EURCAD": "EUR/CAD OTC", "OTC_EURCHF": "EUR/CHF OTC",
        "OTC_GBPJPY": "GBP/JPY OTC", "OTC_GBPAUD": "GBP/AUD OTC",
        "OTC_GBPCAD": "GBP/CAD OTC", "OTC_GBPCHF": "GBP/CHF OTC",
        "OTC_AUDJPY": "AUD/JPY OTC", "OTC_AUDCAD": "AUD/CAD OTC",
        "OTC_CADJPY": "CAD/JPY OTC", "OTC_CHFJPY": "CHF/JPY OTC",
    }
    if symbol not in mapping and symbol.startswith("OTC_"):
        raw = symbol.replace("OTC_", "")
        return f"{raw[:3]}/{raw[3:]} OTC"
    return mapping.get(symbol, symbol)


def generate_pocket_option_url(symbol: str) -> str:
    """Genera URL directa al activo en PocketOption."""
    clean = symbol.replace("OTC_", "").replace("_", "")
    asset_param = f"{clean}-OTC" if "OTC" in symbol else clean
    return f"https://pocketoption.com/en/quick-trading/?asset={asset_param}"
