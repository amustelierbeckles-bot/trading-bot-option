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
from win_rate_cache import (
    hour_bucket as _hour_bucket,
    day_bucket as _day_bucket,
    wr_cache_get as _wr_cache_get,
    wr_cache_set as _wr_cache_set,
    wr_cache_invalidate as _wr_cache_invalidate,
)


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


# ── Endpoint /api/stats ───────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clear_wr_cache():
    """Limpia el caché in-memory entre tests para evitar interferencias."""
    import win_rate_cache
    win_rate_cache._wr_mem_cache.clear()
    yield
    win_rate_cache._wr_mem_cache.clear()


@pytest.mark.asyncio
async def test_stats_endpoint_empty(client):
    """Con trades_store vacío, debe retornar totales en cero sin error."""
    import server
    server.app.state.use_mongo     = False
    server.app.state.trades_store  = []
    server.app.state.signals_store = []

    response = client.get("/api/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["total_trades"] == 0
    assert data["win_rate"] == 0.0
    assert data["period"] == "24h"


@pytest.mark.asyncio
async def test_stats_endpoint_with_trades(client):
    """Con trades reales, debe calcular Win Rate correctamente."""
    import server
    server.app.state.use_mongo = False

    now_str = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S") + "Z"
    server.app.state.signals_store = []
    server.app.state.trades_store = [
        {"symbol": "OTC_EURUSD", "result": "win",  "created_at": now_str},
        {"symbol": "OTC_EURUSD", "result": "win",  "created_at": now_str},
        {"symbol": "OTC_EURUSD", "result": "loss", "created_at": now_str},
        {"symbol": "OTC_GBPUSD", "result": "win",  "created_at": now_str},
    ]

    response = client.get("/api/stats")
    assert response.status_code == 200
    data = response.json()

    assert data["wins"]     == 3
    assert data["losses"]   == 1
    assert data["win_rate"] == 75.0


@pytest.mark.asyncio
async def test_stats_endpoint_returns_required_keys(client):
    """El endpoint debe devolver todas las claves esperadas."""
    import server
    server.app.state.trades_store  = []
    server.app.state.signals_store = []

    response = client.get("/api/stats")
    assert response.status_code == 200
    data = response.json()
    for key in ("period", "total_signals", "total_trades", "win_rate",
                "wins", "losses", "dynamic_threshold"):
        assert key in data, f"Falta clave '{key}' en la respuesta"


@pytest.mark.asyncio
async def test_stats_endpoint_win_rate_zero_with_no_results(client):
    """Trades sin resultado (pending) no deben afectar el Win Rate."""
    import server
    server.app.state.use_mongo = False
    now_str = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S") + "Z"
    server.app.state.signals_store = []
    server.app.state.trades_store = [
        {"symbol": "OTC_EURUSD", "result": "pending", "created_at": now_str},
        {"symbol": "OTC_EURUSD", "result": "pending", "created_at": now_str},
    ]

    response = client.get("/api/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["win_rate"] == 0.0
    assert data["wins"] == 0


@pytest.mark.asyncio
async def test_stats_endpoint_accepts_unknown_params(client):
    """El endpoint debe responder 200 aunque se pasen parámetros desconocidos."""
    import server
    server.app.state.trades_store  = []
    server.app.state.signals_store = []

    response = client.get("/api/stats?window=99h&foo=bar")
    assert response.status_code == 200


# ── Endpoint /api/stats/win-rate ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_win_rate_endpoint_no_crash(client):
    """GET /api/stats/win-rate no debe crashear (hour_bucket/day_bucket con datetime)."""
    import server
    server.app.state.use_mongo = False
    server.app.state.redis = None  # forzar rama computed sin mock async de Redis
    server.app.state.trades_store = []
    server.app.state.signals_store = []

    response = client.get("/api/stats/win-rate")
    assert response.status_code == 200
    data = response.json()
    assert "hourly" in data
    assert "daily" in data
    assert data["source"] == "computed"
    assert "win_rate" in data["hourly"]
    assert "win_rate" in data["daily"]
