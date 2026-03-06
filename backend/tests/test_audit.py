import pytest
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.append(str(Path(__file__).parent.parent))

from data_provider import TwelveDataProvider, CandleData


def _make_provider(configured=True):
    """Crea un provider con API key simulada."""
    import time as _time
    p = TwelveDataProvider.__new__(TwelveDataProvider)
    p.api_key        = "test_key" if configured else ""
    p.is_configured  = configured
    p.cache_ttl      = 300
    p._cache         = {}
    p._req_today     = 0
    p._client        = None
    p._req_reset_t   = _time.time() + 86400   # límite diario no alcanzado
    p.DAILY_LIMIT    = 800
    return p


def _make_candles(prices: list) -> list:
    """Genera velas ficticias con los precios dados."""
    return [
        CandleData(
            time   = f"2026-03-05 10:0{i}:00",
            open   = p,
            high   = p + 0.0001,
            low    = p - 0.0001,
            close  = p,
            volume = 100.0,
        )
        for i, p in enumerate(prices)
    ]


@pytest.mark.asyncio
async def test_get_price_for_audit_returns_penultimate_candle():
    """
    Verifica que get_price_for_audit() retorne la penúltima vela (cerrada),
    NO la última (que puede estar en formación).
    """
    provider = _make_provider(configured=True)
    candles  = _make_candles([1.0820, 1.0825, 1.0830])  # 3 velas
    
    with patch.object(provider, "_fetch_candles", new=AsyncMock(return_value=candles)):
        result = await provider.get_price_for_audit("OTC_EURUSD")
    
    # Debe retornar el cierre de la PENÚLTIMA (índice -2), no la última
    assert result == 1.0825, f"Esperado 1.0825 (penúltima), obtenido {result}"


@pytest.mark.asyncio
async def test_get_price_for_audit_invalidates_cache():
    """
    Verifica que el caché sea eliminado antes de la petición,
    garantizando un precio fresco y no el precio de entrada.
    """
    provider = _make_provider(configured=True)
    
    # Simular un caché "fresco" con el precio de entrada
    provider._cache["OTC_EURUSD"] = {
        "indicators": MagicMock(price=1.0820),
        "expires": __import__("time").time() + 300,  # válido por 5 min más
    }
    
    candles = _make_candles([1.0820, 1.0835, 1.0840])
    
    with patch.object(provider, "_fetch_candles", new=AsyncMock(return_value=candles)):
        result = await provider.get_price_for_audit("OTC_EURUSD")
    
    # El caché fue invalidado → precio real, no el precio de entrada (1.0820)
    assert result == 1.0835
    assert result != 1.0820, "No debe retornar el precio cacheado (precio de entrada)"


@pytest.mark.asyncio
async def test_get_price_for_audit_returns_none_when_not_configured():
    """
    Verifica que retorne None si la API no está configurada.
    """
    provider = _make_provider(configured=False)
    result   = await provider.get_price_for_audit("OTC_EURUSD")
    assert result is None


@pytest.mark.asyncio
async def test_get_price_for_audit_returns_none_on_api_error():
    """
    Verifica que retorne None si la API falla, sin lanzar excepción.
    """
    provider = _make_provider(configured=True)
    
    with patch.object(provider, "_fetch_candles", new=AsyncMock(side_effect=Exception("API timeout"))):
        result = await provider.get_price_for_audit("OTC_EURUSD")
    
    assert result is None
