"""
Trading Bot Backend v3.0 — Modular Architecture
================================================
Entry point: only app factory + lifespan + middlewares + router registration.

All business logic lives in dedicated modules:
  models.py              — Pydantic schemas
  assets.py              — Asset prices & utilities
  circuit_breaker.py     — Autonomous circuit breaker
  win_rate_cache.py      — Redis/in-memory WR cache
  strategies.py          — Strategy classes & MultiStrategyEnsemble
  scoring.py             — Quality & orthogonal scoring
  market_session.py      — Market session detection
  calibration.py         — Dynamic quality threshold
  antifragile.py         — Martingale, correlation lock, position sizing
  auto_exec.py           — Auto-execution + auto-scan loop
  services/audit_service.py    — Autonomous audit (MAE, verify, register)
  services/telegram_service.py — Telegram bot API helpers & polling
  routes/admin.py        — Health, email test, notifications
  routes/signals.py      — Signal scanning, pre-alerts, backtest
  routes/trades.py       — Trade CRUD & manual execute
  routes/stats.py        — Win-rate, strategy performance, audit stats
  routes/risk.py         — Circuit breaker, antifragile, calibration
"""

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, List

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from starlette.middleware.base import BaseHTTPMiddleware

load_dotenv(Path(__file__).parent.parent / ".env")

try:
    import redis.asyncio as aioredis
    _REDIS_AVAILABLE = True
except ImportError:
    _REDIS_AVAILABLE = False

from data_provider import init_provider
from strategies import (
    RangeBreakoutStrategy, CCIAlligatorStrategy, RSIBollingerStrategy,
    MACDStochasticStrategy, EMACrossoverStrategy, MultiStrategyEnsemble,
)
from auto_exec import _auto_scan_loop
from services.telegram_service import telegram_polling_loop

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================================
# LIFESPAN
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Starting Trading Bot API v3.0 (modular)...")

    # ── Data provider (Twelve Data) ───────────────────────────────────────────
    provider = init_provider()
    await provider.start()
    app.state.data_provider = provider
    logger.info("📡 Data provider | modo: %s",
                "REAL" if provider.is_configured else "SIMULADO")

    # ── MongoDB (opcional) ────────────────────────────────────────────────────
    mongo_url = os.getenv("MONGO_URI", os.getenv("MONGO_URL", "mongodb://localhost:27017"))
    try:
        client = AsyncIOMotorClient(mongo_url, serverSelectionTimeoutMS=2000)
        await client.server_info()
        app.state.mongodb   = client
        app.state.db        = client[os.getenv("DB_NAME", "trading_bot")]
        app.state.use_mongo = True
        logger.info("✅ MongoDB conectado en %s", mongo_url)
    except Exception as e:
        logger.warning("⚠️  MongoDB no disponible (%s) - usando almacenamiento en memoria", e)
        app.state.mongodb   = None
        app.state.db        = None
        app.state.use_mongo = False

    # ── Redis (opcional) ──────────────────────────────────────────────────────
    app.state.redis = None
    if _REDIS_AVAILABLE:
        try:
            r = aioredis.from_url(
                os.getenv("REDIS_URL", "redis://localhost:6379"),
                decode_responses=True, socket_connect_timeout=2,
            )
            await r.ping()
            app.state.redis = r
            logger.info("✅ Redis conectado")
            from circuit_breaker import cb_bind_redis, cb_load_state
            cb_bind_redis(r)
            await cb_load_state(r)
        except Exception as re:
            logger.warning("⚠️  Redis no disponible (%s) — caché in-memory activo", re)

    # ── PocketOption WebSocket ────────────────────────────────────────────────
    po_ssid = os.getenv("PO_SSID", "").strip()
    app.state.po_provider = None
    if po_ssid:
        try:
            from po_websocket import init_po_provider
            is_demo = os.getenv("ACCOUNT_MODE", "demo").lower() == "demo"
            _po_uid_raw = (os.getenv("PO_USER_ID") or "").strip()
            try:
                po_user_id = int(_po_uid_raw) if _po_uid_raw else 0
            except ValueError:
                po_user_id = 0
                logger.warning(
                    "⚠️  PO_USER_ID inválido (%r) — usando 0 (auth WebSocket omitido)",
                    _po_uid_raw,
                )
            po_secret = (os.getenv("PO_SECRET") or "").strip()
            po = init_po_provider(
                ssid=po_ssid,
                is_demo=is_demo,
                user_id=po_user_id,
                secret=po_secret,
            )
            await po.start()
            app.state.po_provider = po
            logger.info("🔌 PO WebSocket iniciado | modo=%s", "DEMO" if is_demo else "REAL")
        except Exception as po_err:
            logger.warning("⚠️  PO WebSocket no disponible: %s", po_err)
    else:
        logger.info("⏭  PO WebSocket desactivado (PO_SSID no configurado)")

    # ── Índices MongoDB ────────────────────────────────────────────────────────
    if app.state.use_mongo:
        try:
            db = app.state.db
            await db.signals.create_index([("symbol", 1), ("hour_bucket", 1), ("result", 1)])
            await db.signals.create_index([("session", 1), ("result", 1), ("created_at", -1)])
            await db.signals.create_index([("day_bucket", 1), ("symbol", 1)])
            await db.signals.create_index([("audit_confidence", 1), ("result", 1)])
            await db.signals.create_index([("created_at", -1)])
            await db.signals.create_index([("execution_mode", 1), ("created_at", -1)])
            await db.trades.create_index([("symbol", 1), ("result", 1), ("created_at", -1)])
            await db.trades.create_index([("signal_id", 1)], unique=True, sparse=True)
            await db.trades.create_index([("audit_confidence", 1), ("result", 1)])
            logger.info("✅ Índices MongoDB creados/verificados")
        except Exception as idx_err:
            logger.warning("⚠️  Error creando índices: %s", idx_err)

    # ── Almacenamiento en memoria (fallback) ───────────────────────────────────
    app.state.signals_store:    list = []
    app.state.trades_store:     list = []
    app.state.pre_alerts_store: dict = {}

    # ── Estrategias y Ensemble ────────────────────────────────────────────────
    app.state.strategies = {
        "range_breakout":  RangeBreakoutStrategy(),
        "cci_alligator":   CCIAlligatorStrategy(),
        "rsi_bollinger":   RSIBollingerStrategy(),
        "macd_stochastic": MACDStochasticStrategy(),
        "ema_crossover":   EMACrossoverStrategy(),
    }
    app.state.ensemble = MultiStrategyEnsemble(list(app.state.strategies.values()))
    logger.info("✅ %d estrategias cargadas", len(app.state.strategies))

    # ── Email Service + APScheduler ───────────────────────────────────────────
    app.state.email_service = None
    app.state.scheduler     = None
    if app.state.use_mongo:
        try:
            from services.email_service import EmailService
            from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]
            from zoneinfo import ZoneInfo

            email_svc = EmailService(app.state.db)
            app.state.email_service = email_svc

            scheduler = AsyncIOScheduler(timezone=ZoneInfo("America/Havana"))
            scheduler.add_job(
                email_svc.send_daily_report,
                trigger="cron", hour=23, minute=0, id="daily_report",
            )
            scheduler.start()
            app.state.scheduler = scheduler
            logger.info("📧 Email scheduler iniciado — reporte diario 11:00 PM")
        except Exception as email_err:
            logger.warning("⚠️  Email service no disponible: %s", email_err)

    # ── Background tasks ──────────────────────────────────────────────────────
    scan_task    = asyncio.create_task(_auto_scan_loop(app))
    polling_task = asyncio.create_task(telegram_polling_loop(app))

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    for task in (scan_task, polling_task):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    logger.info("🛑 Apagando servidor...")
    if app.state.scheduler:
        app.state.scheduler.shutdown(wait=False)
    await provider.stop()
    if app.state.po_provider:
        await app.state.po_provider.stop()
    if app.state.mongodb:
        app.state.mongodb.close()


# ============================================================================
# APP FACTORY
# ============================================================================

app = FastAPI(
    title="Trading Bot API",
    description="Multi-Strategy Trading Bot — Modular v3.0",
    version="3.0.0",
    lifespan=lifespan,
)

# ── CORS ─────────────────────────────────────────────────────────────────────
_cors_origins = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
    if o.strip()
]
logger.info("🔒 CORS origins: %s", _cors_origins)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With", "X-API-Key"],
    max_age=600,
)

# ── Security Headers ──────────────────────────────────────────────────────────

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"]        = "DENY"
        response.headers["X-XSS-Protection"]       = "1; mode=block"
        response.headers["Referrer-Policy"]        = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"]     = "geolocation=(), microphone=(), camera=()"
        try:
            del response.headers["Server"]
        except KeyError:
            pass
        return response


# ── Rate Limiting ─────────────────────────────────────────────────────────────

class _RateLimiter:
    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window       = window_seconds
        self.clients: Dict[str, List[float]] = {}

    def is_allowed(self, client_id: str) -> bool:
        now = time.time()
        self.clients.setdefault(client_id, [])
        self.clients[client_id] = [t for t in self.clients[client_id] if now - t < self.window]
        if len(self.clients[client_id]) >= self.max_requests:
            return False
        self.clients[client_id].append(now)
        return True


_public_limiter = _RateLimiter(30, 60)
_scan_limiter   = _RateLimiter(10, 60)
_trade_limiter  = _RateLimiter(20, 60)


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        path      = request.url.path

        if "/api/signals/scan" in path or "/api/scan" in path:
            limiter = _scan_limiter
        elif "/api/trades" in path:
            limiter = _trade_limiter
        else:
            limiter = _public_limiter

        if not limiter.is_allowed(f"{client_ip}:{path}"):
            return Response(
                content='{"error": "Rate limit exceeded. Please slow down."}',
                status_code=429,
                media_type="application/json",
                headers={"Retry-After": "60"},
            )
        return await call_next(request)


app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)

# ============================================================================
# ROUTERS
# ============================================================================

from routes.admin   import router as admin_router
from routes.signals import router as signals_router
from routes.trades  import router as trades_router
from routes.stats   import router as stats_router
from routes.risk    import router as risk_router

app.include_router(admin_router)
app.include_router(signals_router)
app.include_router(trades_router)
app.include_router(stats_router)
app.include_router(risk_router)

# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
