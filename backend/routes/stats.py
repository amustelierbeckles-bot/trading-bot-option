"""
Routes de estadísticas y rendimiento.

  GET /api/stats
  GET /api/stats/win-rate
  GET /api/stats/win-rate/pairs
  GET /api/strategies/performance
  GET /api/strategies/stats
  GET /api/audit/stats
"""
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Request

from win_rate_cache import wr_cache_get, wr_cache_set, hour_bucket, day_bucket
from calibration import get_dynamic_threshold, compute_optimal_threshold

logger = logging.getLogger(__name__)
router = APIRouter()


def _parse_naive_utc(ts: str) -> datetime:
    return datetime.fromisoformat(ts.rstrip("Z").split("+")[0])


@router.get("/api/stats")
async def get_stats(request: Request):
    """Estadísticas globales agregadas: señales, WR, tasa de error de datos, etc."""
    use_mongo = request.app.state.use_mongo
    now       = datetime.utcnow()
    day_ago   = now - timedelta(days=1)

    if use_mongo:
        db              = request.app.state.db
        total_signals   = await db.signals.count_documents({"created_at": {"$gte": day_ago}})
        total_trades    = await db.trades.count_documents({"created_at": {"$gte": day_ago}})
        recent_trades   = await db.trades.find({"result": {"$in": ["win", "loss"]}}).sort("created_at", -1).to_list(200)
    else:
        total_signals   = sum(1 for s in request.app.state.signals_store
                              if _parse_naive_utc(s["created_at"]) >= day_ago)
        total_trades    = sum(1 for t in request.app.state.trades_store
                              if _parse_naive_utc(t.get("created_at", "2000-01-01T00:00:00Z")) >= day_ago)
        recent_trades   = [t for t in reversed(request.app.state.trades_store)
                           if t.get("result") in ("win", "loss")][:200]

    total   = len(recent_trades)
    wins    = sum(1 for t in recent_trades if t.get("result") == "win")
    wr      = round(wins / total * 100, 1) if total else 0.0

    return {
        "period":        "24h",
        "total_signals": total_signals,
        "total_trades":  total_trades,
        "win_rate":      wr,
        "wins":          wins,
        "losses":        total - wins,
        "dynamic_threshold": round(get_dynamic_threshold(), 4),
    }


@router.get("/api/stats/win-rate")
async def get_win_rate(request: Request):
    """Win rate por hora y por día, con caché Redis."""
    redis     = getattr(request.app.state, "redis", None)
    use_mongo = request.app.state.use_mongo

    now_buckets = datetime.utcnow()
    h_key = hour_bucket(now_buckets)
    d_key = day_bucket(now_buckets)

    cached_hour = await wr_cache_get(redis, h_key) if redis else None
    cached_day  = await wr_cache_get(redis, d_key) if redis else None

    if cached_hour and cached_day:
        return {"hourly": cached_hour, "daily": cached_day, "source": "cache"}

    now       = datetime.utcnow()
    hour_ago  = now - timedelta(hours=1)
    day_ago   = now - timedelta(days=1)

    if use_mongo:
        db = request.app.state.db
        h_trades = await db.trades.find({"result": {"$in": ["win", "loss"]}, "created_at": {"$gte": hour_ago}}).to_list(1000)
        d_trades = await db.trades.find({"result": {"$in": ["win", "loss"]}, "created_at": {"$gte": day_ago}}).to_list(5000)
    else:
        h_trades = [t for t in request.app.state.trades_store
                    if t.get("result") in ("win", "loss") and
                    _parse_naive_utc(t.get("created_at", "2000-01-01T00:00:00Z")) >= hour_ago]
        d_trades = [t for t in request.app.state.trades_store
                    if t.get("result") in ("win", "loss") and
                    _parse_naive_utc(t.get("created_at", "2000-01-01T00:00:00Z")) >= day_ago]

    def _calc(trades):
        total = len(trades)
        wins  = sum(1 for t in trades if t.get("result") == "win")
        return {"win_rate": round(wins / total * 100, 1) if total else 0.0,
                "wins": wins, "losses": total - wins, "total": total}

    hourly = _calc(h_trades)
    daily  = _calc(d_trades)

    if redis:
        await wr_cache_set(redis, h_key, hourly)
        await wr_cache_set(redis, d_key, daily)

    return {"hourly": hourly, "daily": daily, "source": "computed"}


@router.get("/api/stats/win-rate/pairs")
async def get_win_rate_by_pairs(request: Request):
    """Win rate desglosado por par de divisas."""
    use_mongo = request.app.state.use_mongo
    day_ago   = datetime.utcnow() - timedelta(days=7)

    if use_mongo:
        trades = await request.app.state.db.trades.find(
            {"result": {"$in": ["win", "loss"]}, "created_at": {"$gte": day_ago}}
        ).to_list(5000)
    else:
        trades = [t for t in request.app.state.trades_store
                  if t.get("result") in ("win", "loss") and
                  _parse_naive_utc(t.get("created_at", "2000-01-01T00:00:00Z")) >= day_ago]

    agg: dict = {}
    for t in trades:
        sym = t.get("symbol", "UNKNOWN")
        if sym not in agg:
            agg[sym] = {"wins": 0, "losses": 0}
        if t.get("result") == "win":
            agg[sym]["wins"] += 1
        else:
            agg[sym]["losses"] += 1

    result = []
    for sym, v in agg.items():
        total = v["wins"] + v["losses"]
        result.append({
            "symbol":   sym,
            "wins":     v["wins"],
            "losses":   v["losses"],
            "total":    total,
            "win_rate": round(v["wins"] / total * 100, 1) if total else 0.0,
        })
    result.sort(key=lambda x: x["win_rate"], reverse=True)
    return {"pairs": result, "period": "7 days"}


@router.get("/api/strategies/performance")
@router.get("/api/strategies/stats")
async def get_strategies_performance(request: Request):
    """Rendimiento histórico de cada estrategia."""
    use_mongo = request.app.state.use_mongo
    day_ago   = datetime.utcnow() - timedelta(days=7)

    if use_mongo:
        trades = await request.app.state.db.trades.find(
            {"result": {"$in": ["win", "loss"]}, "created_at": {"$gte": day_ago}}
        ).to_list(5000)
    else:
        trades = [t for t in request.app.state.trades_store
                  if t.get("result") in ("win", "loss") and
                  _parse_naive_utc(t.get("created_at", "2000-01-01T00:00:00Z")) >= day_ago]

    agg: dict = {}
    for t in trades:
        strats = t.get("strategies_agreeing", [])
        if not strats:
            strats = [t.get("strategy", "unknown")]
        for s in strats:
            if s not in agg:
                agg[s] = {"wins": 0, "losses": 0}
            if t.get("result") == "win":
                agg[s]["wins"] += 1
            else:
                agg[s]["losses"] += 1

    result = []
    for strat, v in agg.items():
        total = v["wins"] + v["losses"]
        result.append({
            "strategy": strat,
            "wins":     v["wins"],
            "losses":   v["losses"],
            "total":    total,
            "win_rate": round(v["wins"] / total * 100, 1) if total else 0.0,
        })
    result.sort(key=lambda x: x["win_rate"], reverse=True)
    return {"strategies": result, "period": "7 days"}


@router.get("/api/audit/stats")
async def get_audit_stats(request: Request):
    """Estadísticas del sistema de auditoría autónoma."""
    use_mongo = request.app.state.use_mongo
    now       = datetime.utcnow()
    day_ago   = now - timedelta(days=1)

    if use_mongo:
        db = request.app.state.db
        total_audited   = await db.trades.count_documents({"source": "auto_audit"})
        pending_audit   = await db.trades.count_documents({"result": "pending"})
        completed_today = await db.trades.count_documents({
            "source": "auto_audit",
            "result": {"$in": ["win", "loss"]},
            "created_at": {"$gte": day_ago},
        })
        auto_exec_today = await db.trades.count_documents({
            "source": "auto_execute",
            "created_at": {"$gte": day_ago},
        })
    else:
        total_audited   = sum(1 for t in request.app.state.trades_store if t.get("source") == "auto_audit")
        pending_audit   = sum(1 for t in request.app.state.trades_store if t.get("result") == "pending")
        completed_today = sum(1 for t in request.app.state.trades_store
                              if t.get("source") == "auto_audit" and t.get("result") in ("win", "loss")
                              and _parse_naive_utc(t.get("created_at", "2000-01-01")) >= day_ago)
        auto_exec_today = sum(1 for t in request.app.state.trades_store
                              if t.get("source") == "auto_execute"
                              and _parse_naive_utc(t.get("created_at", "2000-01-01")) >= day_ago)

    all_trades_with_result = (
        await request.app.state.db.trades.find(
            {"result": {"$in": ["win", "loss"]}}).to_list(2000)
        if use_mongo else
        [t for t in request.app.state.trades_store if t.get("result") in ("win", "loss")]
    )
    calibration_info = compute_optimal_threshold(all_trades_with_result)

    return {
        "total_audited":        total_audited,
        "pending_audit":        pending_audit,
        "completed_today":      completed_today,
        "auto_executed_today":  auto_exec_today,
        "dynamic_threshold":    round(get_dynamic_threshold(), 4),
        "calibration":          calibration_info,
    }
