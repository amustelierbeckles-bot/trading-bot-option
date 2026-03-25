"""
api/routes/signals.py
Endpoints de señales — extraídos de server.py
  GET  /api/health
  GET  /api/strategies
  POST /api/strategies/{id}/toggle
  POST /api/signals/scan
  GET  /api/signals/active
  GET  /api/signals/stats
  GET  /api/data-provider/status
  GET  /api/assets
  GET  /api/market-data/{symbol}
  GET  /api/pre-alerts/active
  GET  /api/signals/pre-alerts
"""
import os
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Request, Depends, HTTPException

from models.schemas import SignalScanRequest
from core.risk_manager import check_correlation_lock
from services.telegram_service import send_signal_telegram

logger = logging.getLogger(__name__)
router = APIRouter()


from utils import _parse_naive_utc


# ── Helpers importados del contexto global (se inyectan desde main.py) ────────
def _get_helpers():
    """Importa helpers del módulo legado para no duplicar código."""
    from main import get_asset_price, get_asset_name, generate_pocket_option_url, _quality_score, _get_market_session
    return get_asset_price, get_asset_name, generate_pocket_option_url, _quality_score, _get_market_session


@router.get("/")
async def root(request: Request):
    return {
        "name":       "Trading Bot API",
        "version":    "3.0.0",
        "status":     "online",
        "strategies": len(request.app.state.strategies),
    }


@router.get("/api/health")
async def health_check(request: Request):
    _, _, _, _, _get_market_session = _get_helpers()
    now     = datetime.utcnow()
    session = _get_market_session(now.hour, now.minute)
    return {
        "status":               "healthy",
        "timestamp":            now.isoformat(),
        "strategies_loaded":    len(request.app.state.strategies),
        "market_session":       session["name"],
        "session_active":       session["active"],
        "session_description":  session["description"],
        "session_pairs":        len(session["pairs"]),
    }


@router.get("/api/strategies")
async def get_strategies(request: Request):
    strategies = request.app.state.strategies
    strategy_info = [
        {"id": "keltner_rsi",     "name": "Keltner Channel + RSI",    "timeframe": "15s - 1m",  "win_rate_expected": "70-75%", "signals_per_day": "15-25", "enabled": strategies["keltner_rsi"].enabled,     "weight": strategies["keltner_rsi"].weight},
        {"id": "cci_alligator",   "name": "CCI + Alligator",          "timeframe": "1m - 5m",   "win_rate_expected": "60-65%", "signals_per_day": "5-8",   "enabled": strategies["cci_alligator"].enabled,   "weight": strategies["cci_alligator"].weight},
        {"id": "rsi_bollinger",   "name": "RSI + Bollinger Bands",    "timeframe": "1m - 5m",   "win_rate_expected": "65-70%", "signals_per_day": "8-12",  "enabled": strategies["rsi_bollinger"].enabled,   "weight": strategies["rsi_bollinger"].weight},
        {"id": "macd_stochastic", "name": "MACD + Stochastic",        "timeframe": "5m - 15m",  "win_rate_expected": "60-68%", "signals_per_day": "4-7",   "enabled": strategies["macd_stochastic"].enabled, "weight": strategies["macd_stochastic"].weight},
        {"id": "ema_crossover",   "name": "EMA Crossover",            "timeframe": "5m - 15m",  "win_rate_expected": "55-60%", "signals_per_day": "3-5",   "enabled": strategies["ema_crossover"].enabled,   "weight": strategies["ema_crossover"].weight},
        {"id": "ensemble",        "name": "Multi-Strategy Ensemble",  "timeframe": "Any",        "win_rate_expected": "75-80%", "signals_per_day": "10-15", "enabled": True,                                  "weight": 1.5},
    ]
    return {"strategies": strategy_info}


@router.post("/api/strategies/{strategy_id}/toggle")
async def toggle_strategy(strategy_id: str, request: Request):
    strategies = request.app.state.strategies
    if strategy_id not in strategies:
        raise HTTPException(status_code=404, detail="Strategy not found")
    strategy = strategies[strategy_id]
    strategy.enabled = not strategy.enabled
    return {"strategy_id": strategy_id, "enabled": strategy.enabled}


@router.post("/api/signals/scan")
async def scan_signals(scan_request: SignalScanRequest, request: Request):
    get_asset_price, get_asset_name, generate_pocket_option_url, _quality_score, _ = _get_helpers()
    ensemble    = request.app.state.ensemble
    use_mongo   = request.app.state.use_mongo
    db          = request.app.state.db
    store       = request.app.state.signals_store
    all_signals = []

    for symbol in scan_request.symbols:
        signal = ensemble.get_consensus_signal()
        score  = _quality_score(signal, symbol) if signal else 0

        if signal and signal["confidence"] >= scan_request.min_confidence and score >= 0.68:
            price = get_asset_price(symbol)
            now   = datetime.utcnow()

            signal_doc = {
                "id":                  str(int(now.timestamp() * 1000)) + "_" + symbol,
                "symbol":              symbol,
                "asset_name":          get_asset_name(symbol),
                "type":                signal["type"],
                "price":               price,
                "entry_price":         price,
                "timestamp":           now.strftime("%Y-%m-%dT%H:%M:%S") + "Z",
                "confidence":          signal["confidence"],
                "cci":                 signal["cci"],
                "strength":            signal["strength"],
                "strategies_agreeing": signal["strategies_agreeing"],
                "reason":              signal["reason"],
                "reasons":             signal["reasons"],
                "consensus_score":     signal["consensus_score"],
                "method":              "ensemble",
                "payout":              round(85.0 + signal["confidence"] * 10, 1),
                "market_quality":      round(signal["consensus_score"] * 100, 1),
                "active":              True,
                "pocket_option_url":   generate_pocket_option_url(symbol),
                "created_at":          now.strftime("%Y-%m-%dT%H:%M:%S") + "Z",
            }

            if use_mongo:
                doc_for_db = {**signal_doc, "created_at": now}
                doc_for_db.pop("id", None)
                result = await db.signals.insert_one(doc_for_db)
                signal_doc["id"] = str(result.inserted_id)
            else:
                store.append(signal_doc)
                if len(store) > 200:
                    store.pop(0)
            all_signals.append(signal_doc)

            only_fire = os.getenv("TELEGRAM_ONLY_FIRE", "false").lower() == "true"
            is_fire   = score >= 0.75 or len(signal.get("strategies_agreeing", [])) >= 3
            if not only_fire or is_fire:
                asyncio.create_task(send_signal_telegram(signal_doc, request.app))

    return {"success": True, "new_signals": len(all_signals), "signals": all_signals}


@router.get("/api/signals/active")
async def get_active_signals(request: Request):
    use_mongo = request.app.state.use_mongo
    now       = datetime.utcnow()
    cutoff    = now - timedelta(minutes=30)
    trade_ttl = timedelta(seconds=120)

    if use_mongo:
        cursor  = request.app.state.db.signals.find(
            {"created_at": {"$gte": cutoff}}
        ).sort("created_at", -1).limit(200)
        signals = await cursor.to_list(200)
        for s in signals:
            s["id"] = str(s["_id"])
            del s["_id"]
            created = s.get("created_at")
            if isinstance(created, datetime):
                s["active"]     = (now - created.replace(tzinfo=None)) <= trade_ttl
                s["created_at"] = created.strftime("%Y-%m-%dT%H:%M:%S") + "Z"
            else:
                s.setdefault("active", True)
    else:
        raw = []
        for s in request.app.state.signals_store:
            try:
                created = _parse_naive_utc(s["created_at"])
                if created >= cutoff:
                    age = now - created
                    raw.append({**s, "active": age <= trade_ttl})
            except Exception:
                continue
        signals = list(reversed(raw))[:200]

    return {"signals": signals, "count": len(signals)}


@router.get("/api/signals/stats")
async def get_signals_stats(request: Request):
    cutoff = datetime.utcnow() - timedelta(days=7)
    if request.app.state.use_mongo:
        total = await request.app.state.db.signals.count_documents(
            {"created_at": {"$gte": cutoff}}
        )
    else:
        total = sum(
            1 for s in request.app.state.signals_store
            if _parse_naive_utc(s["created_at"]) >= cutoff
        )
    return {"period": "7 days", "total_signals": total}


@router.get("/api/data-provider/status")
async def data_provider_status(request: Request):
    provider = request.app.state.data_provider
    return {
        "status": "real" if provider.is_configured else "simulated",
        **provider.stats(),
        "message": (
            "Datos de mercado REALES activos (Twelve Data)"
            if provider.is_configured
            else "Modo simulado activo. Configura TWELVE_DATA_API_KEY para datos reales."
        ),
    }


@router.get("/api/assets")
async def get_assets():
    return [
        {"id": "1",  "symbol": "OTC_EURUSD", "name": "EUR/USD OTC", "type": "forex", "current_price": 1.0823, "price_change_24h": 0.12,  "active": True},
        {"id": "2",  "symbol": "OTC_GBPUSD", "name": "GBP/USD OTC", "type": "forex", "current_price": 1.2654, "price_change_24h": 0.08,  "active": True},
        {"id": "3",  "symbol": "OTC_USDJPY", "name": "USD/JPY OTC", "type": "forex", "current_price": 150.12, "price_change_24h": -0.15, "active": True},
        {"id": "4",  "symbol": "OTC_USDCHF", "name": "USD/CHF OTC", "type": "forex", "current_price": 0.8823, "price_change_24h": -0.05, "active": True},
        {"id": "5",  "symbol": "OTC_AUDUSD", "name": "AUD/USD OTC", "type": "forex", "current_price": 0.6523, "price_change_24h": 0.05,  "active": True},
        {"id": "6",  "symbol": "OTC_USDCAD", "name": "USD/CAD OTC", "type": "forex", "current_price": 1.3512, "price_change_24h": -0.08, "active": True},
        {"id": "7",  "symbol": "OTC_NZDUSD", "name": "NZD/USD OTC", "type": "forex", "current_price": 0.5912, "price_change_24h": 0.03,  "active": True},
        {"id": "8",  "symbol": "OTC_EURJPY", "name": "EUR/JPY OTC", "type": "forex", "current_price": 162.45, "price_change_24h": -0.23, "active": True},
        {"id": "9",  "symbol": "OTC_EURGBP", "name": "EUR/GBP OTC", "type": "forex", "current_price": 0.8556, "price_change_24h": 0.04,  "active": True},
        {"id": "10", "symbol": "OTC_EURAUD", "name": "EUR/AUD OTC", "type": "forex", "current_price": 1.6589, "price_change_24h": 0.07,  "active": True},
        {"id": "11", "symbol": "OTC_EURCAD", "name": "EUR/CAD OTC", "type": "forex", "current_price": 1.4623, "price_change_24h": 0.04,  "active": True},
        {"id": "12", "symbol": "OTC_EURCHF", "name": "EUR/CHF OTC", "type": "forex", "current_price": 0.9545, "price_change_24h": 0.17,  "active": True},
        {"id": "13", "symbol": "OTC_GBPJPY", "name": "GBP/JPY OTC", "type": "forex", "current_price": 189.90, "price_change_24h": -0.07, "active": True},
        {"id": "14", "symbol": "OTC_GBPAUD", "name": "GBP/AUD OTC", "type": "forex", "current_price": 1.9398, "price_change_24h": 0.03,  "active": True},
        {"id": "15", "symbol": "OTC_GBPCAD", "name": "GBP/CAD OTC", "type": "forex", "current_price": 1.7098, "price_change_24h": 0.00,  "active": True},
        {"id": "16", "symbol": "OTC_GBPCHF", "name": "GBP/CHF OTC", "type": "forex", "current_price": 1.1162, "price_change_24h": 0.13,  "active": True},
        {"id": "17", "symbol": "OTC_AUDJPY", "name": "AUD/JPY OTC", "type": "forex", "current_price": 97.90,  "price_change_24h": -0.20, "active": True},
        {"id": "18", "symbol": "OTC_AUDCAD", "name": "AUD/CAD OTC", "type": "forex", "current_price": 0.8812, "price_change_24h": -0.03, "active": True},
        {"id": "19", "symbol": "OTC_CADJPY", "name": "CAD/JPY OTC", "type": "forex", "current_price": 111.09, "price_change_24h": -0.07, "active": True},
        {"id": "20", "symbol": "OTC_CHFJPY", "name": "CHF/JPY OTC", "type": "forex", "current_price": 170.16, "price_change_24h": -0.10, "active": True},
    ]


@router.get("/api/market-data/{symbol}")
async def get_market_data(symbol: str, request: Request):
    provider = request.app.state.data_provider
    ind      = None

    if provider and provider.is_configured:
        cached = provider._cache.get(symbol)
        if cached:
            ind = cached.get("indicators")

    if ind and ind.candles:
        closes = [c.close for c in ind.candles[-20:]]
        price  = ind.price
        change = round(((closes[-1] - closes[0]) / closes[0]) * 100, 4) if closes[0] else 0
        return {"symbol": symbol, "price": price, "change_pct": change,
                "prices": closes, "is_real": True, "source": "cache"}

    from data_provider import simulate_candles
    candles = simulate_candles(symbol, count=20)
    closes  = [c.close for c in candles]
    price   = closes[-1] if closes else 0
    change  = round(((closes[-1] - closes[0]) / closes[0]) * 100, 4) if closes and closes[0] else 0
    return {"symbol": symbol, "price": price, "change_pct": change,
            "prices": closes, "is_real": False, "source": "simulated"}


@router.get("/api/pre-alerts/active")
@router.get("/api/signals/pre-alerts")
async def get_pre_alerts(request: Request):
    store = request.app.state.pre_alerts_store
    now   = datetime.utcnow()
    cutoff = now - timedelta(minutes=5)

    active = []
    for symbol, doc in list(store.items()):
        try:
            ts = datetime.fromisoformat(doc.get("created_at", "").rstrip("Z"))
            if ts >= cutoff:
                active.append(doc)
            else:
                store.pop(symbol, None)
        except Exception:
            active.append(doc)

    return {"pre_alerts": active, "count": len(active)}
