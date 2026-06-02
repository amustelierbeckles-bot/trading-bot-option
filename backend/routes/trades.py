"""
Routes de operaciones (trades).

  GET    /api/trades
  POST   /api/trades
  PUT    /api/trades/{id}
  DELETE /api/trades/{id}
  GET    /api/trades/by-signal/{signal_id}
  POST   /api/trades/{id}/execute
"""
import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from bson import ObjectId

from schemas import TradeResultModel

router = APIRouter()


from utils import _parse_naive_utc


async def _verify_api_key(x_api_key: Optional[str] = Header(None, alias="X-API-Key")):
    import hmac
    current_key = os.getenv("API_SECRET_KEY", None)
    if not current_key:
        raise HTTPException(status_code=503, detail="API key not configured")
    if not x_api_key:
        raise HTTPException(status_code=401, detail="X-API-Key header required")
    if not hmac.compare_digest(x_api_key, current_key):
        raise HTTPException(status_code=403, detail="Invalid API key")
    return True


@router.get("/api/trades")
async def get_trades(request: Request, limit: int = 50, skip: int = 0):
    use_mongo = request.app.state.use_mongo
    if use_mongo:
        cursor = request.app.state.db.trades.find().sort("created_at", -1).skip(skip).limit(limit)
        trades = await cursor.to_list(limit)
        for t in trades:
            t["id"] = str(t["_id"]); del t["_id"]
            if isinstance(t.get("created_at"), datetime):
                t["created_at"] = t["created_at"].strftime("%Y-%m-%dT%H:%M:%S") + "Z"
    else:
        raw    = list(reversed(request.app.state.trades_store))
        trades = raw[skip: skip + limit]
    return {"trades": trades, "count": len(trades)}


@router.post("/api/trades")
async def create_trade(trade: TradeResultModel, request: Request,
                       auth: bool = Depends(_verify_api_key)):
    now       = datetime.utcnow()
    use_mongo = request.app.state.use_mongo

    trade_doc = {
        **trade.dict(),
        "created_at": now,
        "updated_at": now,
        "source":     "manual",
    }

    if use_mongo:
        result    = await request.app.state.db.trades.insert_one(trade_doc)
        trade_doc["id"] = str(result.inserted_id)
        del trade_doc["_id"]
    else:
        trade_doc["id"] = str(int(now.timestamp() * 1000))
        request.app.state.trades_store.append(trade_doc)

    return {"success": True, "trade": trade_doc}


@router.put("/api/trades/{trade_id}")
async def update_trade(trade_id: str, trade: TradeResultModel, request: Request,
                       auth: bool = Depends(_verify_api_key)):
    use_mongo  = request.app.state.use_mongo
    update_doc = {**trade.dict(exclude_unset=True), "updated_at": datetime.utcnow()}

    if use_mongo:
        result = await request.app.state.db.trades.update_one(
            {"_id": ObjectId(trade_id)}, {"$set": update_doc})
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Trade not found")
    else:
        store = request.app.state.trades_store
        idx   = next((i for i, t in enumerate(store) if t.get("id") == trade_id), None)
        if idx is None:
            raise HTTPException(status_code=404, detail="Trade not found")
        store[idx] = {**store[idx], **update_doc}

    return {"success": True, "trade_id": trade_id}


@router.delete("/api/trades/{trade_id}")
async def delete_trade(trade_id: str, request: Request,
                       auth: bool = Depends(_verify_api_key)):
    use_mongo = request.app.state.use_mongo

    if use_mongo:
        result = await request.app.state.db.trades.delete_one({"_id": ObjectId(trade_id)})
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Trade not found")
    else:
        store = request.app.state.trades_store
        idx   = next((i for i, t in enumerate(store) if t.get("id") == trade_id), None)
        if idx is None:
            raise HTTPException(status_code=404, detail="Trade not found")
        store.pop(idx)

    return {"success": True}


@router.get("/api/trades/by-signal/{signal_id}")
async def get_trades_by_signal(signal_id: str, request: Request):
    use_mongo = request.app.state.use_mongo
    if use_mongo:
        cursor = request.app.state.db.trades.find({"signal_id": signal_id})
        trades = await cursor.to_list(50)
        for t in trades:
            t["id"] = str(t["_id"]); del t["_id"]
            if isinstance(t.get("created_at"), datetime):
                t["created_at"] = t["created_at"].strftime("%Y-%m-%dT%H:%M:%S") + "Z"
    else:
        trades = [t for t in request.app.state.trades_store if t.get("signal_id") == signal_id]
    return {"trades": trades, "count": len(trades)}
