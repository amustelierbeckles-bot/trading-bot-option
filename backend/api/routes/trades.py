"""
api/routes/trades.py
Endpoints de trades — extraídos de server.py
  POST   /api/trades
  GET    /api/trades/stats
  GET    /api/trades/history
  DELETE /api/trades/{trade_id}
  DELETE /api/trades/bulk/last/{n}
  DELETE /api/trades/bulk/all
  GET    /api/performance/execution
  GET    /api/calibration
  POST   /api/backtest
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, Depends
from data_provider import IndicatorSet

from models.schemas import TradeResultModel, BacktestRequest
from core.risk_manager import (
    soft_martingale_next_bet, check_correlation_lock,
    update_correlation_lock, evaluate_timeframe,
)
from services.telegram_service import send_telegram

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Umbral dinámico global ────────────────────────────────────────────────────
_dynamic_min_quality:    float = 0.55
_MIN_TRADES_TO_CALIBRATE: int  = 15


from utils import _parse_naive_utc


def _try_parse_ts(ts_str: str) -> datetime:
    try:
        return datetime.fromisoformat(ts_str.rstrip("Z"))
    except Exception:
        return datetime.min


def _calc_stats(trades: list) -> dict:
    """Calcula Win Rate, Profit Factor y desgloses."""
    if not trades:
        return {"total_trades": 0, "total_wins": 0, "total_losses": 0,
                "win_rate": 0.0, "profit_factor": 0.0,
                "by_pair": {}, "by_hour": {}, "by_score": {}}

    wins   = [t for t in trades if t["result"] == "win"]
    losses = [t for t in trades if t["result"] == "loss"]
    win_rate = round(len(wins) / len(trades) * 100, 1)

    profit_wins  = sum(t.get("payout", 85) for t in wins)
    cost_losses  = len(losses) * 100
    profit_factor = round(profit_wins / cost_losses, 2) if cost_losses > 0 else 0.0

    by_pair = {}
    for sym in {t["symbol"] for t in trades}:
        pt = [t for t in trades if t["symbol"] == sym]
        pw = [t for t in pt if t["result"] == "win"]
        by_pair[sym] = {"asset_name": pt[0].get("asset_name", sym),
                        "total": len(pt), "wins": len(pw),
                        "win_rate": round(len(pw) / len(pt) * 100, 1)}

    by_hour: dict = {}
    for t in trades:
        try:
            ts   = t.get("signal_timestamp", t.get("created_at", ""))
            hour = datetime.fromisoformat(ts.rstrip("Z")).hour
        except Exception:
            hour = -1
        h = str(hour).zfill(2)
        entry = by_hour.setdefault(h, {"total": 0, "wins": 0})
        entry["total"] += 1
        if t["result"] == "win":
            entry["wins"] += 1
    for h, v in by_hour.items():
        v["win_rate"] = round(v["wins"] / v["total"] * 100, 1) if v["total"] else 0.0

    buckets  = [("< 55%", 0.0, 0.55), ("55-65%", 0.55, 0.65),
                ("65-75%", 0.65, 0.75), ("75-85%", 0.75, 0.85), ("> 85%", 0.85, 1.1)]
    by_score = {}
    for label, lo, hi in buckets:
        bt = [t for t in trades if lo <= t.get("quality_score", 0) < hi]
        bw = [t for t in bt if t["result"] == "win"]
        if bt:
            by_score[label] = {"total": len(bt), "wins": len(bw),
                               "win_rate": round(len(bw) / len(bt) * 100, 1)}

    return {"total_trades": len(trades), "total_wins": len(wins),
            "total_losses": len(losses), "win_rate": win_rate,
            "profit_factor": profit_factor,
            "by_pair": by_pair, "by_hour": by_hour, "by_score": by_score}


def _compute_optimal_threshold(trades: list) -> dict:
    """Calcula umbral óptimo de quality score basado en historial real."""
    completed = [t for t in trades if t.get("result") in ("win", "loss")]
    if len(completed) < _MIN_TRADES_TO_CALIBRATE:
        return {"calibrated": False, "optimal_threshold": _dynamic_min_quality,
                "recommendation": "Insuficientes trades", "buckets": []}

    buckets_data = []
    thresholds   = [0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80]
    best_threshold = _dynamic_min_quality
    best_score     = 0.0

    for thr in thresholds:
        subset = [t for t in completed if t.get("quality_score", 0) >= thr]
        if len(subset) < 5:
            continue
        wins    = sum(1 for t in subset if t["result"] == "win")
        wr      = wins / len(subset)
        # Score = WR ponderado por volumen (más trades = más confianza)
        score   = wr * min(len(subset) / 30, 1.0)
        buckets_data.append({"threshold": thr, "trades": len(subset),
                              "win_rate": round(wr * 100, 1), "score": round(score, 3)})
        if score > best_score:
            best_score     = score
            best_threshold = thr

    overall_wr = sum(1 for t in completed if t["result"] == "win") / len(completed)
    if overall_wr >= 0.65:
        rec = f"✅ Win Rate {overall_wr*100:.0f}% — umbral {best_threshold:.2f} óptimo"
    elif overall_wr >= 0.55:
        rec = f"🟡 Win Rate {overall_wr*100:.0f}% — considera subir umbral"
    else:
        rec = f"🔴 Win Rate {overall_wr*100:.0f}% — sube umbral o revisa estrategias"

    return {"calibrated": True, "optimal_threshold": best_threshold,
            "recommendation": rec, "buckets": buckets_data,
            "overall_win_rate": round(overall_wr * 100, 1), "total_trades": len(completed)}


@router.post("/api/trades")
async def register_trade(trade: TradeResultModel, request: Request):
    now = datetime.utcnow()
    doc = {
        **trade.model_dump(),
        "id":         f"trade_{int(now.timestamp()*1000)}",
        "created_at": now.strftime("%Y-%m-%dT%H:%M:%S") + "Z",
    }

    if request.app.state.use_mongo:
        db_doc = {**doc, "created_at": now}
        result_ins = await request.app.state.db.trades.insert_one(db_doc)
        doc["id"] = str(result_ins.inserted_id)
    else:
        request.app.state.trades_store.append(doc)

    logger.info("📝 Trade | %s %s → %s | score=%.2f",
                trade.signal_type, trade.symbol,
                "✅ WIN" if trade.result == "win" else "❌ LOSS",
                trade.quality_score)

    base_bet  = trade.entry_price * 0.02 if trade.entry_price else 10.0
    mg_result = soft_martingale_next_bet(trade.symbol, base_bet, trade.result)

    antifragile_response = {
        "martingale":               mg_result,
        "correlation_lock":         None,
        "timeframe_eval":           None,
        "newly_locked_currencies":  [],
    }

    if trade.result == "loss":
        if request.app.state.use_mongo:
            cursor = request.app.state.db.trades.find({"result": "loss"}).sort("created_at", -1).limit(10)
            recent_losses = await cursor.to_list(10)
            for t in recent_losses:
                t["id"] = str(t.pop("_id", ""))
        else:
            all_t         = list(request.app.state.trades_store)
            recent_losses = [t for t in reversed(all_t) if t.get("result") == "loss"][:10]

        newly_locked = update_correlation_lock(recent_losses, lock_minutes=30)
        antifragile_response["newly_locked_currencies"] = newly_locked

        if newly_locked:
            logger.warning("🔴 BLOQUEO CORRELACIÓN activado: %s", newly_locked)
            for nc in newly_locked:
                await send_telegram(
                    f"⚠️ <b>BLOQUEO POR CORRELACIÓN</b>: <code>{nc}</code>\n"
                    f"Pares con {nc} bloqueados 30 min.\n"
                    f"Causa: pérdidas en {trade.symbol} + par anterior"
                )

        antifragile_response["correlation_lock"] = check_correlation_lock(trade.symbol)

        loss_streak = mg_result["losses_streak"]
        if loss_streak in (1, 2):
            fake_ind = type("Ind", (), {"atr_pct": 0.015})()
            tf_eval  = evaluate_timeframe(trade.symbol, loss_streak, fake_ind)
            antifragile_response["timeframe_eval"] = tf_eval
            if tf_eval["action"] == "upgrade":
                await send_telegram(
                    f"📈 <b>CAMBIO DE TIMEFRAME</b>: <code>{trade.symbol}</code>\n"
                    f"{tf_eval['reason']}"
                )

    return {"success": True, "trade": doc, "antifragile": antifragile_response}


@router.get("/api/trades/stats")
async def get_trade_stats(request: Request, days: int = 30):
    cutoff = datetime.utcnow() - timedelta(days=days)
    if request.app.state.use_mongo:
        cursor = request.app.state.db.trades.find(
            {"created_at": {"$gte": cutoff}}
        ).sort("created_at", -1)
        trades = await cursor.to_list(1000)
        for t in trades:
            t["id"] = str(t.pop("_id"))
            if isinstance(t.get("created_at"), datetime):
                t["created_at"] = t["created_at"].strftime("%Y-%m-%dT%H:%M:%S") + "Z"
    else:
        trades = [t for t in request.app.state.trades_store
                  if datetime.fromisoformat(t["created_at"].rstrip("Z")) >= cutoff]

    stats = _calc_stats(trades)
    stats["period_days"] = days
    stats["last_trades"] = trades[:10]
    return stats


@router.get("/api/trades/history")
async def get_trade_history(request: Request, limit: int = 50):
    if request.app.state.use_mongo:
        cursor = request.app.state.db.trades.find().sort("created_at", -1).limit(limit)
        trades = await cursor.to_list(limit)
        for t in trades:
            t["id"] = str(t.pop("_id"))
            if isinstance(t.get("created_at"), datetime):
                t["created_at"] = t["created_at"].strftime("%Y-%m-%dT%H:%M:%S") + "Z"
    else:
        trades = list(reversed(request.app.state.trades_store))[:limit]
    return {"trades": trades, "count": len(trades)}


@router.get("/api/trades/by-signal/{signal_id}")
async def get_trade_by_signal(signal_id: str, request: Request):
    """Devuelve el resultado registrado para una señal específica."""
    if request.app.state.use_mongo:
        doc = await request.app.state.db.trades.find_one(
            {"signal_id": signal_id},
            sort=[("created_at", -1)],
        )
        if doc:
            doc["id"] = str(doc.pop("_id"))
            if isinstance(doc.get("created_at"), datetime):
                doc["created_at"] = doc["created_at"].strftime("%Y-%m-%dT%H:%M:%S") + "Z"
            return {"found": True, "result": doc.get("result"), "trade": doc}
    else:
        store = list(request.app.state.trades_store)
        for t in reversed(store):
            if t.get("signal_id") == signal_id:
                return {"found": True, "result": t.get("result"), "trade": t}
    return {"found": False, "result": None, "trade": None}


@router.delete("/api/trades/{trade_id}")
async def delete_trade(trade_id: str, request: Request):
    if request.app.state.use_mongo:
        from bson import ObjectId
        await request.app.state.db.trades.delete_one({"_id": ObjectId(trade_id)})
    else:
        store = request.app.state.trades_store
        request.app.state.trades_store = [t for t in store if t.get("id") != trade_id]
    return {"success": True}


@router.delete("/api/trades/bulk/last/{n}")
async def delete_last_n_trades(n: int, request: Request):
    if n <= 0 or n > 500:
        raise HTTPException(status_code=400, detail="n debe estar entre 1 y 500")

    if request.app.state.use_mongo:
        cursor = request.app.state.db.trades.find().sort("created_at", -1).limit(n)
        last_n = await cursor.to_list(n)
        ids_to_delete = [t["_id"] for t in last_n]
        result  = await request.app.state.db.trades.delete_many({"_id": {"$in": ids_to_delete}})
        deleted = result.deleted_count
    else:
        store        = list(request.app.state.trades_store)
        store_sorted = sorted(store, key=lambda t: t.get("created_at", ""), reverse=True)
        ids_to_delete = {t["id"] for t in store_sorted[:n]}
        request.app.state.trades_store = [t for t in store if t.get("id") not in ids_to_delete]
        deleted = len(ids_to_delete)

    return {"success": True, "deleted": deleted,
            "message": f"✅ {deleted} operaciones eliminadas del historial"}


@router.delete("/api/trades/bulk/all")
async def delete_all_trades(request: Request):
    if request.app.state.use_mongo:
        result  = await request.app.state.db.trades.delete_many({})
        deleted = result.deleted_count
    else:
        deleted = len(request.app.state.trades_store)
        request.app.state.trades_store = []
    return {"success": True, "deleted": deleted,
            "message": f"✅ Historial completo borrado ({deleted} operaciones)"}


@router.get("/api/performance/execution")
async def get_execution_quality(request: Request, days: int = 30):
    cutoff = datetime.utcnow() - timedelta(days=days)
    if request.app.state.use_mongo:
        cursor = request.app.state.db.trades.find(
            {"created_at": {"$gte": cutoff}, "result": {"$in": ["win", "loss"]}}
        ).sort("created_at", -1)
        trades = await cursor.to_list(2000)
        for t in trades:
            t["id"] = str(t.pop("_id", ""))
            if isinstance(t.get("created_at"), datetime):
                t["created_at"] = t["created_at"].strftime("%Y-%m-%dT%H:%M:%S") + "Z"
    else:
        trades = [t for t in request.app.state.trades_store if t.get("result") in ("win", "loss")]

    if not trades:
        return {"total_trades": 0, "mae_avg_pips": None, "mae_label": "Sin datos",
                "latency_avg_ms": None, "by_session": {}, "mae_vs_result": {}, "period_days": days}

    mae_trades = [t for t in trades if t.get("max_adverse_excursion") is not None]
    lat_trades = [t for t in trades if t.get("execution_latency_ms") is not None]
    mae_avg    = round(sum(t["max_adverse_excursion"] for t in mae_trades) / len(mae_trades), 2) if mae_trades else None
    lat_avg    = round(sum(t["execution_latency_ms"] for t in lat_trades) / len(lat_trades)) if lat_trades else None

    def mae_label(avg):
        if avg is None: return "Sin datos suficientes"
        if avg < 3:     return "🟢 Limpia"
        if avg < 6:     return "🟡 Moderada"
        if avg < 10:    return "🟠 Riesgosa"
        return "🔴 Muy Riesgosa"

    by_session = {}
    for sess in ["Asiática", "Londres", "Londres+NY", "Nueva York"]:
        st = [t for t in trades if t.get("session") == sess]
        if not st:
            continue
        sm = [t for t in st if t.get("max_adverse_excursion") is not None]
        sl = [t for t in st if t.get("execution_latency_ms") is not None]
        sw = [t for t in st if t.get("result") == "win"]
        by_session[sess] = {
            "total": len(st), "wins": len(sw),
            "win_rate": round(len(sw) / len(st) * 100, 1),
            "mae_avg_pips":   round(sum(t["max_adverse_excursion"] for t in sm) / len(sm), 2) if sm else None,
            "mae_label":      mae_label(round(sum(t["max_adverse_excursion"] for t in sm) / len(sm), 2) if sm else None),
            "latency_avg_ms": round(sum(t["execution_latency_ms"] for t in sl) / len(sl)) if sl else None,
        }

    return {"total_trades": len(trades), "trades_with_mae": len(mae_trades),
            "mae_avg_pips": mae_avg, "mae_label": mae_label(mae_avg),
            "latency_avg_ms": lat_avg, "by_session": by_session, "period_days": days}


@router.get("/api/calibration")
async def get_calibration(request: Request):
    global _dynamic_min_quality
    if request.app.state.use_mongo:
        cursor = request.app.state.db.trades.find().sort("created_at", -1)
        trades = await cursor.to_list(2000)
        for t in trades:
            t["id"] = str(t.pop("_id"))
            if isinstance(t.get("created_at"), datetime):
                t["created_at"] = t["created_at"].strftime("%Y-%m-%dT%H:%M:%S") + "Z"
    else:
        trades = list(request.app.state.trades_store)

    if len(trades) < _MIN_TRADES_TO_CALIBRATE:
        return {"calibrated": False, "total_trades": len(trades),
                "min_trades_required": _MIN_TRADES_TO_CALIBRATE,
                "current_threshold": _dynamic_min_quality,
                "optimal_threshold": _dynamic_min_quality,
                "recommendation": f"Necesitas al menos {_MIN_TRADES_TO_CALIBRATE} operaciones. Tienes {len(trades)}.",
                "buckets": []}

    result = _compute_optimal_threshold(trades)
    if result["calibrated"]:
        old = _dynamic_min_quality
        _dynamic_min_quality = max(0.45, min(0.85, result["optimal_threshold"]))
        if abs(_dynamic_min_quality - old) > 0.01:
            logger.info("🎯 Calibración aplicada: %.2f → %.2f", old, _dynamic_min_quality)

    result["current_threshold"] = _dynamic_min_quality
    return result


@router.post("/api/backtest")
async def run_backtest(body: BacktestRequest, request: Request):
    from data_provider import get_provider
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

    from server_legacy import _quality_score
    ensemble     = request.app.state.ensemble
    trades       = []
    wins = losses = 0
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
        won         = (exit_price > entry_price) if signal["type"] == "CALL" else (exit_price < entry_price)

        if won:
            wins  += 1
            equity = round(equity * (1 + PAYOUT / 100), 4)
        else:
            losses += 1
            equity = round(equity * (1 - 1 / 100), 4)

        equity_curve.append(equity)
        trades.append({"index": i, "timestamp": all_candles[i].time,
                       "type": signal["type"], "entry_price": entry_price,
                       "exit_price": exit_price, "score": round(score, 3),
                       "cci": signal.get("cci", 0),
                       "result": "win" if won else "loss", "equity": equity})

    total         = wins + losses
    win_rate      = round(wins / total * 100, 1) if total else 0
    gross_profit  = sum(t["equity"] - 100 for t in trades if t["result"] == "win")
    gross_loss    = sum(100 - t["equity"] for t in trades if t["result"] == "loss")
    profit_factor = round(abs(gross_profit / gross_loss), 2) if gross_loss else 0

    return {"symbol": body.symbol, "interval": body.interval,
            "candles_total": len(all_candles), "expiry_candles": expiry,
            "min_quality": body.min_quality, "total_signals": total,
            "wins": wins, "losses": losses, "win_rate": win_rate,
            "profit_factor": profit_factor, "final_equity": round(equity, 2),
            "equity_curve": equity_curve, "trades": trades,
            "summary": f"{total} señales | {win_rate}% WR | PF {profit_factor} | Capital final: {equity:.1f}%"}
