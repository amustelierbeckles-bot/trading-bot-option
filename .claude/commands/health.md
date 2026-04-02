# /health — Health check del bot en producción

Ejecuta y diagnostica el estado del trading bot en VPS.

## 1. Obtener health

```bash
curl -s http://67.205.165.201:8000/api/health | python3 -m json.tool
```

## 2. Interpretar campos clave

| Campo | Valor esperado | Si falla |
|-------|---------------|----------|
| `po_websocket.connected` | `true` | Revisar proxy y auth en logs |
| `po_websocket.ready_pairs` | `> 0` (en horario 09:30–00:00 UTC-4) | Ticks no llegan — ver logs binarios |
| `po_websocket.last_tick_age` | `< 30s` | Buffer vacío — sin feed de precios |
| `circuit_breaker.state` | `"open"` | Bloqueado por pérdidas — ver `cb:state` en Redis |
| `auto_execute` | `true` | Variable no seteada en .env.production |

## 3. Si ready_pairs = 0

Revisar logs del contenedor:
```bash
ssh -i C:/Users/muste/.ssh/trading_bot_key root@67.205.165.201
docker logs trading-bot-api --tail 50
```

Buscar:
- `updateAssets` → auth confirmado ✅
- `successauth` → auth confirmado ✅
- `1005` → error suscripción, posible IP bloqueada
- Loop reconexión → proxy caído o SSID expirado

## 4. Circuit Breaker bloqueado

```bash
docker exec trading-bot-redis redis-cli GET cb:state
docker exec trading-bot-redis redis-cli DEL cb:state   # solo si autorizado por usuario
```

## 5. Ventana operativa

El bot solo ejecuta trades entre 09:30 y 00:00 UTC-4.
`ready_pairs = 0` fuera de este horario es **comportamiento normal**.
