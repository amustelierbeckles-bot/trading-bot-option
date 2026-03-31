# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## What This Project Is

Algorithmic trading bot for binary options (OTC) on PocketOption. Generates signals via an ensemble of 5 technical strategies, executes trades autonomously, audits results in real-time via PocketOption's WebSocket, and tracks Win Rate with circuit breaker protection.

---

## Commands

### Development (Docker)
```bash
docker compose up                          # Start all services (api :8000, frontend :3000, mongo :27017, redis :6379, mongo-express :8081)
docker compose logs -f api                 # Stream backend logs
docker compose exec api pytest tests/     # Run backend tests inside container
```

### Backend (local)
```bash
cd backend
pip install -r requirements.txt
python server.py                           # Runs FastAPI on :8000

pytest tests/                              # All tests
pytest tests/test_po_websocket_pipeline.py # Single test file
pytest tests/ -k "test_circuit_breaker"   # Single test by name
```

### Frontend (local)
```bash
cd frontend
npm install
npm start                                  # CRA dev server on :3000
CI=true npm test                           # Single run (no watch)
```

### Health check
```bash
curl http://localhost:8000/api/health
```
Returns JSON with `po_websocket` status, `ready_pairs`, `last_tick_age`, `connected`.

### Production deploy (on VPS)
```bash
ssh root@67.205.165.201
cd /opt/trading-bot && git pull origin main
docker build --no-cache -t trading-bot-api-img:latest -f backend/Dockerfile backend/
docker stop trading-bot-api && docker rm trading-bot-api
docker compose -f docker-compose.production.yml up -d api
docker logs trading-bot-api --tail 50
```

**Never use `docker compose --force-recreate`** — causes `KeyError: ContainerConfig` on this VPS.

---

## Architecture

```
React Dashboard (localhost:3000)
  └─ Nginx (proxy /api/ → :8000)
       └─ FastAPI Backend (:8000)
            ├─ Signal Engine:      strategies/ (5 classes) + scoring.py + ensemble
            ├─ Auto-Execution:     auto_exec.py (circuit breaker gated, WR filtered)
            ├─ PO WebSocket:       po_websocket.py (20 OTC pairs, Socket.IO v4)
            ├─ Data Provider:      data_provider.py (TwelveData + Redis cache 300s TTL)
            ├─ Audit:              services/audit_service.py (MAE sampling, W/L via PO price)
            └─ Telegram:           services/telegram_service.py (polling + alerts)
       └─ MongoDB (signals, trades, calibration collections)
       └─ Redis (price cache, rate limiting, circuit breaker state)
```

### Key modules

| File | Role |
|------|------|
| `backend/server.py` | FastAPI app factory, lifespan, CORS, router registration |
| `backend/po_websocket.py` | PocketOption Socket.IO v4 connection, 20 OTC pairs, authentication, price buffer |
| `backend/data_provider.py` | TwelveData API, indicator calculation (RSI, CCI, MACD, BB, EMA, ATR), Redis caching |
| `backend/auto_exec.py` | Auto-execution loop, TD fallback queue, MAX_TD_FALLBACK_PER_CYCLE = 5 |
| `backend/strategies/` | Each file exports one class with `.evaluate()` → signal dict |
| `backend/circuit_breaker.py` | Tracks consecutive losses in Redis, blocks execution after threshold |
| `backend/calibration.py` | Adjusts quality_score threshold based on historical WR (high-confidence audits only) |
| `backend/services/audit_service.py` | Verifies trade outcomes using PO WebSocket close price (no API credits spent) |
| `frontend/src/utils/wlHistory.js` | localStorage `wr_history_OTC_{SYMBOL}` — max 20 rolling entries per pair |

### Signal flow
1. `po_websocket.py` streams real-time OTC ticks → in-memory price buffer
2. Auto-scan loop in `auto_exec.py` reads buffer, calls each strategy `.evaluate()`
3. `scoring.py` computes `quality_score` via ensemble weighting
4. If score ≥ calibrated threshold AND WR filter passes AND circuit breaker open → trade placed
5. `audit_service.py` samples PO price at expiry → registers W/L → updates calibration

### Data flow for prices
- **Primary:** PO WebSocket real-time ticks (free, no rate limit)
- **Fallback:** TwelveData API (5000 req/day limit — guarded by `MAX_TD_FALLBACK_PER_CYCLE = 5`)
- **Cache:** Redis 300s TTL per symbol/interval

---

## Critical Constraints

- **`AUTO_EXECUTE`**: Never set to `true` without WR ≥ 55% on 20+ verified operations
- **`ACCOUNT_MODE`**: Must stay `demo` unless explicitly authorized — never flip to `real`
- **`PO_CI_SESSION` / `PO_SSID`**: Tied to VPS IP — doesn't work from local. Renew via `scripts/get_po_session_playwright.py` when WebSocket fails
- **MongoDB `signals` collection**: Never drop — it's the irreplaceable statistical history
- **Healthcheck in Dockerfile**: Use `python urllib.request` — never install `curl`
- **Circuit breaker**: Never disable in production

---

## Code Conventions

**Language:** Comments and logs in Spanish. Code (variables, functions, classes) in English.

```python
# Python
entry_price, quality_score, signal_type   # snake_case variables
MIN_QUALITY, AUTO_EXECUTE_MIN_WR          # UPPER_SNAKE_CASE constants
class CCIAlligatorStrategy:               # Strategy suffix for strategy classes

# Logs use emoji + context
logger.info("✅ MongoDB conectado")
logger.warning("⚠️ Error WebSocket — reintentando")
```

```javascript
// React/JS
fetchAnalytics, tradeAct, selSig          // camelCase
console.log("✓ CALL EURUSD · 78%")
console.error("✗ Error cargando señales")
```

**Commit style:** `tipo: descripción en inglés, imperativo, conciso`
Types: `feat:`, `fix:`, `refactor:`, `chore:`

---

## Environment Variables

Copy `.env.example` for local dev. Production uses `.env.production` on VPS (never committed).

Key variables:

| Variable | Description |
|----------|-------------|
| `AUTO_EXECUTE` | Enables auto-trading — default `false` |
| `AUTO_EXECUTE_MIN_WR` | Minimum WR % required — set to 55 before activating |
| `ACCOUNT_MODE` | `demo` or `real` |
| `PO_CI_SESSION` | PocketOption cookie (IP-locked to VPS) |
| `TWELVE_DATA_API_KEY` | 5000 req/day limit |
| `TELEGRAM_BOT_TOKEN` | Never commit |
| `MONGO_URI` | Internal Docker network only |
| `PO_PROXY_URL` | `socks5://...` residential proxy if IP gets blocked |

---

## Testing

Tests live in `backend/tests/`. Key test files:
- `test_po_websocket_pipeline.py` — WebSocket connection, candle buffer, subscription pipeline
- `test_circuit_breaker.py` — loss streak logic + Redis persistence
- `test_strategies.py` — each strategy's signal generation
- `test_audit.py` — MAE sampling, W/L verification
- `test_api.py` — FastAPI endpoint integration

CI runs `pytest` (backend) and `CI=true npm test` (frontend) on push to main.
Deploy is **manual via SSH** — there is no automatic CD pipeline.

---

## Protocolo del Agente (PO)

### MÓDULOS CRÍTICOS — requieren confirmación explícita antes de modificar
auto_exec.py · circuit_breaker.py · antifragile.py · risk_manager.py

Formato de confirmación requerido:
> Confirmo: modificar [módulo] con modelo [modelo]

Sin esta confirmación el agente NO toca estos archivos.

### PROHIBICIONES
- Declarar resuelto/implementado/listo sin verificación del usuario
- Inventar comportamiento de funciones sin verlo en el código
- Modificar módulos críticos sin confirmación explícita
- Cerrar tarea sin reportar efectos secundarios

### ESTADOS DE TAREA
EN_CURSO → PUSHEADO → PENDIENTE_VERIFICACION → RESUELTO
Solo el usuario marca RESUELTO. El agente nunca declara RESUELTO unilateralmente.

### VERIFICACIÓN ANTES DE CERRAR TAREA
- ¿El cambio hace exactamente lo que se pidió?
- ¿Efectos secundarios en otros módulos?
- ¿Tests en verde?
- ¿Funciona con MongoDB, Redis, WebSocket en contexto real?
- ¿Podría romper algo que funcionaba?

### PATRONES DE ERROR CONOCIDOS
- scan=0.0s → buffers vacíos, sin ticks reales
- Loop reconexión cada ~2min → SSID expirado o IP bloqueada
- Score/CCI congelado → datos no actualizados en buffer
- WR siempre 0% → trades en colección equivocada (signals vs trades)
- Auth no enviado → guard incorrecto en _handle_handshake
- AUTO_EXECUTE ausente en .env.production → bot nunca ejecuta
- SSID URL-encoded sin decodificar → PO acepta conexión pero no envía ticks
- Condición de carrera auth/suscripción → suscribir pares antes de confirmar auth

### CONTEXTO DE PRODUCCIÓN
- VPS: DigitalOcean · Ubuntu · Docker Compose V2
- Proxy: SOCKS5 residencial (Webshare) — variable PO_PROXY_URL
- Redis key del Circuit Breaker: cb:state (no circuit_breaker:state)
- Repo GitHub: amustelierbeckles-bot/trading-bot-option
- Inicio del proyecto: 5 febrero 2026 (Emergent) · 5 marzo 2026 (GitHub)
