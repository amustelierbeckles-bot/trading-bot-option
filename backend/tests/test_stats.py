"""
Tests para Sprint 1 — Persistencia y caché de Win Rate.

Cubre:
- _hour_bucket / _day_bucket (campos desnormalizados)
- _wr_cache_get / _wr_cache_set / _wr_cache_invalidate (helper caché)
- GET /v1/stats con datos en memoria (use_mongo=False)
"""
import pytest
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.append(str(Path(__file__).parent.parent))

from datetime import datetime
from server import _hour_bucket, _day_bucket, _wr_cache_get, _wr_cache_set, _wr_cache_invalidate


# ── Buckets de tiempo ─────────────────────────────────────────────────────────

def test_hour_bucket_format():
    dt = datetime(2026, 3, 6, 14, 30, 0)
    assert _hour_bucket(dt) == "2026-03-06T14"


def test_day_bucket_format():
    dt = datetime(2026, 3, 6, 14, 30, 0)
    assert _day_bucket(dt) == "2026-03-06"


def test_hour_bucket_different_hours():
    """Dos señales en la misma hora deben tener el mismo bucket."""
    dt1 = datetime(2026, 3, 6, 14, 0, 0)
    dt2 = datetime(2026, 3, 6, 14, 59, 59)
    assert _hour_bucket(dt1) == _hour_bucket(dt2)


def test_hour_bucket_different_hours_differ():
    dt1 = datetime(2026, 3, 6, 14, 0, 0)
    dt2 = datetime(2026, 3, 6, 15, 0, 0)
    assert _hour_bucket(dt1) != _hour_bucket(dt2)


# ── Caché in-memory (Redis=None) ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_wr_cache_set_and_get_inmemory():
    """Sin Redis, el caché in-memory debe funcionar correctamente."""
    await _wr_cache_set(None, "wr:OTC_EURUSD:1h", {"win_rate": 72.5, "total": 20})
    result = await _wr_cache_get(None, "wr:OTC_EURUSD:1h")
    assert result is not None
    assert result["win_rate"] == 72.5
    assert result["total"] == 20


@pytest.mark.asyncio
async def test_wr_cache_miss_returns_none():
    """Una clave que no existe debe retornar None."""
    result = await _wr_cache_get(None, "wr:NONEXISTENT:99h")
    assert result is None


@pytest.mark.asyncio
async def test_wr_cache_invalidate_inmemory():
    """Invalidar un patrón debe limpiar las claves que empiecen con él."""
    await _wr_cache_set(None, "wr:OTC_EURUSD:1h",  {"win_rate": 70.0})
    await _wr_cache_set(None, "wr:OTC_EURUSD:4h",  {"win_rate": 68.0})
    await _wr_cache_set(None, "wr:OTC_GBPUSD:1h",  {"win_rate": 65.0})  # no debe borrarse

    await _wr_cache_invalidate(None, "wr:OTC_EURUSD")

    assert await _wr_cache_get(None, "wr:OTC_EURUSD:1h") is None
    assert await _wr_cache_get(None, "wr:OTC_EURUSD:4h") is None
    assert await _wr_cache_get(None, "wr:OTC_GBPUSD:1h") is not None, \
        "No debe invalidar claves de otros pares"


@pytest.mark.asyncio
async def test_wr_cache_with_redis_set_and_get():
    """Con Redis mock, debe usar redis.set y redis.get."""
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value='{"win_rate": 75.0}')
    mock_redis.set = AsyncMock()

    await _wr_cache_set(mock_redis, "wr:global:1h", {"win_rate": 75.0})
    mock_redis.set.assert_called_once()

    result = await _wr_cache_get(mock_redis, "wr:global:1h")
    assert result == {"win_rate": 75.0}
    mock_redis.get.assert_called_once_with("wr:global:1h")


@pytest.mark.asyncio
async def test_wr_cache_redis_error_falls_back_to_memory():
    """Si Redis lanza excepción, debe caer al caché in-memory sin error."""
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(side_effect=Exception("Redis connection lost"))

    # Primero guardamos en memoria
    await _wr_cache_set(None, "wr:fallback:test", {"win_rate": 60.0})
    # Pedimos con Redis roto → debe retornar desde memoria
    result = await _wr_cache_get(mock_redis, "wr:fallback:test")
    assert result is not None
    assert result["win_rate"] == 60.0


# ── Endpoint /v1/stats ────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clear_wr_cache():
    """Limpia el caché in-memory entre tests para evitar interferencias."""
    import server
    server._wr_mem_cache.clear()
    yield
    server._wr_mem_cache.clear()


@pytest.mark.asyncio
async def test_stats_endpoint_empty(client):
    """Con trades_store vacío, debe retornar totales en cero sin error."""
    import server
    server.app.state.trades_store = []

    response = client.get("/v1/stats?window=1h")
    assert response.status_code == 200
    data = response.json()
    assert data["global"]["total"] == 0
    assert data["global"]["win_rate"] == 0.0
    assert data["window"] == "1h"


@pytest.mark.asyncio
async def test_stats_endpoint_with_trades(client):
    """Con trades reales verificados, debe calcular Win Rate correctamente."""
    import server
    server.app.state.use_mongo = False   # fuerza in-memory aunque Mongo esté disponible

    now_str = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S") + "Z"
    server.app.state.trades_store = [
        {"symbol": "OTC_EURUSD", "result": "win",  "audit_confidence": "high",
         "session": "london", "created_at": now_str, "payout": 85},
        {"symbol": "OTC_EURUSD", "result": "win",  "audit_confidence": "high",
         "session": "london", "created_at": now_str, "payout": 85},
        {"symbol": "OTC_EURUSD", "result": "loss", "audit_confidence": "high",
         "session": "london", "created_at": now_str, "payout": 85},
        {"symbol": "OTC_GBPUSD", "result": "win",  "audit_confidence": "high",
         "session": "newyork", "created_at": now_str, "payout": 85},
    ]

    response = client.get("/v1/stats?window=1h")
    assert response.status_code == 200
    data = response.json()

    assert data["global"]["total"] == 4
    assert data["global"]["wins"]  == 3
    assert data["global"]["win_rate"] == 75.0

    assert "OTC_EURUSD" in data["by_pair"]
    assert data["by_pair"]["OTC_EURUSD"]["win_rate"] == pytest.approx(66.7, abs=0.1)

    assert "london" in data["by_session"]
    assert data["by_session"]["london"]["wins"] == 2


@pytest.mark.asyncio
async def test_stats_endpoint_filters_low_confidence(client):
    """Trades con audit_confidence='low' (datos simulados) NO deben sumarse al Win Rate."""
    import server
    server.app.state.use_mongo = False
    now_str = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S") + "Z"
    server.app.state.trades_store = [
        {"symbol": "OTC_EURUSD", "result": "win",  "audit_confidence": "high",
         "session": "london", "created_at": now_str, "payout": 85},
        {"symbol": "OTC_EURUSD", "result": "win",  "audit_confidence": "low",   # simulado
         "session": "london", "created_at": now_str, "payout": 85},
    ]

    response = client.get("/v1/stats?window=1h")
    data = response.json()
    # Solo 1 trade "high" debe contar
    assert data["global"]["total"] == 1


@pytest.mark.asyncio
async def test_stats_endpoint_caches_result(client):
    """La segunda llamada al endpoint debe retornar cached=True."""
    import server
    server.app.state.trades_store = []
    server.app.state.redis = None   # caché in-memory

    # Primera llamada → calcula
    r1 = client.get("/v1/stats?window=4h")
    assert r1.json()["cached"] is False

    # Segunda llamada → desde caché
    r2 = client.get("/v1/stats?window=4h")
    assert r2.json()["cached"] is True


@pytest.mark.asyncio
async def test_stats_endpoint_invalid_window_defaults_to_1h(client):
    """Un window inválido debe ser ignorado y usar 1h por defecto."""
    import server
    server.app.state.trades_store = []

    response = client.get("/v1/stats?window=99h")
    assert response.status_code == 200
    assert response.json()["window"] == "1h"
