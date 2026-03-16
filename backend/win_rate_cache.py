"""
Cache de Win Rate con Redis → in-memory fallback.

Clave formato:  "wr:{scope}:{window}"
Ej:  "wr:global:1h"  |  "wr:OTC_EURUSD:1h"  |  "wr:london:session"
TTL: 300 segundos (5 minutos)
"""
import json
import time
from datetime import datetime
from typing import Dict, Optional

_WR_CACHE_TTL = 300   # segundos
_wr_mem_cache: Dict[str, tuple] = {}   # key → (value, expires_at)


async def wr_cache_get(redis, key: str) -> Optional[dict]:
    """Lee Win Rate del caché. Retorna dict o None si expirado/inexistente."""
    try:
        if redis is not None:
            raw = await redis.get(key)
            return json.loads(raw) if raw else None
    except Exception:
        pass
    entry = _wr_mem_cache.get(key)
    if entry and time.time() < entry[1]:
        return entry[0]
    return None


async def wr_cache_set(redis, key: str, value: dict, ttl: int = _WR_CACHE_TTL) -> None:
    """Escribe Win Rate en caché con TTL."""
    try:
        if redis is not None:
            await redis.set(key, json.dumps(value), ex=ttl)
            return
    except Exception:
        pass
    _wr_mem_cache[key] = (value, time.time() + ttl)


async def wr_cache_invalidate(redis, pattern: str) -> None:
    """Invalida todas las claves que empiecen con el patrón dado."""
    try:
        if redis is not None:
            keys = await redis.keys(f"{pattern}*")
            if keys:
                await redis.delete(*keys)
            return
    except Exception:
        pass
    to_del = [k for k in _wr_mem_cache if k.startswith(pattern)]
    for k in to_del:
        _wr_mem_cache.pop(k, None)


def hour_bucket(dt: datetime) -> str:
    """Devuelve 'YYYY-MM-DDTHH' para indexar Win Rate por hora."""
    return dt.strftime("%Y-%m-%dT%H")


def day_bucket(dt: datetime) -> str:
    """Devuelve 'YYYY-MM-DD' para indexar Win Rate por día."""
    return dt.strftime("%Y-%m-%d")
