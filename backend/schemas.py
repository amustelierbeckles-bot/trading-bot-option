"""
Pydantic models compartidos entre módulos del backend.
"""
from pydantic import BaseModel
from typing import List


class SignalScanRequest(BaseModel):
    symbols: List[str] = ["OTC_EURUSD", "OTC_EURJPY", "OTC_GBPUSD"]
    timeframe: str = "1m"
    use_ensemble: bool = True
    min_confidence: float = 0.65


class TradeResultModel(BaseModel):
    signal_id:        str
    symbol:           str
    asset_name:       str
    signal_type:      str            # "CALL" | "PUT"
    result:           str            # "win"  | "loss"
    entry_price:      float = 0.0
    payout:           float = 85.0
    quality_score:    float = 0.0
    cci:              float = 0.0
    signal_timestamp: str  = ""      # ISO timestamp de la señal original


class BacktestRequest(BaseModel):
    symbol:         str   = "OTC_EURUSD"
    interval:       str   = "1min"   # 1min | 5min | 15min
    candles:        int   = 200      # historial a analizar (máx 500)
    expiry_candles: int   = 2        # velas de expiración (2 = 2 min en 1min)
    min_quality:    float = 0.55     # umbral de calidad para contar señal


class RiskStatusRequest(BaseModel):
    symbol: str = "OTC_EURUSD"
    balance: float = 1000.0
    risk_pct: float = 2.0
    min_quality_threshold: float = None


class ExecuteSignalBody(BaseModel):
    execution_mode: str = "manual"   # "manual" | "auto"
    amount: float = 100.0
    po_order_id: str = None
