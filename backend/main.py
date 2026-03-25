"""
main.py — Trading Bot Backend v3.0
Reemplaza completamente server.py (3,680 líneas → módulos separados)

Arquitectura:
  models/schemas.py              → Modelos Pydantic
  core/strategies/base.py        → 5 estrategias de trading
  core/ensemble.py               → MultiStrategyEnsemble
  core/risk_manager.py           → Circuit Breaker, Martingala, Correlación
  services/telegram_service.py   → Servicio Telegram completo
  api/routes/signals.py          → GET/POST /api/signals/*, /api/strategies/*
  api/routes/trades.py           → /api/trades/*, /api/backtest, /api/calibration
  api/routes/risk.py             → /api/risk/*, /api/antifragile/*
"""

import os
import asyncio
import logging
import math
import random
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from pathlib import Path

from fastapi import FastAPI, Request, Response, Header, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from data_provider import (
    IndicatorSet, init_provider, get_provider,
    get_simulated_indicators, OTC_TO_TWELVE,
)

from models.schemas import SignalScanRequest, TradeResultModel, BacktestRequest, RiskStatusRequest
from core.strategies.base import (
    KeltnerRSIStrategy, CCIAlligatorStrategy, RSIBollingerStrategy,
    MACDStochasticStrategy, EMACrossoverStrategy,
)
from core.ensemble import MultiStrategyEnsemble
from core.risk_manager import (
    check_correlation_lock, update_correlation_lock,
    soft_martingale_next_bet, check_circuit_breaker,
    calc_streak, evaluate_timeframe, get_session_trades,
    pair_win_rate_last_30min, _try_parse_ts,
    _martingale_state, _correlation_locks, _timeframe_overrides,
)
from services.telegram_service import (
    send_telegram, send_signal_telegram, send_pre_alert_telegram,
    telegram_polling_loop,
)
from api.routes import signals as signals_router
from api.routes import trades  as trades_router
from api.routes import risk    as risk_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================================
# PRECIOS BASE
# ============================================================================

ASSET_PRICES: Dict[str, float] = {
    "OTC_EURUSD": 1.0823, "OTC_GBPUSD": 1.2654, "OTC_USDJPY": 150.12,
    "OTC_USDCHF": 0.8823, "OTC_AUDUSD": 0.6523, "OTC_USDCAD": 1.3512,
    "OTC_NZDUSD": 0.5912, "OTC_EURJPY": 162.45, "OTC_EURGBP": 0.8556,
    "OTC_EURAUD": 1.6589, "OTC_EURCAD": 1.4623, "OTC_EURCHF": 0.9545,
    "OTC_GBPJPY": 189.90, "OTC_GBPAUD": 1.9398, "OTC_GBPCAD": 1.7098,
    "OTC_GBPCHF": 1.1162, "OTC_AUDJPY": 97.90,  "OTC_AUDCAD": 0.8812,
    "OTC_CADJPY": 111.09, "OTC_CHFJPY": 170.16,
}
_price_state: Dict[str, Dict] = {}


def get_asset_price(symbol: str) -> float:
    base  = ASSET_PRICES.get(symbol, 1.0000)
    state = _price_state.get(symbol)
    if not state:
        state = {"price": base, "momentum": 0.0, "ticks": 0}
        _price_state[symbol] = state
    drift    = (base - state["price"]) * 0.003
    noise    = random.gauss(0, base * 0.0003)
    momentum = state["momentum"] * 0.85 + drift + noise
    state["price"]    = round(state["price"] + momentum, 5)
    state["momentum"] = momentum
    state["ticks"]   += 1
    return state["price"]


def get_price_trend(symbol: str, ind: Optional[IndicatorSet] = None) -> str:
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
    clean       = symbol.replace("OTC_", "").replace("_", "")
    asset_param = f"{clean}-OTC" if "OTC" in symbol else clean
    return f"https://pocketoption.com/en/quick-trading/?asset={asset_param}"


# ============================================================================
# QUALITY SCORE & HELPERS
# ============================================================================

def _cci_sigmoid(cci_abs: float) -> float:
    return 1.0 - math.exp(-cci_abs / 200.0)


def _quality_score(signal: dict, symbol: str = None,
                   ind: Optional[IndicatorSet] = None) -> float:
    confidence  = signal.get("confidence", 0)
    cci_abs     = abs(signal.get("cci", 0))
    n_agreeing  = len(signal.get("strategies_agreeing", []))
    n_total     = signal.get("n_total", max(n_agreeing, 1))
    signal_type = signal.get("type", "")

    confluence = n_agreeing / 5.0
    cci_factor = _cci_sigmoid(cci_abs)
    consensus  = 1.0 if n_agreeing == n_total else 0.0

    trend_score = 0.5
    if symbol or ind:
        trend = get_price_trend(symbol, ind)
        if   trend == "bullish" and signal_type == "CALL":  trend_score = 1.0
        elif trend == "bearish" and signal_type == "PUT":   trend_score = 1.0
        elif trend == "bullish" and signal_type == "PUT":   trend_score = 0.15
        elif trend == "bearish" and signal_type == "CALL":  trend_score = 0.15

    real_bonus = 0.05 if (ind and ind.is_real) else 0.0
    return round(
        confluence  * 0.30 + confidence  * 0.30 +
        cci_factor  * 0.15 + trend_score * 0.15 +
        consensus   * 0.10 + real_bonus, 4,
    )


from utils import _parse_naive_utc


def _get_market_session(utc_hour: int, utc_minute: int = 0) -> dict:
    utc5_total = (utc_hour * 60 + utc_minute) - 300
    if utc5_total < 0:
        utc5_total += 1440
    utc5_hour = utc5_total // 60
    utc5_min  = utc5_total % 60
    t = utc5_total

    MORNING_START, MORNING_END = 9 * 60 + 30, 12 * 60
    NIGHT_START,   NIGHT_END   = 0, 2 * 60

    ALL_20_PAIRS = [
        "OTC_EURUSD", "OTC_GBPUSD", "OTC_USDJPY", "OTC_USDCHF",
        "OTC_AUDUSD", "OTC_NZDUSD", "OTC_USDCAD", "OTC_EURJPY",
        "OTC_EURGBP", "OTC_EURAUD", "OTC_EURCAD", "OTC_EURCHF",
        "OTC_GBPJPY", "OTC_GBPAUD", "OTC_GBPCAD", "OTC_GBPCHF",
        "OTC_AUDJPY", "OTC_AUDCAD", "OTC_CADJPY", "OTC_CHFJPY",
    ]

    if MORNING_START <= t < MORNING_END:
        return {"name": "Mañana (09:30–12:00)", "active": True, "quality_boost": 0.06,
                "pairs": ALL_20_PAIRS, "description": "Ventana mañana — Londres+NY, 20 pares activos",
                "utc5_display": f"{utc5_hour:02d}:{utc5_min:02d} UTC-5"}
    if NIGHT_START <= t < NIGHT_END:
        return {"name": "Madrugada (00:00–02:00)", "active": True, "quality_boost": 0.03,
                "pairs": ALL_20_PAIRS, "description": "Ventana madrugada — sesión Asiática, 20 pares activos",
                "utc5_display": f"{utc5_hour:02d}:{utc5_min:02d} UTC-5"}

    if t < NIGHT_END:       mins_next, next_w = NIGHT_END - t,     "02:00 (fin madrugada)"
    elif t < MORNING_START: mins_next, next_w = MORNING_START - t, "09:30 (mañana)"
    else:                   mins_next, next_w = (1440 - t),        "00:00 (madrugada)"

    return {"name": "Fuera de ventana", "active": False, "quality_boost": 0.0, "pairs": [],
            "description": (f"Bot pausado — próxima ventana: {next_w} UTC-5 "
                            f"(en ~{mins_next} min) · 0 créditos consumidos"),
            "utc5_display": f"{utc5_hour:02d}:{utc5_min:02d} UTC-5"}


# ============================================================================
# SECURITY MIDDLEWARE
# ============================================================================

class RateLimiter:
    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests   = max_requests
        self.window_seconds = window_seconds
        self._requests: Dict = {}

    def is_allowed(self, key: str) -> bool:
        now     = time.time()
        history = [t for t in self._requests.get(key, []) if now - t < self.window_seconds]
        if len(history) >= self.max_requests:
            return False
        history.append(now)
        self._requests[key] = history
        return True


public_limiter = RateLimiter(max_requests=30, window_seconds=60)
scan_limiter   = RateLimiter(max_requests=10, window_seconds=60)
trade_limiter  = RateLimiter(max_requests=20, window_seconds=60)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"]        = "DENY"
        response.headers["X-XSS-Protection"]       = "1; mode=block"
        response.headers["Referrer-Policy"]         = "strict-origin-when-cross-origin"
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path      = request.url.path
        client_ip = request.client.host if request.client else "unknown"
        limiter   = scan_limiter if "/scan" in path else (trade_limiter if "/trades" in path else public_limiter)
        if not limiter.is_allowed(client_ip):
            return Response(content='{"detail":"Rate limit exceeded."}',
                            status_code=429, media_type="application/json")
        return await call_next(request)


async def verify_api_key(x_api_key: Optional[str] = Header(None, alias="X-API-Key")) -> bool:
    api_key = os.getenv("API_KEY", "")
    if not api_key:
        return True
    if not x_api_key or x_api_key != api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return True


# ============================================================================
# AUTO-SCAN LOOP
# ============================================================================

_dynamic_min_quality:    float = 0.55
_MIN_TRADES_TO_CALIBRATE: int  = 15


async def _auto_scan_loop(app: FastAPI):
    """Motor de escaneo PARALELO v3.0"""
    INTERVAL         = 120
    MIN_CONFIDENCE   = 0.68
    MIN_QUALITY_BASE = 0.55
    MAX_PER_CYCLE    = 2
    COOLDOWN_SECONDS = 240
    MAX_STORE        = 20

    DEFAULT_PAIRS = [
        "OTC_EURUSD", "OTC_GBPUSD", "OTC_USDJPY", "OTC_USDCHF",
        "OTC_AUDUSD", "OTC_NZDUSD", "OTC_USDCAD", "OTC_EURJPY",
        "OTC_EURGBP", "OTC_EURAUD", "OTC_EURCAD", "OTC_EURCHF",
        "OTC_GBPJPY", "OTC_GBPAUD", "OTC_GBPCAD", "OTC_GBPCHF",
        "OTC_AUDJPY", "OTC_AUDCAD", "OTC_CADJPY", "OTC_CHFJPY",
    ]

    cooldown_map       = {}
    _calibration_cycle = 0
    await asyncio.sleep(5)
    logger.info("🚀 Auto-scan PARALELO v3.0 iniciado — %ds ciclo", INTERVAL)

    while True:
        cycle_start = datetime.utcnow()
        try:
            global _dynamic_min_quality
            ensemble  = app.state.ensemble
            store     = app.state.signals_store
            use_mongo = app.state.use_mongo
            db        = app.state.db
            now       = cycle_start

            # Auto-calibración cada 10 ciclos (~20 min)
            _calibration_cycle += 1
            if _calibration_cycle % 10 == 0:
                try:
                    from api.routes.trades import _compute_optimal_threshold
                    all_trades = []
                    if use_mongo:
                        cursor = db.trades.find()
                        all_trades = await cursor.to_list(2000)
                        for t in all_trades:
                            t["id"] = str(t.pop("_id", ""))
                            if isinstance(t.get("created_at"), datetime):
                                t["created_at"] = t["created_at"].strftime("%Y-%m-%dT%H:%M:%S") + "Z"
                    else:
                        all_trades = list(app.state.trades_store)

                    if len(all_trades) >= _MIN_TRADES_TO_CALIBRATE:
                        cal = _compute_optimal_threshold(all_trades)
                        if cal["calibrated"]:
                            _dynamic_min_quality = max(0.45, min(0.85, cal["optimal_threshold"]))
                            logger.info("🎯 Auto-calibración | Umbral → %.2f", _dynamic_min_quality)
                except Exception as cal_err:
                    logger.warning("⚠️  Error en auto-calibración: %s", cal_err)

            # Ajuste de umbral por rendimiento de la hora actual
            effective_base = _dynamic_min_quality
            try:
                all_t_h = list(app.state.trades_store) if not use_mongo else []
                if use_mongo:
                    cursor_h = db.trades.find()
                    all_t_h  = await cursor_h.to_list(1000)
                    for t in all_t_h:
                        if isinstance(t.get("created_at"), datetime):
                            t["created_at"] = t["created_at"].strftime("%Y-%m-%dT%H:%M:%S") + "Z"
                hour_trades = [t for t in all_t_h
                               if _try_parse_ts(t.get("signal_timestamp") or t.get("created_at", "")).hour == now.hour]
                if len(hour_trades) >= 10:
                    hw      = sum(1 for t in hour_trades if t.get("result") == "win")
                    hour_wr = hw / len(hour_trades)
                    if hour_wr >= 0.65:
                        effective_base = max(0.45, effective_base - 0.05)
                    elif hour_wr < 0.45:
                        effective_base = min(0.80, effective_base + 0.07)
            except Exception:
                pass

            session       = _get_market_session(now.hour, now.minute)
            QUALITY_PAIRS = session["pairs"] if session["pairs"] else DEFAULT_PAIRS
            MIN_QUALITY   = effective_base - session["quality_boost"]

            if not session["active"]:
                logger.info("🌙 [%s] %s — sin escaneo.", session["name"], session["description"])
                await asyncio.sleep(INTERVAL)
                continue

            pairs_to_scan = []
            for symbol in QUALITY_PAIRS:
                last_entry = cooldown_map.get(symbol)
                if last_entry:
                    last_time, last_score = last_entry
                    adaptive_cd = COOLDOWN_SECONDS if last_score < 0.65 else 120
                    if (now - last_time).total_seconds() < adaptive_cd:
                        continue
                lock = check_correlation_lock(symbol)
                if lock["locked"]:
                    continue
                pairs_to_scan.append(symbol)

            if not pairs_to_scan:
                logger.info("⏳ Todos los pares en cooldown.")
                await asyncio.sleep(INTERVAL)
                continue

            # Fetch paralelo
            fetch_start = datetime.utcnow()
            provider    = get_provider()
            if provider and provider.is_configured:
                indicators_map = await provider.get_indicators_batch(pairs_to_scan)
            else:
                indicators_map = {sym: get_simulated_indicators(sym) for sym in pairs_to_scan}
            fetch_elapsed = (datetime.utcnow() - fetch_start).total_seconds()

            real_count = sum(1 for s in pairs_to_scan if indicators_map.get(s) and indicators_map[s].is_real)
            if real_count == 0:
                now_ts        = datetime.utcnow()
                last_sim_warn = getattr(app.state, "_last_sim_warn", None)
                if not last_sim_warn or (now_ts - last_sim_warn).total_seconds() > 1800:
                    app.state._last_sim_warn = now_ts
                    asyncio.create_task(send_telegram(
                        "⚠️ <b>ATENCIÓN: Bot en modo simulado</b>\n\n"
                        "🚫 <b>Las señales están SUSPENDIDAS</b> hasta que se renueven los créditos API.\n"
                        "<i>No ejecutes operaciones hasta ver: ✅ API real activa.</i>"
                    ))
            elif real_count > 0 and getattr(app.state, "_last_sim_warn", None):
                app.state._last_sim_warn = None
                asyncio.create_task(send_telegram(
                    f"✅ <b>API real activa</b> — {real_count}/{len(pairs_to_scan)} pares con datos reales."
                ))

            candidates = []
            for symbol in pairs_to_scan:
                ind = indicators_map.get(symbol) or get_simulated_indicators(symbol)
                if not ind.is_real:
                    continue
                if ind.atr_pct > 0:
                    atr_threshold = 0.015 if session["name"] in ("Londres", "Londres+NY") else 0.010
                    if ind.atr_pct < atr_threshold:
                        continue

                signal = ensemble.get_consensus_signal(ind)
                if not signal:
                    pre = ensemble.get_pre_alert_signal(ind)
                    if pre:
                        pre_doc = {
                            "symbol":           symbol, "asset_name": get_asset_name(symbol),
                            "type":             pre["type"], "confluence_pct": pre["confluence_pct"],
                            "strategies_fired": pre["strategies_fired"], "confidence": pre["confidence"],
                            "cci":              pre["cci"], "reason": pre["reason"],
                            "session":          session["name"],
                            "timestamp":        now.strftime("%Y-%m-%dT%H:%M:%S") + "Z",
                            "created_at":       now.strftime("%Y-%m-%dT%H:%M:%S") + "Z",
                            "atr_pct":          round(ind.atr_pct, 4),
                        }
                        app.state.pre_alerts_store[symbol] = pre_doc
                        asyncio.create_task(send_pre_alert_telegram(pre_doc))
                    else:
                        app.state.pre_alerts_store.pop(symbol, None)
                    continue

                if signal["confidence"] < MIN_CONFIDENCE:
                    continue
                score = _quality_score(signal, symbol, ind)
                if score < MIN_QUALITY:
                    continue
                candidates.append((score, symbol, signal, ind))

            candidates.sort(key=lambda x: x[0], reverse=True)
            top           = candidates[:MAX_PER_CYCLE]
            cycle_elapsed = (datetime.utcnow() - cycle_start).total_seconds()

            for score, symbol, signal, ind in top:
                price     = ind.price if ind.is_real else get_asset_price(symbol)
                emit_time = datetime.utcnow()
                ts        = emit_time.strftime("%Y-%m-%dT%H:%M:%S") + "Z"

                data_freshness_ms = None
                if ind.is_real and ind.last_candle_time:
                    try:
                        candle_dt         = datetime.strptime(ind.last_candle_time, "%Y-%m-%d %H:%M:%S")
                        data_freshness_ms = int((emit_time - candle_dt).total_seconds() * 1000)
                    except Exception:
                        pass

                doc = {
                    "id":                  f"{int(emit_time.timestamp()*1000)}_{symbol}",
                    "symbol":              symbol, "asset_name": get_asset_name(symbol),
                    "type":                signal["type"], "price": price, "entry_price": price,
                    "timestamp":           ts, "confidence": signal["confidence"],
                    "cci":                 signal["cci"], "strength": signal["strength"],
                    "strategies_agreeing": signal["strategies_agreeing"],
                    "reason":              signal["reason"], "reasons": signal["reasons"],
                    "consensus_score":     signal["consensus_score"], "quality_score": score,
                    "method":              "quality_scan_parallel",
                    "payout":              round(85.0 + signal["confidence"] * 10, 1),
                    "market_quality":      round(score * 100, 1),
                    "atr":                 round(ind.atr, 6), "atr_pct": round(ind.atr_pct, 4),
                    "session":             session["name"], "active": True, "created_at": ts,
                    "data_freshness_ms":   data_freshness_ms,
                    "scan_elapsed_ms":     round(cycle_elapsed * 1000),
                    "fetch_elapsed_ms":    round(fetch_elapsed * 1000),
                }

                if use_mongo:
                    db_doc = {**doc, "created_at": emit_time}
                    db_doc.pop("id", None)
                    result = await db.signals.insert_one(db_doc)
                    doc["id"] = str(result.inserted_id)
                else:
                    cutoff_dt = emit_time - timedelta(minutes=5)
                    store[:]  = [s for s in store if _parse_naive_utc(s["created_at"]) >= cutoff_dt]
                    if len(store) >= MAX_STORE:
                        store.pop(0)
                    store.append(doc)

                cooldown_map[symbol] = (emit_time, score)
                app.state.pre_alerts_store.pop(symbol, None)
                logger.info("✅ Señal | %s %s | score=%.2f | conf=%.2f | scan=%.1fs",
                            signal["type"], symbol, score, signal["confidence"], cycle_elapsed)

                only_fire = os.getenv("TELEGRAM_ONLY_FIRE", "false").lower() == "true"
                is_fire   = score >= 0.75 or len(signal.get("strategies_agreeing", [])) >= 3
                if not only_fire or is_fire:
                    asyncio.create_task(send_signal_telegram(doc, app))

            if not top:
                logger.info("🔍 Ciclo sin señales (umbral %.2f)", MIN_QUALITY)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("❌ Error en auto-scan: %s", e)

        elapsed = (datetime.utcnow() - cycle_start).total_seconds()
        await asyncio.sleep(max(5.0, INTERVAL - elapsed))


# ============================================================================
# LIFESPAN
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Starting Trading Bot API v3.0...")

    provider = init_provider()
    await provider.start()
    app.state.data_provider = provider
    logger.info("📡 Data provider | modo: %s", "REAL" if provider.is_configured else "SIMULADO")

    mongo_url = os.getenv("MONGO_URL", "mongodb://localhost:27017")
    try:
        client = AsyncIOMotorClient(mongo_url, serverSelectionTimeoutMS=2000)
        await client.server_info()
        app.state.mongodb   = client
        app.state.db        = client[os.getenv("DB_NAME", "trading_bot")]
        app.state.use_mongo = True
        logger.info("✅ MongoDB conectado en %s", mongo_url)
    except Exception as e:
        logger.warning("⚠️  MongoDB no disponible (%s) - usando memoria", e)
        app.state.mongodb = app.state.db = None
        app.state.use_mongo = False

    app.state.signals_store:    list = []
    app.state.trades_store:     list = []
    app.state.pre_alerts_store: dict = {}

    app.state.strategies = {
        "keltner_rsi":     KeltnerRSIStrategy(),
        "cci_alligator":   CCIAlligatorStrategy(),
        "rsi_bollinger":   RSIBollingerStrategy(),
        "macd_stochastic": MACDStochasticStrategy(),
        "ema_crossover":   EMACrossoverStrategy(),
    }
    app.state.ensemble = MultiStrategyEnsemble(list(app.state.strategies.values()))
    logger.info("✅ %d estrategias cargadas", len(app.state.strategies))

    scan_task    = asyncio.create_task(_auto_scan_loop(app))
    polling_task = asyncio.create_task(telegram_polling_loop(app))

    yield

    for task in (scan_task, polling_task):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    logger.info("🛑 Apagando servidor...")
    await provider.stop()
    if app.state.mongodb:
        app.state.mongodb.close()


# ============================================================================
# APP & MIDDLEWARE
# ============================================================================

def _parse_cors_origins() -> list:
    origins_str = os.getenv("CORS_ORIGINS", "http://localhost:3000")
    return [o.strip() for o in origins_str.split(",") if o.strip()]


app = FastAPI(
    title="Trading Bot API",
    description="Multi-Strategy Trading Bot — v3.0",
    version="3.0.0",
    lifespan=lifespan,
)

CORS_ORIGINS = _parse_cors_origins()
app.add_middleware(CORSMiddleware,
    allow_origins=CORS_ORIGINS, allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With", "X-API-Key"],
    max_age=600,
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)

# Registra todos los routers
app.include_router(signals_router.router)
app.include_router(trades_router.router)
app.include_router(risk_router.router)


# ── Endpoints simples de notificaciones ──────────────────────────────────────

@app.post("/api/notifications/test")
async def test_notifications():
    await send_telegram("🧪 Notificación de prueba desde Trading Bot v3.0")
    return {"success": True}


@app.get("/api/notifications/config")
async def get_notifications_config():
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    tg_chat  = os.getenv("TELEGRAM_CHAT_ID", "")
    return {
        "telegram": {
            "enabled":         os.getenv("TELEGRAM_ENABLED", "false").lower() == "true",
            "configured":      bool(tg_token and tg_chat),
            "token_preview":   tg_token[:10] + "..." if tg_token else None,
            "chat_id_preview": tg_chat[:5]  + "..." if tg_chat  else None,
        }
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
