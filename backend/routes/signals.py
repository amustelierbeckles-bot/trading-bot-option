"""
Routes de señales.

  POST /api/signals/scan
  GET  /api/signals/active
  GET  /api/signals/stats
  GET  /api/pre-alerts/active
  GET  /api/signals/pre-alerts
  GET  /api/strategies
  POST /api/strategies/{id}/toggle
  GET  /api/assets
  GET  /api/market-data/{symbol}
  POST /api/backtest
"""
import asyncio
import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from schemas import SignalScanRequest, BacktestRequest
from assets import get_asset_name, get_asset_price, ASSET_PRICES
from scoring import quality_score as _quality_score
from calibration import get_dynamic_threshold

router = APIRouter()


from utils import _parse_naive_utc


async def _verify_api_key(x_api_key: Optional[str] = Header(None, alias="X-API-Key")):
    import hmac
    current_key = os.getenv("API_SECRET_KEY", None)
    if not current_key:
        return True
    if not x_api_key:
        raise HTTPException(status_code=401, detail="X-API-Key header required")
    if not hmac.compare_digest(x_api_key, current_key):
        raise HTTPException(status_code=403, detail="Invalid API key")
    return True


@router.post("/api/signals/scan")
async def scan_signals(scan_request: SignalScanRequest, request: Request,
                       auth: bool = Depends(_verify_api_key)):
    from data_provider import get_provider, get_simulated_indicators, get_indicators_for
    from assets import generate_pocket_option_url
    from services.telegram_service import send_signal_telegram

    ensemble  = request.app.state.ensemble
    use_mongo = request.app.state.use_mongo
    db        = request.app.state.db
    store     = request.app.state.signals_store
    all_signals = []

    effective_threshold = max(get_dynamic_threshold(), scan_request.min_confidence)

    for symbol in scan_request.symbols:
        try:
            ind = await get_indicators_for(symbol, "1min")
        except Exception:
            ind = get_simulated_indicators(symbol)

        signal = ensemble.get_consensus_signal(ind)
        score  = _quality_score(signal, symbol, ind) if signal else 0

        if not signal or signal["confidence"] < scan_request.min_confidence or score < effective_threshold:
            continue

        price = ind.price if (ind and ind.is_real) else get_asset_price(symbol)
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
            "quality_score":       score,
            "method":              "ensemble",
            "payout":              round(85.0 + signal["confidence"] * 10, 1),
            "market_quality":      round(signal["consensus_score"] * 100, 1),
            "data_source":         "real" if (ind and ind.is_real) else "simulated",
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
        cursor  = request.app.state.db.signals.find({"created_at": {"$gte": cutoff}}).sort("created_at", -1).limit(200)
        signals = await cursor.to_list(200)
        for s in signals:
            s["id"] = str(s["_id"]); del s["_id"]
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
                    raw.append({**s, "active": (now - created) <= trade_ttl})
            except Exception:
                continue
        signals = list(reversed(raw))[:200]

    return {"signals": signals, "count": len(signals)}


@router.get("/api/signals/stats")
async def get_signals_stats(request: Request):
    cutoff = datetime.utcnow() - timedelta(days=7)
    if request.app.state.use_mongo:
        total = await request.app.state.db.signals.count_documents({"created_at": {"$gte": cutoff}})
    else:
        total = sum(1 for s in request.app.state.signals_store
                    if _parse_naive_utc(s["created_at"]) >= cutoff)
    return {"period": "7 days", "total_signals": total}


@router.get("/api/pre-alerts/active")
@router.get("/api/signals/pre-alerts")
async def get_pre_alerts(request: Request):
    now    = datetime.utcnow()
    cutoff = now - timedelta(minutes=5)
    fresh  = {}
    for sym, doc in list(request.app.state.pre_alerts_store.items()):
        try:
            ts = _parse_naive_utc(doc.get("created_at", ""))
            if ts >= cutoff:
                fresh[sym] = doc
            else:
                request.app.state.pre_alerts_store.pop(sym, None)
        except Exception:
            pass
    return {"pre_alerts": fresh, "count": len(fresh)}


@router.get("/api/strategies")
async def get_strategies(request: Request):
    strategies = request.app.state.strategies
    return [
        {"id": "range_breakout",  "name": "Range Breakout + ATR",   "timeframe": "1m - 5m",  "win_rate_expected": "65-72%", "signals_per_day": "8-15",  "enabled": strategies["range_breakout"].enabled,  "weight": strategies["range_breakout"].weight},
        {"id": "cci_alligator",   "name": "CCI + Alligator",        "timeframe": "1m - 5m",  "win_rate_expected": "60-65%", "signals_per_day": "5-8",   "enabled": strategies["cci_alligator"].enabled,   "weight": strategies["cci_alligator"].weight},
        {"id": "rsi_bollinger",   "name": "RSI + Bollinger Bands",  "timeframe": "1m - 5m",  "win_rate_expected": "65-70%", "signals_per_day": "8-12",  "enabled": strategies["rsi_bollinger"].enabled,   "weight": strategies["rsi_bollinger"].weight},
        {"id": "macd_stochastic", "name": "MACD + Stochastic",      "timeframe": "5m - 15m", "win_rate_expected": "60-68%", "signals_per_day": "4-7",   "enabled": strategies["macd_stochastic"].enabled, "weight": strategies["macd_stochastic"].weight},
        {"id": "ema_crossover",   "name": "EMA Crossover",          "timeframe": "5m - 15m", "win_rate_expected": "55-60%", "signals_per_day": "3-5",   "enabled": strategies["ema_crossover"].enabled,   "weight": strategies["ema_crossover"].weight},
    ]


@router.post("/api/strategies/{strategy_id}/toggle")
async def toggle_strategy(strategy_id: str, request: Request):
    strategies = request.app.state.strategies
    if strategy_id not in strategies:
        raise HTTPException(status_code=404, detail="Strategy not found")
    strategies[strategy_id].enabled = not strategies[strategy_id].enabled
    return {"strategy_id": strategy_id, "enabled": strategies[strategy_id].enabled}


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
    """Datos de mercado para el dashboard (sparkline). Solo caché — CERO créditos API."""
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
        return {"symbol": symbol, "price": price, "change_pct": change, "prices": closes,
                "is_real": True, "source": "cache"}

    from data_provider import simulate_candles
    candles = simulate_candles(symbol, count=20)
    closes  = [c.close for c in candles]
    price   = closes[-1] if closes else 0
    change  = round(((closes[-1] - closes[0]) / closes[0]) * 100, 4) if closes and closes[0] else 0
    return {"symbol": symbol, "price": price, "change_pct": change, "prices": closes,
            "is_real": False, "source": "simulated"}


@router.post("/api/backtest")
async def run_backtest(body: BacktestRequest, request: Request):
    from data_provider import get_provider, IndicatorSet
    from scoring import quality_score as _quality_score

    provider = get_provider()
    if not provider or not provider.is_configured:
        raise HTTPException(status_code=400,
                            detail="Backtesting requiere API key de Twelve Data configurada")

    candles_count = min(max(body.candles, 100), 500)
    expiry        = max(body.expiry_candles, 1)

    try:
        all_candles = await provider.fetch_historical_candles(body.symbol, body.interval, candles_count)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Error Twelve Data: {e}")

    if len(all_candles) < 60:
        raise HTTPException(status_code=400, detail="Datos insuficientes (mínimo 60 velas)")

    ensemble     = request.app.state.ensemble
    trades       = []
    wins         = 0
    losses       = 0
    equity       = 100.0
    equity_curve = [100.0]
    WINDOW       = 50
    PAYOUT       = 0.85

    for i in range(WINDOW, len(all_candles) - expiry):
        window = all_candles[i - WINDOW: i]
        ind    = IndicatorSet()
        ind.compute(window)
        ind.is_real = True

        signal = ensemble.get_consensus_signal(ind)
        if not signal:
            continue
        score = _quality_score(signal, body.symbol, ind)
        if score < body.min_quality:
            continue

        entry_price = all_candles[i].close
        exit_price  = all_candles[i + expiry].close
        won         = exit_price > entry_price if signal["type"] == "CALL" else exit_price < entry_price
        result      = "win" if won else "loss"

        if won:
            wins += 1; equity = round(equity * (1 + PAYOUT / 100), 4)
        else:
            losses += 1; equity = round(equity * (1 - 1 / 100), 4)

        equity_curve.append(equity)
        trades.append({
            "index": i, "timestamp": all_candles[i].time,
            "type": signal["type"], "entry_price": entry_price, "exit_price": exit_price,
            "score": round(score, 3), "cci": signal.get("cci", 0), "result": result, "equity": equity,
        })

    total = wins + losses
    win_rate      = round(wins / total * 100, 1) if total else 0
    gross_profit  = sum(t["equity"] - 100 for t in trades if t["result"] == "win")
    gross_loss    = sum(100 - t["equity"] for t in trades if t["result"] == "loss")
    profit_factor = round(abs(gross_profit / gross_loss), 2) if gross_loss else 0

    return {
        "symbol": body.symbol, "interval": body.interval, "candles_total": len(all_candles),
        "expiry_candles": expiry, "min_quality": body.min_quality,
        "total_signals": total, "wins": wins, "losses": losses,
        "win_rate": win_rate, "profit_factor": profit_factor,
        "final_equity": round(equity, 2), "equity_curve": equity_curve, "trades": trades,
        "summary": f"{total} señales | {win_rate}% WR | PF {profit_factor} | Capital final: {equity:.1f}%",
    }
