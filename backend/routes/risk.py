"""
Routes de gestión de riesgo y sistema Antifragile.

  GET  /api/risk/status
  POST /api/risk/status
  POST /api/risk/reset
  POST /api/risk/circuit-breaker/reset
  GET  /api/circuit-breaker/status
  GET  /api/antifragile/status
  POST /api/antifragile/reset
  GET  /api/calibration/status
  POST /api/calibration/recalibrate
"""
import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from circuit_breaker import cb_get_state, cb_reset, cb_is_blocked
from antifragile import (
    _martingale_state, _correlation_locks, _timeframe_overrides,
    soft_martingale_next_bet,
)
from calibration import get_dynamic_threshold, set_dynamic_threshold, compute_optimal_threshold
from schemas import RiskStatusRequest

router = APIRouter()


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


@router.get("/api/risk/status")
async def get_risk_status(request: Request):
    """Estado actual del motor de riesgo Antifragile v3.0."""
    cb    = cb_get_state()
    now   = datetime.utcnow()

    martingale_summary = {}
    for sym, state in _martingale_state.items():
        martingale_summary[sym] = {
            "base_bet":      state.get("base", 0),
            "current_bet":   state.get("current", 0),
            "losses_streak": state.get("losses", 0),
        }

    correlation_active = {
        cur: exp.isoformat()
        for cur, exp in _correlation_locks.items()
        if isinstance(exp, datetime) and exp > now
    }

    timeframe_overrides_active = dict(_timeframe_overrides)

    return {
        "circuit_breaker":     cb,
        "martingale":          martingale_summary,
        "correlation_locks":   correlation_active,
        "timeframe_overrides": timeframe_overrides_active,
        "dynamic_threshold":   round(get_dynamic_threshold(), 4),
    }


@router.post("/api/risk/status")
async def update_risk_status(body: RiskStatusRequest, request: Request,
                             auth: bool = Depends(_verify_api_key)):
    """Actualiza umbral dinámico u otras configuraciones de riesgo."""
    if body.min_quality_threshold is not None:
        set_dynamic_threshold(body.min_quality_threshold)
    return {"success": True, "dynamic_threshold": round(get_dynamic_threshold(), 4)}


@router.post("/api/risk/reset")
async def reset_risk(request: Request, auth: bool = Depends(_verify_api_key)):
    """Resetea Circuit Breaker, Martingale y Correlation Locks de golpe."""
    cb_reset()
    _martingale_state.clear()
    _correlation_locks.clear()
    _timeframe_overrides.clear()
    return {"success": True, "message": "Risk state fully reset"}


@router.post("/api/risk/circuit-breaker/reset")
@router.post("/api/circuit-breaker/reset")
async def reset_circuit_breaker(auth: bool = Depends(_verify_api_key)):
    cb_reset()
    return {"success": True, "circuit_breaker": cb_get_state()}


@router.get("/api/circuit-breaker/status")
async def get_circuit_breaker_status():
    return cb_get_state()


@router.get("/api/antifragile/status")
async def get_antifragile_status():
    now = datetime.utcnow()
    return {
        "martingale_symbols":         list(_martingale_state.keys()),
        "correlation_locks_active":   sum(
            1 for exp in _correlation_locks.values()
            if isinstance(exp, datetime) and exp > now
        ),
        "timeframe_overrides_active": len(_timeframe_overrides),
    }


@router.post("/api/antifragile/reset")
async def reset_antifragile(auth: bool = Depends(_verify_api_key)):
    _martingale_state.clear()
    _correlation_locks.clear()
    _timeframe_overrides.clear()
    return {"success": True, "message": "Antifragile state reset"}


@router.get("/api/calibration/status")
async def get_calibration_status(request: Request):
    """Estado de la calibración dinámica del umbral de calidad."""
    use_mongo = request.app.state.use_mongo

    if use_mongo:
        trades = await request.app.state.db.trades.find(
            {"result": {"$in": ["win", "loss"]}}
        ).sort("created_at", -1).to_list(500)
    else:
        trades = [t for t in request.app.state.trades_store
                  if t.get("result") in ("win", "loss")][-500:]

    info = compute_optimal_threshold(trades)
    return {
        "current_threshold": round(get_dynamic_threshold(), 4),
        "calibration_info":  info,
        "trades_available":  len(trades),
    }


@router.post("/api/calibration/recalibrate")
async def recalibrate(request: Request, auth: bool = Depends(_verify_api_key)):
    """Fuerza una re-calibración del umbral dinámico usando los trades actuales."""
    use_mongo = request.app.state.use_mongo

    if use_mongo:
        trades = await request.app.state.db.trades.find(
            {"result": {"$in": ["win", "loss"]}}
        ).sort("created_at", -1).to_list(500)
    else:
        trades = [t for t in request.app.state.trades_store
                  if t.get("result") in ("win", "loss")][-500:]

    info = compute_optimal_threshold(trades)
    if info.get("optimal_threshold"):
        set_dynamic_threshold(info["optimal_threshold"])

    return {
        "success":           True,
        "new_threshold":     round(get_dynamic_threshold(), 4),
        "calibration_info":  info,
    }
