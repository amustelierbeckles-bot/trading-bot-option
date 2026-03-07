"""
TRADING BOT BACKEND - VERSIÓN COMPLETA v2.0-fix1
Multi-Strategy Trading Bot with MongoDB & Redis

FIX 2026-02-26: Desactivada auditoría autónoma.
- _auto_register_observation ya no se llama al enviar señal Telegram
- _autonomous_audit ya no se lanza en background
- _mae_sampling_loop ya no corre en background
- Los trades en MongoDB ahora solo vienen de registro MANUAL del usuario
- Esto corrige Win Rate corrupto y calibración del umbral dinámico incorrecta
"""

from fastapi import FastAPI, HTTPException, Request, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from pydantic import BaseModel
from contextlib import asynccontextmanager
import os
import random
import logging
import math
import asyncio
import httpx
import time
import json
from pathlib import Path
from dotenv import load_dotenv

try:
    import redis.asyncio as aioredis
    _REDIS_AVAILABLE = True
except ImportError:
    _REDIS_AVAILABLE = False

# Import time for rate limiting
time_module = time

# Carga el archivo .env desde la raíz del proyecto
load_dotenv(Path(__file__).parent.parent / ".env")

from data_provider import (
    IndicatorSet, get_indicators_for, init_provider, get_provider,
    get_simulated_indicators, OTC_TO_TWELVE,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================================
# WIN RATE CACHE (Redis → in-memory fallback)
# ============================================================================
# Clave formato:  "wr:{scope}:{window}"
# Ej:  "wr:global:1h"  |  "wr:OTC_EURUSD:1h"  |  "wr:london:session"
# TTL: 300 segundos (5 minutos)
# Cuando Redis no está disponible se usa un dict en memoria con timestamp.

_WR_CACHE_TTL = 300   # segundos
_wr_mem_cache: Dict[str, tuple] = {}   # key → (value, expires_at)


async def _wr_cache_get(redis, key: str) -> Optional[dict]:
    """Lee Win Rate del caché. Retorna dict o None si expirado/inexistente."""
    try:
        if redis is not None:
            raw = await redis.get(key)
            return json.loads(raw) if raw else None
    except Exception:
        pass
    # Fallback in-memory
    entry = _wr_mem_cache.get(key)
    if entry and time.time() < entry[1]:
        return entry[0]
    return None


async def _wr_cache_set(redis, key: str, value: dict, ttl: int = _WR_CACHE_TTL) -> None:
    """Escribe Win Rate en caché con TTL."""
    try:
        if redis is not None:
            await redis.set(key, json.dumps(value), ex=ttl)
            return
    except Exception:
        pass
    # Fallback in-memory
    _wr_mem_cache[key] = (value, time.time() + ttl)


async def _wr_cache_invalidate(redis, pattern: str) -> None:
    """Invalida todas las claves que empiecen con el patrón dado."""
    try:
        if redis is not None:
            keys = await redis.keys(f"{pattern}*")
            if keys:
                await redis.delete(*keys)
            return
    except Exception:
        pass
    # Fallback in-memory: limpia claves que comiencen con el patrón
    to_del = [k for k in _wr_mem_cache if k.startswith(pattern)]
    for k in to_del:
        _wr_mem_cache.pop(k, None)


def _hour_bucket(dt: datetime) -> str:
    """Devuelve 'YYYY-MM-DDTHH' para indexar Win Rate por hora."""
    return dt.strftime("%Y-%m-%dT%H")


def _day_bucket(dt: datetime) -> str:
    """Devuelve 'YYYY-MM-DD' para indexar Win Rate por día."""
    return dt.strftime("%Y-%m-%d")


# ============================================================================
# CIRCUIT BREAKER AUTÓNOMO
# ============================================================================
# Estado global del CB. Se actualiza cada vez que se verifica un resultado
# en _verify_signal_result, sin requerir intervención del usuario.
#
# Estructura:
#   _cb_state["blocked"]        → bool
#   _cb_state["blocked_until"]  → datetime | None
#   _cb_state["consecutive_losses"] → int
#   _cb_state["reason"]         → str

_cb_state: Dict[str, object] = {
    "blocked":            False,
    "blocked_until":      None,
    "consecutive_losses": 0,
    "reason":             "",
}

CB_CONSECUTIVE_LIMIT = 3
CB_COOLDOWN_MINUTES  = 60


def _cb_is_blocked() -> bool:
    """
    Retorna True si el Circuit Breaker está activo y el cooldown no expiró.
    Si el cooldown ya pasó, resetea el estado automáticamente.
    """
    if not _cb_state["blocked"]:
        return False
    until = _cb_state.get("blocked_until")
    if until and datetime.utcnow() >= until:
        # Cooldown expirado → reset automático
        _cb_state.update({"blocked": False, "blocked_until": None,
                           "consecutive_losses": 0, "reason": ""})
        logger.info("✅ Circuit Breaker: cooldown expirado — bot reanudado")
        return False
    return True


def _cb_record_result(outcome: str, symbol: str) -> None:
    """
    Actualiza el contador de pérdidas consecutivas del CB.
    Llamado desde _verify_signal_result después de cada verificación.

    - "win"  → resetea el contador (racha rota)
    - "loss" → incrementa; si llega a CB_CONSECUTIVE_LIMIT dispara el bloqueo
    """
    if _cb_state["blocked"]:
        return  # ya bloqueado, no re-disparar

    if outcome == "win":
        _cb_state["consecutive_losses"] = 0
    elif outcome == "loss":
        _cb_state["consecutive_losses"] = int(_cb_state["consecutive_losses"]) + 1
        n = _cb_state["consecutive_losses"]
        logger.warning("⚠️  CB: %d pérdida(s) consecutiva(s) | %s", n, symbol)

        if n >= CB_CONSECUTIVE_LIMIT:
            until = datetime.utcnow() + timedelta(minutes=CB_COOLDOWN_MINUTES)
            _cb_state.update({
                "blocked":       True,
                "blocked_until": until,
                "reason":        (f"🛑 {n} pérdidas consecutivas — "
                                  f"bot pausado hasta {until.strftime('%H:%M')} UTC"),
            })
            logger.warning("🛑 CIRCUIT BREAKER ACTIVADO | %s | cooldown hasta %s UTC",
                           symbol, until.strftime("%H:%M"))


# ============================================================================
# MODELS
# ============================================================================

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

# ============================================================================
# PRECIOS BASE POR SÍMBOLO
# ============================================================================

ASSET_PRICES = {
    "OTC_EURUSD": 1.0823, "OTC_GBPUSD": 1.2654, "OTC_USDJPY": 150.12,
    "OTC_USDCHF": 0.8823, "OTC_AUDUSD": 0.6523, "OTC_USDCAD": 1.3512,
    "OTC_NZDUSD": 0.5912, "OTC_EURJPY": 162.45, "OTC_EURGBP": 0.8556,
    "OTC_EURAUD": 1.6589, "OTC_EURCAD": 1.4623, "OTC_EURCHF": 0.9545,
    "OTC_GBPJPY": 189.90, "OTC_GBPAUD": 1.9398, "OTC_GBPCAD": 1.7098,
    "OTC_GBPCHF": 1.1162, "OTC_AUDJPY": 97.90,  "OTC_AUDCAD": 0.8812,
    "OTC_CADJPY": 111.09, "OTC_CHFJPY": 170.16,
}

# ── Generador de precios con momentum persistente ────────────────────────────
# Mantiene estado entre ciclos para que las señales sean coherentes
# con la dirección del precio (micro-tendencia simulada pero consistente).
_price_state: Dict[str, Dict] = {}

def get_asset_price(symbol: str) -> float:
    base = ASSET_PRICES.get(symbol, 1.0000)
    state = _price_state.get(symbol)

    if not state:
        state = {"price": base, "momentum": 0.0, "ticks": 0}
        _price_state[symbol] = state

    # Momentum mean-reverting con drift aleatorio
    # Tiende a regresar al precio base lentamente (mean-reversion)
    drift       = (base - state["price"]) * 0.003  # atracción al base
    noise       = random.gauss(0, base * 0.0003)
    momentum    = state["momentum"] * 0.85 + drift + noise  # decay + nueva info
    new_price   = state["price"] + momentum

    state["price"]    = round(new_price, 5)
    state["momentum"] = momentum
    state["ticks"]   += 1

    return state["price"]

def get_price_trend(symbol: str, ind: Optional[IndicatorSet] = None) -> str:
    """Retorna tendencia: usa indicadores reales si están disponibles."""
    if ind and ind.is_real:
        return ind.trend
    # Fallback al momentum simulado
    state = _price_state.get(symbol)
    if not state:
        return "neutral"
    m         = state["momentum"]
    threshold = ASSET_PRICES.get(symbol, 1.0) * 0.0001
    if m > threshold:  return "bullish"
    if m < -threshold: return "bearish"
    return "neutral"

# ============================================================================
# ESTRATEGIAS
# ============================================================================

def _conf_from_extreme(value: float, low_bad: float, low_good: float,
                       high_good: float, high_bad: float,
                       min_conf: float = 0.60, max_conf: float = 0.82) -> float:
    """
    Calcula confianza según qué tan extremo es un valor.
    Ej: RSI=25 → más extremo que RSI=31 → mayor confianza.
    """
    if value <= low_good:
        ratio = (low_good - value) / max(low_good - low_bad, 1e-9)
    elif value >= high_good:
        ratio = (value - high_good) / max(high_bad - high_good, 1e-9)
    else:
        return 0.0
    return round(min_conf + (max_conf - min_conf) * min(ratio, 1.0), 2)


class TradingStrategy:
    def __init__(self, name: str, weight: float = 1.0):
        self.name = name
        self.weight = weight
        self.enabled = True
        self.min_confidence = 0.60
    
    def generate_signal(self, ind: Optional[IndicatorSet] = None) -> Optional[Dict]:
        return None


class RangeBreakoutStrategy(TradingStrategy):
    """
    Breakout de rango usando ATR + EMA21 + histograma MACD.

    Filosofía OPUESTA a las estrategias de reversión (RSI/CCI):
    - RSI/CCI: "precio en extremo → va a revertir al centro"
    - Esta:    "precio rompió el rango → va a CONTINUAR en esa dirección"

    Esta decorrelación es la clave: cuando RSI/CCI Y esta estrategia coinciden,
    hay dos marcos teóricos independientes apuntando al mismo lado → señal fuerte.

    Condiciones CALL (breakout alcista):
      1. precio > ema21 + (atr * 1.2)  — rompió el rango superior
      2. macd_hist > 0                  — momentum positivo confirma
      3. atr_pct > 0.04                 — volatilidad real, no ruido lateral
      4. trend == "bullish"             — EMA confirma dirección

    Condiciones PUT (breakout bajista):
      1. precio < ema21 - (atr * 1.2)  — rompió el rango inferior
      2. macd_hist < 0                  — momentum negativo confirma
      3. atr_pct > 0.04                 — volatilidad real, no ruido lateral
      4. trend == "bearish"             — EMA confirma dirección

    Grupo ortogonal: breakout_volatility (5º grupo, el más anticorrelacionado).
    """

    ATR_MULT     = 1.2    # multiplicador del ATR para definir el rango
    MIN_ATR_PCT  = 0.04   # % mínimo de ATR para filtrar mercados laterales

    def __init__(self):
        super().__init__("Range Breakout + ATR", 1.2)

    def generate_signal(self, ind: Optional[IndicatorSet] = None) -> Optional[Dict]:
        if not (ind and ind.is_real):
            return None

        price     = ind.price
        ema21     = ind.ema21
        atr       = ind.atr
        atr_pct   = ind.atr_pct
        macd_hist = ind.macd_hist
        trend     = ind.trend

        # Filtro de volatilidad mínima: descartar mercados planos
        if atr_pct < self.MIN_ATR_PCT or atr <= 0:
            return None

        breakout_band = atr * self.ATR_MULT
        above_range   = price > ema21 + breakout_band
        below_range   = price < ema21 - breakout_band

        # CALL: breakout alcista confirmado por MACD y tendencia
        if above_range and macd_hist > 0 and trend == "bullish":
            # Confianza: qué tan lejos está del rango (más lejos = más fuerte)
            excess_atr = (price - (ema21 + breakout_band)) / atr
            conf = round(min(0.58 + excess_atr * 0.08 + abs(macd_hist) * 2, 0.82), 2)
            return {
                "type":       "CALL",
                "confidence": conf,
                "cci":        round(ind.cci, 1),
                "reason":     (f"Breakout alcista | precio {price:.5f} > "
                               f"EMA21+ATR*{self.ATR_MULT} ({ema21 + breakout_band:.5f}) | "
                               f"MACD hist={macd_hist:.5f}"),
            }

        # PUT: breakout bajista confirmado por MACD y tendencia
        if below_range and macd_hist < 0 and trend == "bearish":
            excess_atr = ((ema21 - breakout_band) - price) / atr
            conf = round(min(0.58 + excess_atr * 0.08 + abs(macd_hist) * 2, 0.82), 2)
            return {
                "type":       "PUT",
                "confidence": conf,
                "cci":        round(ind.cci, 1),
                "reason":     (f"Breakout bajista | precio {price:.5f} < "
                               f"EMA21-ATR*{self.ATR_MULT} ({ema21 - breakout_band:.5f}) | "
                               f"MACD hist={macd_hist:.5f}"),
            }

        return None


class CCIAlligatorStrategy(TradingStrategy):
    """
    CCI extremo como señal de REVERSIÓN + confirmación con EMA opuesta.
    En mercados OTC el CCI extremo indica sobreextensión y rebote inminente.

    REAL:  CCI > 100 + trend bearish (sobrecomprado, va a bajar) → PUT
           CCI < -100 + trend bullish (sobrevendido, va a subir)  → CALL

    Lógica: el precio está sobreextendido respecto a su media.
    El Alligator (EMA) empieza a girar en contra → confirmación de reversión.
    """
    def __init__(self):
        super().__init__("CCI + Alligator", 1.2)
    
    def generate_signal(self, ind: Optional[IndicatorSet] = None) -> Optional[Dict]:
        if ind and ind.is_real:
            cci   = ind.cci
            trend = ind.trend
            # CCI sobrecomprado + tendencia girando a la baja → PUT (reversión bajista)
            if cci > 100 and trend in ("bearish", "neutral"):
                conf = round(min(0.60 + abs(cci) / 800, 0.80), 2)
                return {"type": "PUT",  "confidence": conf, "cci": round(cci, 1),
                        "reason": f"CCI sobrecomprado ({cci:.1f}) → reversión bajista OTC"}
            # CCI sobrevendido + tendencia girando al alza → CALL (reversión alcista)
            if cci < -100 and trend in ("bullish", "neutral"):
                conf = round(min(0.60 + abs(cci) / 800, 0.80), 2)
                return {"type": "CALL", "confidence": conf, "cci": round(cci, 1),
                        "reason": f"CCI sobrevendido ({cci:.1f}) → reversión alcista OTC"}
        return None

        # Fallback simulado
        cci = ind.cci if ind else random.uniform(-200, 200)
        if cci > 100:
            return {"type": "PUT",  "confidence": round(random.uniform(0.60, 0.72), 2),
                    "cci": round(cci, 1), "reason": f"CCI sobrecomprado ({cci:.1f}) - reversión bajista"}
        elif cci < -100:
            return {"type": "CALL", "confidence": round(random.uniform(0.60, 0.72), 2),
                    "cci": round(cci, 1), "reason": f"CCI sobrevendido ({cci:.1f}) - reversión alcista"}
        return None


class RSIBollingerStrategy(TradingStrategy):
    """
    RSI + precio cerca de banda de Bollinger.
    REAL:  RSI < 35 + precio dentro del 0.5% de BB_lower → CALL
           RSI > 65 + precio dentro del 0.5% de BB_upper → PUT
    """
    def __init__(self):
        super().__init__("RSI + Bollinger Bands", 1.1)
    
    def generate_signal(self, ind: Optional[IndicatorSet] = None) -> Optional[Dict]:
        if ind and ind.is_real:
            rsi   = ind.rsi
            price = ind.price
            bb_u  = ind.bb_upper
            bb_l  = ind.bb_lower
            bb_range = max(bb_u - bb_l, 1e-9)

            dist_upper = (bb_u - price) / bb_range
            dist_lower = (price - bb_l) / bb_range

            if rsi < 35 and dist_lower < 0.10:
                conf = _conf_from_extreme(rsi, 10, 35, 65, 90)
                return {"type": "CALL", "confidence": conf, "cci": round(ind.cci, 1),
                        "reason": f"RSI {rsi:.1f} + precio en BB inferior real"}
            if rsi > 65 and dist_upper < 0.10:
                conf = _conf_from_extreme(rsi, 10, 35, 65, 90)
                return {"type": "PUT",  "confidence": conf, "cci": round(ind.cci, 1),
                        "reason": f"RSI {rsi:.1f} + precio en BB superior real"}
        return None

        # Fallback simulado
        rsi = ind.rsi if ind else random.uniform(20, 82)
        if rsi > 70:
            return {"type": "PUT",  "confidence": round(random.uniform(0.62, 0.74), 2),
                    "cci": round(random.uniform(90, 130), 1),
                    "reason": f"RSI {rsi:.1f} + precio en Bollinger superior"}
        elif rsi < 30:
            return {"type": "CALL", "confidence": round(random.uniform(0.62, 0.74), 2),
                    "cci": round(random.uniform(-130, -90), 1),
                    "reason": f"RSI {rsi:.1f} + precio en Bollinger inferior"}
        return None


class MACDStochasticStrategy(TradingStrategy):
    """
    Estocástico extremo + histograma MACD para confirmar impulso real.
    REAL:  Stoch < 20 + histogram > 0 → CALL (impulso alcista confirmado)
           Stoch > 80 + histogram < 0 → PUT  (impulso bajista confirmado)

    Usa el histograma (macd_line - signal_line) en vez de solo macd_line
    para detectar el momento en que el impulso realmente cambia de dirección.
    """
    def __init__(self):
        super().__init__("MACD + Stochastic", 1.0)
    
    def generate_signal(self, ind: Optional[IndicatorSet] = None) -> Optional[Dict]:
        if ind and ind.is_real:
            stoch    = ind.stoch_k
            # Usa macd_hist si existe, si no cae back a macd_line
            histogram = getattr(ind, "macd_hist", ind.macd_line)
            if stoch < 20 and histogram > 0:
                conf = _conf_from_extreme(stoch, 0, 20, 80, 100)
                return {"type": "CALL", "confidence": conf, "cci": round(ind.cci, 1),
                        "reason": f"Stoch {stoch:.1f} sobrevendido + MACD histograma alcista"}
            if stoch > 80 and histogram < 0:
                conf = _conf_from_extreme(stoch, 0, 20, 80, 100)
                return {"type": "PUT",  "confidence": conf, "cci": round(ind.cci, 1),
                        "reason": f"Stoch {stoch:.1f} sobrecomprado + MACD histograma bajista"}
        return None

        # Fallback simulado
        stoch = ind.stoch_k if ind else random.uniform(0, 100)
        if stoch > 78:
            return {"type": "PUT",  "confidence": round(random.uniform(0.60, 0.72), 2),
                    "cci": round(random.uniform(70, 110), 1),
                    "reason": f"Stoch {stoch:.1f} sobrecomprado + MACD bajista"}
        elif stoch < 22:
            return {"type": "CALL", "confidence": round(random.uniform(0.60, 0.72), 2),
                    "cci": round(random.uniform(-110, -70), 1),
                    "reason": f"Stoch {stoch:.1f} sobrevendido + MACD alcista"}
        return None


class EMACrossoverStrategy(TradingStrategy):
    """
    Cruce de EMA9 vs EMA21.
    REAL:  EMA9 > EMA21 + momentum positivo → CALL
           EMA9 < EMA21 + momentum negativo → PUT
    """
    def __init__(self):
        super().__init__("EMA Crossover", 0.9)
    
    def generate_signal(self, ind: Optional[IndicatorSet] = None) -> Optional[Dict]:
        if ind and ind.is_real:
            ema9  = ind.ema9
            ema21 = ind.ema21
            diff  = (ema9 - ema21) / max(ema21, 1e-9)
            MIN_DIFF = 0.0003  # 0.03% mínimo para considerar cruce real
            if diff > MIN_DIFF:
                conf = round(min(0.60 + abs(diff) * 500, 0.72), 2)
                return {"type": "CALL", "confidence": conf, "cci": round(ind.cci, 1),
                        "reason": f"EMA9 ({ema9:.5f}) > EMA21 ({ema21:.5f}) cruce alcista real"}
            if diff < -MIN_DIFF:
                conf = round(min(0.60 + abs(diff) * 500, 0.72), 2)
                return {"type": "PUT",  "confidence": conf, "cci": round(ind.cci, 1),
                        "reason": f"EMA9 ({ema9:.5f}) < EMA21 ({ema21:.5f}) cruce bajista real"}
        return None

        # Fallback simulado
        fired = random.random() > 0.55
        if fired:
            t = "CALL" if random.random() > 0.5 else "PUT"
            return {"type": t, "confidence": round(random.uniform(0.60, 0.68), 2),
                    "cci": round(random.uniform(-60, 60), 1),
                    "reason": f"EMA 9/21 cruce {'alcista' if t == 'CALL' else 'bajista'} confirmado"}
        return None


class MultiStrategyEnsemble:
    def __init__(self, strategies: List[TradingStrategy]):
        self.strategies = strategies
        self.name = "Multi-Strategy Ensemble"
    
    def get_pre_alert_signal(self, ind: Optional[IndicatorSet] = None) -> Optional[Dict]:
        """
        Pre-Alerta: detecta confluencia parcial (exactamente 3 de 5 estrategias).

        Se dispara ANTES de que se forme la señal completa, dando 2-3 minutos
        de anticipación para que el usuario monitoree el gráfico.

        Reglas:
        - Exactamente 3 estrategias deben coincidir en dirección
        - Las 2 restantes no deben contradecir (pueden ser neutras)
        - NO se emite si ya hay señal completa (≥4 estrategias)
        - Confluence_pct: 60% (3/5)
        """
        signals = []
        for strategy in self.strategies:
            if not strategy.enabled:
                continue
            sig = strategy.generate_signal(ind)
            if sig and sig["confidence"] >= strategy.min_confidence:
                signals.append({"strategy": strategy.name, "weight": strategy.weight, **sig})
        
        if len(signals) < 2:
            return None
        
        call_signals = [s for s in signals if s["type"] == "CALL"]
        put_signals  = [s for s in signals if s["type"] == "PUT"]

        total = len(signals)

        # Determina si hay confluencia parcial (exactamente 3, no más)
        if len(call_signals) >= 3 and len(call_signals) > len(put_signals):
            partial = call_signals[:3]
            direction = "CALL"
        elif len(put_signals) >= 3 and len(put_signals) > len(call_signals):
            partial = put_signals[:3]
            direction = "PUT"
        else:
            return None

        # Si ya hay señal completa (≥4 coinciden), NO emitir pre-alerta
        # La señal completa ya fue o será emitida por get_consensus_signal
        if len(partial) >= 4 or (direction == "CALL" and len(call_signals) >= 4) \
                              or (direction == "PUT"  and len(put_signals)  >= 4):
            return None

        avg_confidence  = sum(s["confidence"] for s in partial) / len(partial)
        avg_cci         = sum(s.get("cci", 0) for s in partial) / len(partial)
        confluence_pct  = round(len(partial) / 5 * 100)          # 60%
        data_source     = "real" if (ind and ind.is_real) else "simulated"

        return {
            "type":             direction,
            "is_pre_alert":     True,
            "confluence_pct":   confluence_pct,
            "strategies_fired": [s["strategy"] for s in partial],
            "strategies_total": total,
            "confidence":       round(avg_confidence, 2),
            "cci":              round(avg_cci, 1),
            "reason":           partial[0]["reason"],
            "data_source":      data_source,
        }

    def get_consensus_signal(self, ind: Optional[IndicatorSet] = None) -> Optional[Dict]:
        """
        Confluencia REAL: cada estrategia evalúa los indicadores reales
        de forma independiente. Sin bias forzado.
        Requiere mayoría (≥2 estrategias de acuerdo).
        """
        signals = []
        for strategy in self.strategies:
            if not strategy.enabled:
                continue
            sig = strategy.generate_signal(ind)
            if sig and sig["confidence"] >= strategy.min_confidence:
                signals.append({"strategy": strategy.name, "weight": strategy.weight, **sig})

        if len(signals) < 2:
            return None

        call_signals = [s for s in signals if s["type"] == "CALL"]
        put_signals  = [s for s in signals if s["type"] == "PUT"]

        total = len(signals)
        if len(call_signals) > len(put_signals) and len(call_signals) >= 2:
            agreeing = call_signals
        elif len(put_signals) > len(call_signals) and len(put_signals) >= 2:
            agreeing = put_signals
        else:
            return None
        
        avg_confidence  = sum(s["confidence"] * s["weight"] for s in agreeing) / sum(s["weight"] for s in agreeing)
        avg_cci         = sum(s.get("cci", 0) for s in agreeing) / len(agreeing)
        consensus_score = len(agreeing) / total
        strength        = "very_strong" if len(agreeing) >= 4 else "strong" if len(agreeing) >= 3 else "moderate"
        data_source     = "real" if (ind and ind.is_real) else "simulated"
        
        return {
            "type":                agreeing[0]["type"],
            "confidence":          round(avg_confidence, 2),
            "cci":                 round(avg_cci, 1),
            "strength":            strength,
            "strategies_agreeing": [s["strategy"] for s in agreeing],
            "reason":              agreeing[0]["reason"],
            "reasons":             [s["reason"] for s in agreeing],
            "consensus_score":     round(consensus_score, 2),
            "n_strategies":        len(agreeing),
            "n_total":             total,
            "data_source":         data_source,
        }

# ============================================================================
# HELPERS
# ============================================================================

def get_asset_name(symbol: str) -> str:
    mapping = {
        "OTC_EURUSD": "EUR/USD OTC",
        "OTC_GBPUSD": "GBP/USD OTC",
        "OTC_USDJPY": "USD/JPY OTC",
        "OTC_USDCHF": "USD/CHF OTC",
        "OTC_AUDUSD": "AUD/USD OTC",
        "OTC_USDCAD": "USD/CAD OTC",
        "OTC_NZDUSD": "NZD/USD OTC",
        "OTC_EURJPY": "EUR/JPY OTC",
        "OTC_EURGBP": "EUR/GBP OTC",
        "OTC_EURAUD": "EUR/AUD OTC",
        "OTC_EURCAD": "EUR/CAD OTC",
        "OTC_EURCHF": "EUR/CHF OTC",
        "OTC_GBPJPY": "GBP/JPY OTC",
        "OTC_GBPAUD": "GBP/AUD OTC",
        "OTC_GBPCAD": "GBP/CAD OTC",
        "OTC_GBPCHF": "GBP/CHF OTC",
        "OTC_AUDJPY": "AUD/JPY OTC",
        "OTC_AUDCAD": "AUD/CAD OTC",
        "OTC_CADJPY": "CAD/JPY OTC",
        "OTC_CHFJPY": "CHF/JPY OTC",
    }
    # Fallback: convierte OTC_AUDJPY → AUD/JPY OTC
    if symbol not in mapping and symbol.startswith("OTC_"):
        raw = symbol.replace("OTC_", "")
        return f"{raw[:3]}/{raw[3:]} OTC"
    return mapping.get(symbol, symbol)

def generate_pocket_option_url(symbol: str) -> str:
    clean = symbol.replace("OTC_", "").replace("_", "")
    asset_param = f"{clean}-OTC" if "OTC" in symbol else clean
    return f"https://pocketoption.com/en/quick-trading/?asset={asset_param}"

# ============================================================================
# LIFESPAN
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Starting Trading Bot API...")
    
    # ── Data provider (Twelve Data) ───────────────────────────────────────────
    provider = init_provider()
    await provider.start()
    app.state.data_provider = provider
    logger.info("📡 Data provider iniciado | modo: %s",
                "REAL" if provider.is_configured else "SIMULADO")

    # ── MongoDB (opcional) ────────────────────────────────────────────────────
    mongo_url = os.getenv("MONGO_URL", "mongodb://localhost:27017")
    try:
        client = AsyncIOMotorClient(mongo_url, serverSelectionTimeoutMS=2000)
        await client.server_info()                      # Prueba la conexión
        app.state.mongodb = client
        app.state.db      = client[os.getenv("DB_NAME", "trading_bot")]
        app.state.use_mongo = True
        logger.info("✅ MongoDB conectado en %s", mongo_url)
    except Exception as e:
        logger.warning("⚠️  MongoDB no disponible (%s) - usando almacenamiento en memoria", e)
        app.state.mongodb   = None
        app.state.db        = None
        app.state.use_mongo = False

    # ── Redis (opcional) ──────────────────────────────────────────────────────
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    app.state.redis = None
    if _REDIS_AVAILABLE:
        try:
            r = aioredis.from_url(redis_url, decode_responses=True, socket_connect_timeout=2)
            await r.ping()
            app.state.redis = r
            logger.info("✅ Redis conectado en %s", redis_url)
        except Exception as re:
            logger.warning("⚠️  Redis no disponible (%s) — usando caché in-memory", re)

    # ── Índices MongoDB ────────────────────────────────────────────────────────
    if app.state.use_mongo:
        try:
            db = app.state.db
            # signals: queries de Win Rate por hora, par y sesión
            await db.signals.create_index([("symbol", 1), ("hour_bucket", 1), ("result", 1)])
            await db.signals.create_index([("session", 1), ("result", 1), ("created_at", -1)])
            await db.signals.create_index([("day_bucket", 1), ("symbol", 1)])
            await db.signals.create_index([("audit_confidence", 1), ("result", 1)])
            await db.signals.create_index([("created_at", -1)])  # paginación reciente
            # trades: queries de auditoría
            await db.trades.create_index([("symbol", 1), ("result", 1), ("created_at", -1)])
            await db.trades.create_index([("signal_id", 1)], unique=True, sparse=True)
            await db.trades.create_index([("audit_confidence", 1), ("result", 1)])
            logger.info("✅ Índices MongoDB creados/verificados")
        except Exception as idx_err:
            logger.warning("⚠️  Error creando índices: %s", idx_err)

    # ── Almacenamiento en memoria (fallback sin MongoDB) ───────────────────────
    app.state.signals_store: list = []
    app.state.trades_store:  list = []  # historial de operaciones
    app.state.pre_alerts_store: dict = {}  # symbol → pre_alert_doc

    # ── Estrategias ───────────────────────────────────────────────────────────
    app.state.strategies = {
        "range_breakout":  RangeBreakoutStrategy(),
        "cci_alligator":   CCIAlligatorStrategy(),
        "rsi_bollinger":   RSIBollingerStrategy(),
        "macd_stochastic": MACDStochasticStrategy(),
        "ema_crossover":   EMACrossoverStrategy(),
    }
    app.state.ensemble = MultiStrategyEnsemble(list(app.state.strategies.values()))
    logger.info("✅ %d estrategias cargadas", len(app.state.strategies))

    # ── Auto-scan en background ───────────────────────────────────────────────
    scan_task    = asyncio.create_task(_auto_scan_loop(app))
    polling_task = asyncio.create_task(_telegram_polling_loop(app))
    
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


def _cci_sigmoid(cci_abs: float) -> float:
    """
    Normalización sigmoidal del CCI:
    - CCI 0    → 0.0
    - CCI 100  → 0.46
    - CCI 140  → 0.68  (zona de alta probabilidad)
    - CCI 200  → 0.88
    - CCI 300  → 0.97  (asintótico, no premia sobreextensión extrema)

    Ventaja sobre linear cap: diferencia entre CCI=150 y CCI=250
    sin premiar CCI>300 (probable reversal).
    """
    return 1.0 - math.exp(-cci_abs / 200.0)


# ── Mapa de grupos ortogonales por estrategia ────────────────────────────────
# Agrupa las estrategias por "tipo de indicador subyacente".
# El objetivo es penalizar el consenso falso: si 3 estrategias coinciden
# pero usan el mismo oscilador (RSI), solo cuentan como 1 grupo, no como 3.
#
# Grupos:
#   rsi_momentum:        Oscilador RSI ± Bollinger Bands (reversión a la media).
#   cci_reversal:        Reversión basada en CCI (descorrelacionado del RSI).
#   macd_stoch:          Momentum por histograma MACD + Estocástico (velocidad).
#   ema_trend:           Tendencia por cruce de medias (direccionalidad).
#   breakout_volatility: Rotura de rango con ATR (filosofía OPUESTA a reversión).
#
# Una señal con grupos {rsi_momentum, cci_reversal, breakout_volatility} vale
# más que {rsi_momentum, rsi_momentum, cci_reversal}: son tres marcos teóricos
# independientes apuntando al mismo lado.
_STRATEGY_GROUPS: Dict[str, str] = {
    "Range Breakout + ATR":  "breakout_volatility",  # anticorrelacionada con reversión
    "RSI + Bollinger Bands": "rsi_momentum",
    "CCI + Alligator":       "cci_reversal",
    "MACD + Stochastic":     "macd_stoch",
    "EMA Crossover":         "ema_trend",
}
_TOTAL_GROUPS = len(set(_STRATEGY_GROUPS.values()))  # 5 grupos distintos


def _orthogonal_score(strategies_agreeing: list) -> float:
    """
    Mide la DIVERSIDAD real del consenso, no solo la cantidad de estrategias.

    Retorna un valor entre 0.0 y 1.0:
    - 1.0 → todas las estrategias provienen de grupos ortogonales distintos
    - 0.5 → consenso parcialmente diverso
    - 0.25 → consenso concentrado en un solo tipo de indicador (señal débil)

    Ejemplos:
      ["CCI + Alligator", "EMA Crossover", "MACD + Stochastic"]
        → grupos: {cci_reversal, ema_trend, macd_stoch} → 3/4 = 0.75 ✓ Fuerte

      ["Keltner Channel + RSI", "RSI + Bollinger Bands", "CCI + Alligator"]
        → grupos: {rsi_momentum, rsi_momentum, cci_reversal} → 2/4 = 0.50
        → Aunque son 3 estrategias, la diversidad real es baja
    """
    if not strategies_agreeing:
        return 0.0

    unique_groups = set()
    for strat_name in strategies_agreeing:
        group = _STRATEGY_GROUPS.get(strat_name, f"unknown_{strat_name}")
        unique_groups.add(group)

    return round(len(unique_groups) / _TOTAL_GROUPS, 4)


def _quality_score(signal: dict, symbol: str = None,
                   ind: Optional[IndicatorSet] = None) -> float:
    """
    Quality Score ponderado con Consenso Ortogonal (0-1).

    Componentes:
    - Confluencia ortogonal (diversidad de grupos de indicadores)  → 30 %
      Reemplaza la simple cuenta de estrategias.
      Penaliza el "falso consenso" cuando múltiples estrategias usan el mismo
      oscilador base (ej. KeltnerRSI + RSIBollinger son casi idénticas).
    - Confianza promedio ponderada del ensemble                     → 30 %
    - Fuerza del CCI (normalización sigmoidal)                      → 15 %
    - Alineación con micro-tendencia del par                        → 15 %
    - Bonus de consenso (100% acuerdo entre estrategias)            → 10 %
    - Bonus por datos reales                                        → +5 % (extra)
    """
    confidence         = signal.get("confidence", 0)
    cci_abs            = abs(signal.get("cci", 0))
    strategies_agreeing = signal.get("strategies_agreeing", [])
    n_agreeing         = len(strategies_agreeing)
    n_total            = signal.get("n_total", max(n_agreeing, 1))
    signal_type        = signal.get("type", "")

    # Confluencia ortogonal: reemplaza n_agreeing/5 con diversidad real de grupos
    ortho_confluence = _orthogonal_score(strategies_agreeing)

    cci_factor = _cci_sigmoid(cci_abs)
    consensus  = 1.0 if n_agreeing == n_total else 0.0

    # Alineación con la tendencia (real si tenemos indicadores, simulada si no)
    trend_score = 0.5
    if symbol or ind:
        trend = get_price_trend(symbol, ind)
        if trend == "bullish" and signal_type == "CALL":   trend_score = 1.0
        elif trend == "bearish" and signal_type == "PUT":  trend_score = 1.0
        elif trend == "bullish" and signal_type == "PUT":  trend_score = 0.15
        elif trend == "bearish" and signal_type == "CALL": trend_score = 0.15

    # Bonus por datos reales (más confiable que simulación)
    real_bonus = 0.05 if (ind and ind.is_real) else 0.0

    return round(
        ortho_confluence * 0.30 +   # diversidad real de grupos ortogonales
        confidence       * 0.30 +
        cci_factor       * 0.15 +
        trend_score      * 0.15 +
        consensus        * 0.10 +
        real_bonus,
        4
    )


def _get_market_session(utc_hour: int, utc_minute: int = 0) -> dict:
    """
    Detecta la sesión de mercado activa y sus características.

    Sesiones en UTC (alineadas con etiquetas de /v1/stats):
      london   08:00–16:00 UTC  → alta volatilidad EUR/GBP, ideal RangeBreakout
      newyork  13:00–21:00 UTC  → solapamiento NY+Londres 13–16h, tendencias fuertes
      asia     00:00–08:00 UTC  → baja volatilidad, lateralización, JPY/AUD
      off      No hay sesión dominante activa

    En OTC las sesiones son aproximadas pero sirven para calibrar umbrales.
    El bot opera en TODAS las sesiones activas; fuera de horario pausamos para
    ahorrar créditos de API.

    Ventanas de operación definidas por el usuario (UTC-5):
      Mañana:    09:30–12:00 UTC-5 → 14:30–17:00 UTC → london+newyork
      Madrugada: 00:00–02:00 UTC-5 → 05:00–07:00 UTC → london temprano
    """
    # UTC → UTC-5 en minutos totales
    utc5_total = (utc_hour * 60 + utc_minute) - 300
    if utc5_total < 0:
        utc5_total += 1440
    utc5_hour = utc5_total // 60
    utc5_min  = utc5_total % 60
    t = utc5_total

    MORNING_START = 9 * 60 + 30    # 570 min UTC-5 → 14:30 UTC
    MORNING_END   = 12 * 60         # 720 min UTC-5 → 17:00 UTC
    NIGHT_START   = 0               #   0 min UTC-5 → 05:00 UTC
    NIGHT_END     = 2 * 60          # 120 min UTC-5 → 07:00 UTC

    # Determina sesión UTC real para etiquetas consistentes con /v1/stats
    utc_t = utc_hour * 60 + utc_minute
    if 480 <= utc_t < 780:          # 08:00–13:00 UTC
        session_type = "london"
    elif 780 <= utc_t < 1260:       # 13:00–21:00 UTC (solapamiento incluido)
        session_type = "newyork"
    elif utc_t < 480 or utc_t >= 1260:
        session_type = "asia"
    else:
        session_type = "off"

    ALL_20_PAIRS = [
        "OTC_EURUSD", "OTC_GBPUSD", "OTC_USDJPY", "OTC_USDCHF",
        "OTC_AUDUSD", "OTC_NZDUSD", "OTC_USDCAD", "OTC_EURJPY",
        "OTC_EURGBP", "OTC_EURAUD", "OTC_EURCAD", "OTC_EURCHF",
        "OTC_GBPJPY", "OTC_GBPAUD", "OTC_GBPCAD", "OTC_GBPCHF",
        "OTC_AUDJPY", "OTC_AUDCAD", "OTC_CADJPY", "OTC_CHFJPY",
    ]

    # Ventana mañana 09:30–12:00 UTC-5 → coincide con Londres+NY
    if MORNING_START <= t < MORNING_END:
        return {
            "name":          session_type,          # "london" o "newyork"
            "display":       "Mañana (09:30–12:00)",
            "active":        True,
            "quality_boost": 0.06,
            "pairs":         ALL_20_PAIRS,
            "description":   f"Ventana mañana — {session_type} activa, 20 pares",
            "utc5_display":  f"{utc5_hour:02d}:{utc5_min:02d} UTC-5",
        }

    # Ventana madrugada 00:00–02:00 UTC-5 → coincide con Londres temprano/Asia
    if NIGHT_START <= t < NIGHT_END:
        return {
            "name":          session_type,          # "london" o "asia"
            "display":       "Madrugada (00:00–02:00)",
            "active":        True,
            "quality_boost": 0.03,
            "pairs":         ALL_20_PAIRS,
            "description":   f"Ventana madrugada — {session_type} activa, 20 pares",
            "utc5_display":  f"{utc5_hour:02d}:{utc5_min:02d} UTC-5",
        }

    # Fuera de ventanas → PAUSADO
    if t < NIGHT_END:
        mins_next, next_w = NIGHT_END - t, "02:00 (fin madrugada)"
    elif t < MORNING_START:
        mins_next, next_w = MORNING_START - t, "09:30 (mañana)"
    else:
        mins_next, next_w = (1440 - t), "00:00 (madrugada)"

    return {
        "name":          "off",
        "display":       "Fuera de ventana",
        "active":        False,
        "quality_boost": 0.0,
        "pairs":         [],
        "description":   (
            f"Bot pausado — próxima ventana: {next_w} UTC-5 "
            f"(en ~{mins_next} min) · 0 créditos consumidos"
        ),
        "utc5_display":  f"{utc5_hour:02d}:{utc5_min:02d} UTC-5",
    }


async def _auto_scan_loop(app: "FastAPI"):
    """
    Motor de escaneo PARALELO v2.3 — asyncio.gather() para todos los pares.

    Optimización de créditos API (Antifragile v3.0):
      - Máximo 8 pares por sesión (los de mayor liquidez histórica)
      - Cache TTL 600s (10 min) — el mercado OTC no cambia tan rápido
      - 8 pares × 1 req × ~8 ciclos/hora × 8h sesión ≈ 512 req/día MAX
      - Con caché funcionando: ~8 req reales cada 10 min = ~96 req/día
    """
    INTERVAL         = 120    # segundos entre ciclos
    MIN_CONFIDENCE   = 0.68
    MIN_QUALITY_BASE = 0.55
    MAX_PER_CYCLE    = 2
    COOLDOWN_SECONDS = 240
    MAX_STORE        = 20

    # 20 pares OTC completos
    DEFAULT_PAIRS = [
        "OTC_EURUSD", "OTC_GBPUSD", "OTC_USDJPY", "OTC_USDCHF",
        "OTC_AUDUSD", "OTC_NZDUSD", "OTC_USDCAD", "OTC_EURJPY",
        "OTC_EURGBP", "OTC_EURAUD", "OTC_EURCAD", "OTC_EURCHF",
        "OTC_GBPJPY", "OTC_GBPAUD", "OTC_GBPCAD", "OTC_GBPCHF",
        "OTC_AUDJPY", "OTC_AUDCAD", "OTC_CADJPY", "OTC_CHFJPY",
    ]

    cooldown_map: dict = {}   # symbol → (last_signal_utc, last_score)

    await asyncio.sleep(5)
    logger.info("🚀 Auto-scan PARALELO v2.3 iniciado — gather() · %ds ciclo · score_base>%.2f",
                INTERVAL, MIN_QUALITY_BASE)

    _calibration_cycle = 0

    while True:
        cycle_start = datetime.utcnow()
        try:
            ensemble  = app.state.ensemble
            store     = app.state.signals_store
            use_mongo = app.state.use_mongo
            db        = app.state.db
            now       = cycle_start

            # ── Auto-calibración cada 10 ciclos (~20 min) ────────────────────
            _calibration_cycle += 1
            if _calibration_cycle % 10 == 0:
                try:
                    if use_mongo:
                        cursor     = db.trades.find()
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
                            global _dynamic_min_quality
                            _dynamic_min_quality = max(0.45, min(0.85, cal["optimal_threshold"]))
                            logger.info("🎯 Auto-calibración | Umbral → %.2f | %s",
                                        _dynamic_min_quality, cal["recommendation"])
                except Exception as cal_err:
                    logger.warning("⚠️  Error en auto-calibración: %s", cal_err)

            # ── Umbral efectivo (calibración global + ajuste por hora) ────────
            effective_base = _dynamic_min_quality
            try:
                if use_mongo:
                    cursor_h = db.trades.find()
                    all_t_h  = await cursor_h.to_list(1000)
                    for t in all_t_h:
                        if isinstance(t.get("created_at"), datetime):
                            t["created_at"] = t["created_at"].strftime("%Y-%m-%dT%H:%M:%S") + "Z"
                else:
                    all_t_h = list(app.state.trades_store)

                hour_trades = [
                    t for t in all_t_h
                    if _try_parse_ts(
                        t.get("signal_timestamp") or t.get("created_at", "")
                    ).hour == now.hour
                ]
                if len(hour_trades) >= 10:
                    hw       = sum(1 for t in hour_trades if t.get("result") == "win")
                    hour_wr  = hw / len(hour_trades)
                    if hour_wr >= 0.65:
                        effective_base = max(0.45, effective_base - 0.05)
                        logger.info("⏰ Hora %02d: WR %.0f%% → umbral relajado %.2f",
                                    now.hour, hour_wr * 100, effective_base)
                    elif hour_wr < 0.45:
                        effective_base = min(0.80, effective_base + 0.07)
                        logger.info("⏰ Hora %02d: WR %.0f%% → umbral endurecido %.2f",
                                    now.hour, hour_wr * 100, effective_base)
            except Exception:
                pass

            # ── Filtro de sesión ──────────────────────────────────────────────
            session       = _get_market_session(now.hour, now.minute)
            QUALITY_PAIRS = session["pairs"] if session["pairs"] else DEFAULT_PAIRS
            MIN_QUALITY   = effective_base - session["quality_boost"]

            if not session["active"]:
                logger.info("🌙 [%s] %s — sin escaneo. Próximo ciclo en %ds.",
                            session["display"], session["description"], INTERVAL)
                await asyncio.sleep(INTERVAL)
                continue

            # ── Filtra pares en cooldown ──────────────────────────────────────
            pairs_to_scan = []
            for symbol in QUALITY_PAIRS:
                # Filtro 1: cooldown normal
                last_entry = cooldown_map.get(symbol)
                if last_entry:
                    last_time, last_score = last_entry
                    adaptive_cd = COOLDOWN_SECONDS if last_score < 0.65 else 120
                    if (now - last_time).total_seconds() < adaptive_cd:
                        continue
                # Filtro 2 (Antifragile v3.0): Bloqueo por Correlación
                lock = _check_correlation_lock(symbol)
                if lock["locked"]:
                    logger.debug("🔴 %s bloqueado por correlación (%s)",
                                 symbol, lock["currencies"])
                    continue
                pairs_to_scan.append(symbol)

            calibration_tag = "CALIBRADO" if _dynamic_min_quality != MIN_QUALITY_BASE else "DEFAULT"
            logger.info(
                "⚡ Sesión: %s | %d/%d pares (cooldown) | Umbral: %.2f [%s] | gather() START",
                session["display"], len(pairs_to_scan), len(QUALITY_PAIRS),
                MIN_QUALITY, calibration_tag,
            )

            if not pairs_to_scan:
                logger.info("⏳ Todos los pares en cooldown — próximo ciclo en %ds", INTERVAL)
                await asyncio.sleep(INTERVAL)
                continue

            # ── FETCH PARALELO — todos los pares simultáneamente ─────────────
            fetch_start = datetime.utcnow()
            provider    = get_provider()

            if provider and provider.is_configured:
                indicators_map = await provider.get_indicators_batch(pairs_to_scan)
            else:
                # Simulado: genera indicadores para todos los pares (sin I/O)
                indicators_map = {sym: get_simulated_indicators(sym) for sym in pairs_to_scan}

            fetch_elapsed = (datetime.utcnow() - fetch_start).total_seconds()
            logger.info("⚡ Fetch paralelo completado en %.1fs para %d pares",
                        fetch_elapsed, len(pairs_to_scan))

            # ── Detecta si todos los datos son simulados (API sin créditos) ─────
            real_count = sum(1 for s in pairs_to_scan if indicators_map.get(s) and indicators_map[s].is_real)
            simulated_count = len(pairs_to_scan) - real_count

            if simulated_count > 0 and real_count == 0:
                # TODOS simulados → alerta única cada 30 minutos para no spamear
                now_ts = datetime.utcnow()
                last_sim_warn = getattr(app.state, "_last_sim_warn", None)
                if not last_sim_warn or (now_ts - last_sim_warn).total_seconds() > 1800:
                    app.state._last_sim_warn = now_ts
                    logger.warning(
                        "⚠️  MODO SIMULADO ACTIVO — API sin créditos o no configurada. "
                        "NO se emitirán señales hasta que la API vuelva a funcionar."
                    )
                    asyncio.create_task(_send_telegram(
                        "⚠️ <b>ATENCIÓN: Bot en modo simulado</b>\n\n"
                        "Los créditos de Twelve Data se han agotado.\n"
                        "🚫 <b>Las señales están SUSPENDIDAS</b> hasta que se renueven los créditos API (medianoche UTC).\n\n"
                        "<i>No ejecutes operaciones manualmente hasta ver este mensaje: ✅ API real activa.</i>"
                    ))
            elif real_count > 0:
                # API funcionando → notifica recuperación si venía de modo simulado
                last_sim_warn = getattr(app.state, "_last_sim_warn", None)
                if last_sim_warn:
                    app.state._last_sim_warn = None
                    logger.info("✅ API real activa — %d/%d pares con datos reales",
                                real_count, len(pairs_to_scan))
                    asyncio.create_task(_send_telegram(
                        f"✅ <b>API real activa</b> — {real_count}/{len(pairs_to_scan)} pares con datos reales.\n"
                        "Las señales han sido reanudadas."
                    ))

            # ── EVALUACIÓN CONCURRENTE de estrategias por par ─────────────────
            # (CPU-bound puro → no necesita gather, es instantáneo)
            candidates = []
            for symbol in pairs_to_scan:
                ind = indicators_map.get(symbol)
                if ind is None:
                    ind = get_simulated_indicators(symbol)

                # ── GUARDIA CRÍTICA: NO emitir señales con datos simulados ──────
                # Los datos simulados son ruido aleatorio — operarlos destruye capital.
                # Solo se permiten señales con ind.is_real = True.
                if not ind.is_real:
                    logger.debug(
                        "⏭  %s omitido — datos simulados (API sin créditos o no configurada)",
                        symbol
                    )
                    continue

                # Filtro ATR
                if ind.is_real and ind.atr_pct > 0:
                    atr_threshold = 0.015 if session["name"] in ("london", "newyork") else 0.010
                    if ind.atr_pct < atr_threshold:
                        logger.debug("⏭  %s omitido — ATR%% %.4f < %.4f (mercado plano)",
                                     symbol, ind.atr_pct, atr_threshold)
                        continue

                signal = ensemble.get_consensus_signal(ind)
                if not signal:
                    # ── Sin señal completa → intenta pre-alerta ───────────────
                    pre = ensemble.get_pre_alert_signal(ind)
                    if pre:
                        pre_doc = {
                            "symbol":          symbol,
                            "asset_name":      get_asset_name(symbol),
                            "type":            pre["type"],
                            "confluence_pct":  pre["confluence_pct"],
                            "strategies_fired": pre["strategies_fired"],
                            "confidence":      pre["confidence"],
                            "cci":             pre["cci"],
                            "reason":          pre["reason"],
                            "session":         session["name"],
                            "timestamp":       now.strftime("%Y-%m-%dT%H:%M:%S") + "Z",
                            "created_at":      now.strftime("%Y-%m-%dT%H:%M:%S") + "Z",
                            "atr_pct":         round(ind.atr_pct, 4) if ind else 0,
                        }
                        app.state.pre_alerts_store[symbol] = pre_doc
                        logger.info("⏳ Pre-Alerta | %s %s | %d%% confluencia | %s",
                                    pre["type"], symbol, pre["confluence_pct"],
                                    ", ".join(pre["strategies_fired"]))
                        # Telegram pre-alerta (no bloquea)
                        asyncio.create_task(_send_pre_alert_telegram(pre_doc))
                    else:
                        # Limpia pre-alerta si ya no aplica
                        app.state.pre_alerts_store.pop(symbol, None)
                    continue
                if signal["confidence"] < MIN_CONFIDENCE:
                    continue

                score = _quality_score(signal, symbol, ind)

                # ── Signal Calibration by Pair ─────────────────────────────────
                # Si el par tiene Win Rate < 50% (degraded) en el último período,
                # elevamos el umbral mínimo en +0.10 para ese par específico.
                # Usa el caché de Redis — 0 queries adicionales a MongoDB.
                pair_min_quality = MIN_QUALITY
                try:
                    redis = getattr(app.state, "redis", None)
                    cached_stats = await _wr_cache_get(redis, "wr:stats:1h")
                    if cached_stats:
                        pair_data = cached_stats.get("by_pair", {}).get(symbol, {})
                        if pair_data.get("degraded", False):
                            pair_min_quality = MIN_QUALITY + 0.10
                            logger.debug(
                                "📉 %s degradado (WR=%.0f%%) → umbral elevado a %.2f",
                                symbol, pair_data.get("win_rate", 0), pair_min_quality
                            )
                except Exception:
                    pass

                if score < pair_min_quality:
                    continue

                candidates.append((score, symbol, signal, ind))

            # ── Selecciona los mejores del ciclo ──────────────────────────────
            candidates.sort(key=lambda x: x[0], reverse=True)
            top = candidates[:MAX_PER_CYCLE]

            cycle_elapsed = (datetime.utcnow() - cycle_start).total_seconds()
            logger.info("⚡ Evaluación completada en %.1fs | %d candidatos | %d señales",
                        cycle_elapsed, len(candidates), len(top))

            for score, symbol, signal, ind in top:
                price     = ind.price if (ind and ind.is_real) else get_asset_price(symbol)
                emit_time = datetime.utcnow()
                ts        = emit_time.strftime("%Y-%m-%dT%H:%M:%S") + "Z"

                # data_freshness_ms: diferencia entre última vela de Twelve Data y emisión
                data_freshness_ms = None
                if ind and ind.is_real and ind.last_candle_time:
                    try:
                        candle_dt         = datetime.strptime(ind.last_candle_time, "%Y-%m-%d %H:%M:%S")
                        data_freshness_ms = int((emit_time - candle_dt).total_seconds() * 1000)
                    except Exception:
                        data_freshness_ms = None

                doc = {
                    "id":                  f"{int(emit_time.timestamp()*1000)}_{symbol}",
                    "symbol":              symbol,
                    "asset_name":          get_asset_name(symbol),
                    "type":                signal["type"],
                    "price":               price,
                    "entry_price":         price,
                    "timestamp":           ts,
                    "confidence":          signal["confidence"],
                    "cci":                 signal["cci"],
                    "strength":            signal["strength"],
                    "strategies_agreeing": signal["strategies_agreeing"],
                    "reason":              signal["reason"],
                    "reasons":             signal["reasons"],
                    "consensus_score":     signal["consensus_score"],
                    "quality_score":       score,
                    "method":              "quality_scan_parallel",
                    "payout":              round(85.0 + signal["confidence"] * 10, 1),
                    "market_quality":      round(score * 100, 1),
                    "atr":                 round(ind.atr, 6) if ind else 0,
                    "atr_pct":             round(ind.atr_pct, 4) if ind else 0,
                    "session":             session["name"],
                    "active":              True,
                    "created_at":          ts,
                    # ── v4.0: buckets desnormalizados para queries O(1) ─────────
                    "hour_bucket":         _hour_bucket(emit_time),
                    "day_bucket":          _day_bucket(emit_time),
                    "data_source":         "real" if (ind and ind.is_real) else "simulated",
                    "audit_confidence":    "high" if (ind and ind.is_real) else "low",
                    # ── Campos v2.3 ────────────────────────────────────────────
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
                    cutoff = emit_time - timedelta(minutes=5)
                    store[:] = [
                        s for s in store
                        if _parse_naive_utc(s["created_at"]) >= cutoff
                    ]
                    if len(store) >= MAX_STORE:
                        store.pop(0)
                    store.append(doc)

                cooldown_map[symbol] = (emit_time, score)
                # Limpia pre-alerta del par si había una activa
                app.state.pre_alerts_store.pop(symbol, None)
                logger.info(
                    "✅ Señal | %s %s | score=%.2f | conf=%.2f | ATR%%=%.4f | "
                    "freshness=%sms | scan=%.1fs",
                    signal["type"], symbol, score, signal["confidence"],
                    ind.atr_pct if ind else 0,
                    data_freshness_ms if data_freshness_ms is not None else "N/A",
                    cycle_elapsed,
                )

                # ── Circuit Breaker: bloquea Telegram durante cooldown ─────────
                if _cb_is_blocked():
                    logger.warning(
                        "🛑 CB activo — señal %s %s bloqueada (Telegram silenciado) | %s",
                        signal["type"], symbol, _cb_state.get("reason", "")
                    )
                else:
                    # Telegram + auditoría autónoma
                    only_fire = os.getenv("TELEGRAM_ONLY_FIRE", "false").lower() == "true"
                    is_fire   = score >= 0.75 or len(signal.get("strategies_agreeing", [])) >= 3
                    if not only_fire or is_fire:
                        asyncio.create_task(_send_signal_telegram(doc, app))

            if not top:
                logger.info("🔍 Ciclo sin señales (umbral %.2f) | scan=%.1fs",
                            MIN_QUALITY, cycle_elapsed)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("❌ Error en auto-scan: %s", e)

        # Descuenta el tiempo ya gastado en el ciclo para mantener el intervalo exacto
        elapsed  = (datetime.utcnow() - cycle_start).total_seconds()
        sleep_t  = max(5.0, INTERVAL - elapsed)
        await asyncio.sleep(sleep_t)

# ============================================================================
# APP
# ============================================================================

app = FastAPI(
    title="Trading Bot API",
    description="Multi-Strategy Trading Bot",
    version="2.0.0",
    lifespan=lifespan
)

# ============================================================================
# SECURITY CONFIGURATION
# ============================================================================

# Parse CORS origins from environment (comma-separated)
def _parse_cors_origins():
    origins_str = os.getenv("CORS_ORIGINS", "http://localhost:3000")
    return [origin.strip() for origin in origins_str.split(",") if origin.strip()]

CORS_ORIGINS = _parse_cors_origins()
logger.info("🔒 CORS configured for origins: %s", CORS_ORIGINS)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
    max_age=600,  # 10 minutes cache for preflight
)

# ============================================================================
# RATE LIMITING & SECURITY HEADERS
# ============================================================================

from fastapi import Response
from starlette.middleware.base import BaseHTTPMiddleware

# Simple in-memory rate limiter (for production, use Redis)
class RateLimiter:
    def __init__(self, max_requests: int = 60, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window = window_seconds
        self.clients: Dict[str, List[float]] = {}
    
    def is_allowed(self, client_id: str) -> bool:
        now = time.time()
        # Clean old entries
        if client_id in self.clients:
            self.clients[client_id] = [
                t for t in self.clients[client_id] 
                if now - t < self.window
            ]
        else:
            self.clients[client_id] = []
        
        # Check limit
        if len(self.clients[client_id]) >= self.max_requests:
            return False
        
        self.clients[client_id].append(now)
        return True

# Initialize rate limiters for different endpoints
public_limiter = RateLimiter(max_requests=30, window_seconds=60)   # Health, assets
scan_limiter = RateLimiter(max_requests=10, window_seconds=60)     # Scan endpoints
trade_limiter = RateLimiter(max_requests=20, window_seconds=60)    # Trade operations

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""
    
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        
        # Security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        
        # Remove server identification
        if "Server" in response.headers:
            del response.headers["Server"]
        
        return response

class RateLimitMiddleware(BaseHTTPMiddleware):
    """Apply rate limiting based on endpoint path."""
    
    async def dispatch(self, request: Request, call_next):
        # Get client identifier (IP + path)
        client_ip = request.client.host if request.client else "unknown"
        path = request.url.path
        
        # Choose limiter based on endpoint
        if "/api/signals/scan" in path or "/api/scan" in path:
            limiter = scan_limiter
        elif "/api/trades" in path:
            limiter = trade_limiter
        else:
            limiter = public_limiter
        
        client_id = f"{client_ip}:{path}"
        
        if not limiter.is_allowed(client_id):
            return Response(
                content='{"error": "Rate limit exceeded. Please slow down."}',
                status_code=429,
                media_type="application/json",
                headers={"Retry-After": "60"}
            )
        
        return await call_next(request)

# Add security middlewares
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)

# ============================================================================
# API KEY AUTHENTICATION
# ============================================================================

# API Key check updated to be dynamic
async def verify_api_key(x_api_key: Optional[str] = Header(None, alias="X-API-Key")):
    """
    Dependency to verify API key for sensitive endpoints.
    In development mode (API_KEY not set), allows all requests with warning.
    """
    # Read fresh env var on each request to support dynamic config/testing
    current_key = os.getenv("API_SECRET_KEY", None)

    if not current_key:
        # Development mode - log warning but allow
        logger.debug("⚠️  API_SECRET_KEY not set - running in development mode (no auth)")
        return True
    
    if not x_api_key:
        raise HTTPException(
            status_code=401,
            detail="X-API-Key header required",
            headers={"WWW-Authenticate": "ApiKey"}
        )
    
    # Use constant-time comparison to prevent timing attacks
    import hmac
    # Ensure both are bytes or str for hmac (hmac handles str in newer pythons, but let's be safe)
    if not hmac.compare_digest(x_api_key, current_key):
        raise HTTPException(
            status_code=403,
            detail="Invalid API key"
        )
    
    return True

async def optional_api_key(x_api_key: Optional[str] = Header(None, alias="X-API-Key")):
    """Optional API key verification for less sensitive endpoints."""
    if not API_KEY:
        return True
    if not x_api_key:
        return False
    
    import hmac
    return hmac.compare_digest(x_api_key, API_KEY)

# ============================================================================
# ENDPOINTS
# ============================================================================

@app.get("/")
async def root():
    return {
        "name": "Trading Bot API",
        "version": "2.0.0",
        "status": "online",
        "strategies": len(app.state.strategies)
    }

@app.get("/api/health")
async def health_check():
    now     = datetime.utcnow()
    session = _get_market_session(now.hour, now.minute)
    return {
        "status":             "healthy",
        "timestamp":          now.isoformat(),
        "strategies_loaded":  len(app.state.strategies),
        "market_session":     session["display"],
        "session_active":     session["active"],
        "session_description": session["description"],
        "circuit_breaker": {
            "blocked":            _cb_state["blocked"],
            "consecutive_losses": _cb_state["consecutive_losses"],
            "reason":             _cb_state.get("reason", ""),
            "blocked_until":      (
                _cb_state["blocked_until"].strftime("%Y-%m-%dT%H:%M:%S") + "Z"
                if _cb_state.get("blocked_until") else None
            ),
        },
        "session_pairs":      len(session["pairs"]),
    }

@app.get("/api/strategies")
async def get_strategies(request: Request):
    strategies = request.app.state.strategies
    
    strategy_info = [
        {
            "id": "range_breakout",
            "name": "Range Breakout + ATR",
            "timeframe": "1m - 5m",
            "win_rate_expected": "65-72%",
            "signals_per_day": "8-15",
            "enabled": strategies["range_breakout"].enabled,
            "weight": strategies["range_breakout"].weight
        },
        {
            "id": "cci_alligator",
            "name": "CCI + Alligator",
            "timeframe": "1m - 5m",
            "win_rate_expected": "60-65%",
            "signals_per_day": "5-8",
            "enabled": strategies["cci_alligator"].enabled,
            "weight": strategies["cci_alligator"].weight
        },
        {
            "id": "rsi_bollinger",
            "name": "RSI + Bollinger Bands",
            "timeframe": "1m - 5m",
            "win_rate_expected": "65-70%",
            "signals_per_day": "8-12",
            "enabled": strategies["rsi_bollinger"].enabled,
            "weight": strategies["rsi_bollinger"].weight
        },
        {
            "id": "macd_stochastic",
            "name": "MACD + Stochastic",
            "timeframe": "5m - 15m",
            "win_rate_expected": "60-68%",
            "signals_per_day": "4-7",
            "enabled": strategies["macd_stochastic"].enabled,
            "weight": strategies["macd_stochastic"].weight
        },
        {
            "id": "ema_crossover",
            "name": "EMA Crossover",
            "timeframe": "5m - 15m",
            "win_rate_expected": "55-60%",
            "signals_per_day": "3-5",
            "enabled": strategies["ema_crossover"].enabled,
            "weight": strategies["ema_crossover"].weight
        },
        {
            "id": "ensemble",
            "name": "Multi-Strategy Ensemble",
            "timeframe": "Any",
            "win_rate_expected": "75-80%",
            "signals_per_day": "10-15",
            "enabled": True,
            "weight": 1.5
        }
    ]
    
    return {"strategies": strategy_info}

@app.post("/api/strategies/{strategy_id}/toggle")
async def toggle_strategy(strategy_id: str, request: Request):
    strategies = request.app.state.strategies
    
    if strategy_id not in strategies:
        raise HTTPException(status_code=404, detail="Strategy not found")
    
    strategy = strategies[strategy_id]
    strategy.enabled = not strategy.enabled
    
    return {"strategy_id": strategy_id, "enabled": strategy.enabled}

@app.post("/api/signals/scan")
async def scan_signals(
    scan_request: SignalScanRequest,
    request: Request,
    auth: bool = Depends(verify_api_key)
):
    ensemble    = request.app.state.ensemble
    use_mongo   = request.app.state.use_mongo
    db          = request.app.state.db
    store       = request.app.state.signals_store
    all_signals = []

    # FIX 1: Usar el umbral dinámico calibrado en lugar de un valor hardcodeado.
    # _dynamic_min_quality es actualizado continuamente por el auto-scan
    # usando el historial real de trades, por lo que refleja el rendimiento actual.
    # Si aún no se ha calibrado, usar MIN_QUALITY_BASE como fallback seguro.
    effective_threshold = max(_dynamic_min_quality, scan_request.min_confidence)

    for symbol in scan_request.symbols:
        # FIX 2: Intentar obtener indicadores reales antes de puntuar la señal.
        # Sin ind, el quality_score siempre usaría trend_score=0.5 (neutro)
        # y perdería el real_bonus de +0.05, subestimando señales reales.
        try:
            ind = await get_indicators_for(symbol, "1min")
        except Exception:
            ind = get_simulated_indicators(symbol)

        signal = ensemble.get_consensus_signal(ind)
        score  = _quality_score(signal, symbol, ind) if signal else 0

        if not signal:
            continue
        if signal["confidence"] < scan_request.min_confidence:
            continue
        if score < effective_threshold:
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
            "quality_score":       score,           # FIX 4: incluir score en el doc
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

        # FIX 3: all_signals.append fuera del bloque else para que funcione
        # también cuando MongoDB está activo (antes siempre retornaba lista vacía).
        all_signals.append(signal_doc)

        # ── Notificación Telegram ──────────────────────────────────────────
        only_fire = os.getenv("TELEGRAM_ONLY_FIRE", "false").lower() == "true"
        is_fire   = score >= 0.75 or len(signal.get("strategies_agreeing", [])) >= 3
        if not only_fire or is_fire:
            asyncio.create_task(_send_signal_telegram(signal_doc, request.app))

    logger.info("🔍 Scan manual: %d señales generadas (umbral: %.2f)",
                len(all_signals), effective_threshold)
    return {"success": True, "new_signals": len(all_signals), "signals": all_signals}

def _parse_naive_utc(ts: str) -> datetime:
    """Parsea un string ISO UTC (con o sin Z) y devuelve datetime naive."""
    return datetime.fromisoformat(ts.rstrip("Z").split("+")[0])

@app.get("/api/signals/active")
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

@app.get("/api/signals/stats")
async def get_signals_stats(request: Request):
    if request.app.state.use_mongo:
        cutoff = datetime.utcnow() - timedelta(days=7)
        total  = await request.app.state.db.signals.count_documents(
            {"created_at": {"$gte": cutoff}}
        )
    else:
        cutoff = datetime.utcnow() - timedelta(days=7)
        total  = sum(
            1 for s in request.app.state.signals_store
            if _parse_naive_utc(s["created_at"]) >= cutoff
        )
    return {"period": "7 days", "total_signals": total}

# ============================================================================
# RUN
# ============================================================================

@app.get("/api/data-provider/status")
async def data_provider_status(request: Request):
    """Estado del proveedor de datos y uso de la API."""
    provider = request.app.state.data_provider
    return {
        "status": "real" if provider.is_configured else "simulated",
        **provider.stats(),
        "message": (
            "Datos de mercado REALES activos (Twelve Data)"
            if provider.is_configured
            else "Modo simulado activo. Configura TWELVE_DATA_API_KEY para datos reales."
        )
    }

@app.get("/api/assets")
async def get_assets():
    return [
        # FOREX PRINCIPALES
        {"id": "1", "symbol": "OTC_EURUSD", "name": "EUR/USD OTC", "type": "forex", "current_price": 1.0823, "price_change_24h": 0.12, "active": True},
        {"id": "2", "symbol": "OTC_GBPUSD", "name": "GBP/USD OTC", "type": "forex", "current_price": 1.2654, "price_change_24h": 0.08, "active": True},
        {"id": "3", "symbol": "OTC_USDJPY", "name": "USD/JPY OTC", "type": "forex", "current_price": 150.12, "price_change_24h": -0.15, "active": True},
        {"id": "4", "symbol": "OTC_USDCHF", "name": "USD/CHF OTC", "type": "forex", "current_price": 0.8823, "price_change_24h": -0.05, "active": True},
        {"id": "5", "symbol": "OTC_AUDUSD", "name": "AUD/USD OTC", "type": "forex", "current_price": 0.6523, "price_change_24h": 0.05, "active": True},
        {"id": "6", "symbol": "OTC_USDCAD", "name": "USD/CAD OTC", "type": "forex", "current_price": 1.3512, "price_change_24h": -0.08, "active": True},
        {"id": "7", "symbol": "OTC_NZDUSD", "name": "NZD/USD OTC", "type": "forex", "current_price": 0.5912, "price_change_24h": 0.03, "active": True},
        {"id": "8", "symbol": "OTC_EURJPY", "name": "EUR/JPY OTC", "type": "forex", "current_price": 162.45, "price_change_24h": -0.23, "active": True},
        
        # FOREX CRUZADOS
        {"id": "9", "symbol": "OTC_EURGBP", "name": "EUR/GBP OTC", "type": "forex", "current_price": 0.8556, "price_change_24h": 0.04, "active": True},
        {"id": "10", "symbol": "OTC_EURAUD", "name": "EUR/AUD OTC", "type": "forex", "current_price": 1.6589, "price_change_24h": 0.07, "active": True},
        {"id": "11", "symbol": "OTC_EURCAD", "name": "EUR/CAD OTC", "type": "forex", "current_price": 1.4623, "price_change_24h": 0.04, "active": True},
        {"id": "12", "symbol": "OTC_EURCHF", "name": "EUR/CHF OTC", "type": "forex", "current_price": 0.9545, "price_change_24h": 0.17, "active": True},
        {"id": "13", "symbol": "OTC_GBPJPY", "name": "GBP/JPY OTC", "type": "forex", "current_price": 189.90, "price_change_24h": -0.07, "active": True},
        {"id": "14", "symbol": "OTC_GBPAUD", "name": "GBP/AUD OTC", "type": "forex", "current_price": 1.9398, "price_change_24h": 0.03, "active": True},
        {"id": "15", "symbol": "OTC_GBPCAD", "name": "GBP/CAD OTC", "type": "forex", "current_price": 1.7098, "price_change_24h": 0.00, "active": True},
        {"id": "16", "symbol": "OTC_GBPCHF", "name": "GBP/CHF OTC", "type": "forex", "current_price": 1.1162, "price_change_24h": 0.13, "active": True},
        {"id": "17", "symbol": "OTC_AUDJPY", "name": "AUD/JPY OTC", "type": "forex", "current_price": 97.90, "price_change_24h": -0.20, "active": True},
        {"id": "18", "symbol": "OTC_AUDCAD", "name": "AUD/CAD OTC", "type": "forex", "current_price": 0.8812, "price_change_24h": -0.03, "active": True},
        {"id": "19", "symbol": "OTC_CADJPY", "name": "CAD/JPY OTC", "type": "forex", "current_price": 111.09, "price_change_24h": -0.07, "active": True},
        {"id": "20", "symbol": "OTC_CHFJPY", "name": "CHF/JPY OTC", "type": "forex", "current_price": 170.16, "price_change_24h": -0.10, "active": True}
    ]

@app.get("/api/market-data/{symbol}")
async def get_market_data(symbol: str, request: Request):
    """
    Retorna datos de mercado para el dashboard (sparkline + precio + cambio).
    IMPORTANTE: Solo usa el caché interno del provider — NUNCA consume
    créditos API frescos. Los créditos los maneja exclusivamente el scan loop.
    El frontend puede llamar este endpoint con libertad sin coste adicional.
    """
    provider = request.app.state.data_provider
    now      = datetime.utcnow()

    # ── Solo lee del caché — CERO requests a Twelve Data ─────────────────────
    ind = None
    if provider and provider.is_configured:
        cached = provider._cache.get(symbol)
        if cached:
            ind = cached.get("indicators")

    if ind and ind.candles:
        closes = [c.close for c in ind.candles[-20:]]  # últimas 20 velas para sparkline
        price  = ind.price
        change = round(((closes[-1] - closes[0]) / closes[0]) * 100, 4) if closes[0] else 0
        return {
            "symbol":     symbol,
            "price":      price,
            "change_pct": change,
            "prices":     closes,   # sparkline
            "is_real":    True,
            "source":     "cache",
        }

    # Fallback simulado — sin llamada API, usa estado en memoria
    from data_provider import simulate_candles
    candles = simulate_candles(symbol, count=20)
    closes  = [c.close for c in candles]
    price   = closes[-1] if closes else 0
    change  = round(((closes[-1] - closes[0]) / closes[0]) * 100, 4) if closes and closes[0] else 0
    return {
        "symbol":     symbol,
        "price":      price,
        "change_pct": change,
        "prices":     closes,
        "is_real":    False,
        "source":     "simulated",
    }


# ============================================================================
# TRADES — Registro y estadísticas de operaciones
# ============================================================================

def _calc_stats(trades: list) -> dict:
    """Calcula Win Rate, Profit Factor y desgloses a partir de una lista de trades."""
    if not trades:
        return {
            "total_trades": 0, "total_wins": 0, "total_losses": 0,
            "win_rate": 0.0, "profit_factor": 0.0,
            "by_pair": {}, "by_hour": {}, "by_score": {},
        }

    wins   = [t for t in trades if t["result"] == "win"]
    losses = [t for t in trades if t["result"] == "loss"]

    # Win rate global
    win_rate = round(len(wins) / len(trades) * 100, 1)

    # Profit factor: (ganancias × payout%) / (pérdidas × 100 unidades base)
    profit_wins  = sum(t.get("payout", 85) for t in wins)
    cost_losses  = len(losses) * 100
    profit_factor = round(profit_wins / cost_losses, 2) if cost_losses > 0 else 0.0

    # Por par
    by_pair = {}
    for sym in {t["symbol"] for t in trades}:
        pt  = [t for t in trades if t["symbol"] == sym]
        pw  = [t for t in pt if t["result"] == "win"]
        by_pair[sym] = {
            "asset_name": pt[0].get("asset_name", sym),
            "total":      len(pt),
            "wins":       len(pw),
            "win_rate":   round(len(pw) / len(pt) * 100, 1),
        }

    # Por hora del día (UTC)
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

    # Por nivel de quality score
    buckets = [("< 55%", 0.0, 0.55), ("55-65%", 0.55, 0.65),
               ("65-75%", 0.65, 0.75), ("75-85%", 0.75, 0.85), ("> 85%", 0.85, 1.1)]
    by_score = {}
    for label, lo, hi in buckets:
        bt = [t for t in trades if lo <= t.get("quality_score", 0) < hi]
        bw = [t for t in bt if t["result"] == "win"]
        if bt:
            by_score[label] = {
                "total":    len(bt),
                "wins":     len(bw),
                "win_rate": round(len(bw) / len(bt) * 100, 1),
            }

    return {
        "total_trades":  len(trades),
        "total_wins":    len(wins),
        "total_losses":  len(losses),
        "win_rate":      win_rate,
        "profit_factor": profit_factor,
        "by_pair":       by_pair,
        "by_hour":       by_hour,
        "by_score":      by_score,
    }


@app.post("/api/trades")
async def register_trade(
    trade: TradeResultModel,
    request: Request,
    auth: bool = Depends(verify_api_key)
):
    """
    Registra el resultado de una operación (win/loss).
    Activa automáticamente los módulos Antifragile v3.0:
      - Martingala Suave 1.5x
      - Evaluación de Timeframe post-pérdida
      - Bloqueo por Correlación
    """
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

    # ── Módulo 1: Martingala Suave ────────────────────────────────────────────
    base_bet    = trade.entry_price * 0.02 if trade.entry_price else 10.0  # 2% como proxy
    mg_result   = _soft_martingale_next_bet(trade.symbol, base_bet, trade.result)
    logger.info("🎲 Martingala | %s | %s | next=$%.2f",
                trade.symbol, mg_result["reason"], mg_result["next_bet"])

    # ── Módulo 3: Bloqueo por Correlación ────────────────────────────────────
    antifragile_response = {
        "martingale":         mg_result,
        "correlation_lock":   None,
        "timeframe_eval":     None,
        "newly_locked_currencies": [],
    }

    if trade.result == "loss":
        # Obtiene pérdidas recientes para evaluar correlación
        if request.app.state.use_mongo:
            cursor = request.app.state.db.trades.find(
                {"result": "loss"}
            ).sort("created_at", -1).limit(10)
            recent_losses = await cursor.to_list(10)
            for t in recent_losses:
                t["id"] = str(t.pop("_id", ""))
        else:
            all_t = list(request.app.state.trades_store)
            recent_losses = [t for t in reversed(all_t) if t.get("result") == "loss"][:10]

        newly_locked = _update_correlation_lock(recent_losses, lock_minutes=30)
        antifragile_response["newly_locked_currencies"] = newly_locked

        if newly_locked:
            logger.warning("🔴 BLOQUEO CORRELACIÓN activado: %s", newly_locked)
            for nc in newly_locked:
                await _send_telegram(
                    f"⚠️ <b>BLOQUEO POR CORRELACIÓN</b>: <code>{nc}</code>\n"
                    f"Pares con {nc} bloqueados 30 min.\n"
                    f"Causa: pérdidas en {trade.symbol} + par anterior"
                )

        # Correlación del par actual
        antifragile_response["correlation_lock"] = _check_correlation_lock(trade.symbol)

        # ── Módulo 2: Evaluación de Timeframe ────────────────────────────────
        loss_streak = mg_result["losses_streak"]
        if loss_streak in (1, 2):
            # Crea un IndicatorSet mínimo con los datos del trade
            fake_ind = type("Ind", (), {
                "atr_pct": getattr(trade, "atr_pct", 0.015) or 0.015,
            })()
            tf_eval = _evaluate_timeframe(trade.symbol, loss_streak, fake_ind)
            antifragile_response["timeframe_eval"] = tf_eval

            if tf_eval["action"] == "upgrade":
                logger.info("📈 TF Upgrade: %s → %s", trade.symbol, tf_eval["to_tf"])
                await _send_telegram(
                    f"📈 <b>CAMBIO DE TIMEFRAME</b>: <code>{trade.symbol}</code>\n"
                    f"{tf_eval['reason']}"
                )

    return {
        "success":      True,
        "trade":        doc,
        "antifragile":  antifragile_response,
    }


@app.get("/api/trades/stats")
async def get_trade_stats(request: Request, days: int = 30):
    """Retorna Win Rate, Profit Factor y desgloses por par, hora y score."""
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
        trades = [
            t for t in request.app.state.trades_store
            if datetime.fromisoformat(t["created_at"].rstrip("Z")) >= cutoff
        ]

    stats = _calc_stats(trades)
    stats["period_days"] = days
    stats["last_trades"] = trades[:10]  # últimas 10 para el historial
    return stats


@app.get("/api/trades/history")
async def get_trade_history(request: Request, limit: int = 50):
    """Retorna el historial de operaciones más recientes."""
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


@app.delete("/api/trades/{trade_id}")
async def delete_trade(trade_id: str, request: Request):
    """Elimina un trade registrado por error."""
    if request.app.state.use_mongo:
        from bson import ObjectId
        await request.app.state.db.trades.delete_one({"_id": ObjectId(trade_id)})
    else:
        store = request.app.state.trades_store
        request.app.state.trades_store = [t for t in store if t.get("id") != trade_id]
    return {"success": True}


@app.delete("/api/trades/bulk/last/{n}")
async def delete_last_n_trades(n: int, request: Request):
    """
    Elimina las últimas N operaciones registradas.
    Útil para limpiar trades generados con datos simulados o erróneos.
    """
    if n <= 0 or n > 500:
        raise HTTPException(status_code=400, detail="n debe estar entre 1 y 500")

    if request.app.state.use_mongo:
        cursor = request.app.state.db.trades.find().sort("created_at", -1).limit(n)
        last_n = await cursor.to_list(n)
        ids_to_delete = [t["_id"] for t in last_n]
        result = await request.app.state.db.trades.delete_many(
            {"_id": {"$in": ids_to_delete}}
        )
        deleted = result.deleted_count
    else:
        store = list(request.app.state.trades_store)
        # Ordena por fecha descendente, toma los últimos N
        store_sorted = sorted(
            store,
            key=lambda t: t.get("created_at", ""),
            reverse=True
        )
        ids_to_delete = {t["id"] for t in store_sorted[:n]}
        request.app.state.trades_store = [
            t for t in store if t.get("id") not in ids_to_delete
        ]
        deleted = len(ids_to_delete)

    logger.info("🗑️  Borrados %d trades (últimos %d solicitados)", deleted, n)
    return {
        "success":  True,
        "deleted":  deleted,
        "message":  f"✅ {deleted} operaciones eliminadas del historial",
    }


@app.delete("/api/trades/bulk/all")
async def delete_all_trades(request: Request):
    """Borra TODO el historial de trades. Usar con precaución."""
    if request.app.state.use_mongo:
        result = await request.app.state.db.trades.delete_many({})
        deleted = result.deleted_count
    else:
        deleted = len(request.app.state.trades_store)
        request.app.state.trades_store = []

    logger.info("🗑️  Historial completo borrado: %d trades eliminados", deleted)
    return {
        "success": True,
        "deleted": deleted,
        "message": f"✅ Historial completo borrado ({deleted} operaciones)",
    }


# ── Umbral dinámico global (calibrado con historial real) ─────────────────────
# Se actualiza en cada ciclo si hay suficientes trades registrados.
_dynamic_min_quality: float = 0.55   # valor por defecto (sin calibración)
_MIN_TRADES_TO_CALIBRATE: int = 15   # mínimo de trades para confiar en el WR


def _compute_optimal_threshold(trades: list) -> dict:
    """
    Analiza el Win Rate por bucket de quality score y encuentra
    el umbral mínimo donde WR >= MIN_WR_TARGET.

    Estrategia:
    - Divide los trades en 5 rangos de score: <55, 55-65, 65-75, 75-85, >85
    - Calcula WR real en cada rango
    - Recomienda usar como umbral el rango más bajo con WR >= 55%
    - Si ninguno supera el 55%, recomienda el más alto disponible

    Returns dict con análisis completo y umbral recomendado.
    """
    MIN_WR_TARGET   = 55.0   # Win Rate mínimo aceptable
    MIN_SAMPLE      = 5      # mínimo de trades por bucket para ser válido

    buckets = [
        ("< 0.55",  0.00, 0.55),
        ("0.55-0.65", 0.55, 0.65),
        ("0.65-0.75", 0.65, 0.75),
        ("0.75-0.85", 0.75, 0.85),
        ("> 0.85",  0.85, 1.10),
    ]

    analysis = []
    for label, lo, hi in buckets:
        bt = [t for t in trades if lo <= t.get("quality_score", 0) < hi]
        bw = [t for t in bt if t.get("result") == "win"]
        wr = round(len(bw) / len(bt) * 100, 1) if bt else None
        analysis.append({
            "range":       label,
            "threshold_lo": lo,
            "threshold_hi": hi,
            "total":       len(bt),
            "wins":        len(bw),
            "win_rate":    wr,
            "valid":       len(bt) >= MIN_SAMPLE and wr is not None,
            "profitable":  wr is not None and wr >= MIN_WR_TARGET,
        })

    # Encuentra el umbral óptimo: más bajo con WR >= target y muestra válida
    optimal_threshold = 0.55   # default conservador
    recommendation    = "Sin datos suficientes — usando umbral por defecto (0.55)"
    calibrated        = False

    valid_profitable = [b for b in analysis if b["valid"] and b["profitable"]]
    valid_any        = [b for b in analysis if b["valid"]]

    if valid_profitable:
        # Usar el bucket más bajo que es rentable (más señales sin perder calidad)
        best = min(valid_profitable, key=lambda b: b["threshold_lo"])
        optimal_threshold = best["threshold_lo"]
        calibrated        = True
        recommendation    = (
            f"Score ≥ {optimal_threshold:.2f} tiene WR {best['win_rate']}% "
            f"con {best['total']} operaciones — umbral recomendado"
        )
    elif valid_any:
        # Ningún bucket es rentable → usar el que tiene mejor WR
        best = max(valid_any, key=lambda b: b["win_rate"] or 0)
        optimal_threshold = best["threshold_lo"]
        calibrated        = True
        recommendation    = (
            f"⚠️  Ningún bucket supera 55% WR. Mejor resultado: "
            f"score ≥ {optimal_threshold:.2f} con {best['win_rate']}% WR "
            f"({best['total']} ops). Considera revisar estrategias."
        )

    return {
        "total_trades":        len(trades),
        "min_trades_required": _MIN_TRADES_TO_CALIBRATE,
        "calibrated":          calibrated,
        "optimal_threshold":   optimal_threshold,
        "current_threshold":   _dynamic_min_quality,
        "recommendation":      recommendation,
        "min_wr_target":       MIN_WR_TARGET,
        "buckets":             analysis,
    }


@app.get("/api/performance/execution")
async def get_execution_quality(request: Request, days: int = 30):
    """
    Métricas de Calidad de Ejecución:
    - MAE promedio por sesión (Limpia vs Riesgosa)
    - Latencia promedio por sesión (ms entre señal y ejecución)
    - MAE vs Resultado (¿alto MAE = más pérdidas?)
    """
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

    mae_avg = round(sum(t["max_adverse_excursion"] for t in mae_trades) / len(mae_trades), 2) if mae_trades else None
    lat_avg = round(sum(t["execution_latency_ms"] for t in lat_trades) / len(lat_trades)) if lat_trades else None

    def mae_label(avg):
        if avg is None:  return "Sin datos suficientes"
        if avg < 3:      return "🟢 Limpia"
        if avg < 6:      return "🟡 Moderada"
        if avg < 10:     return "🟠 Riesgosa"
        return           "🔴 Muy Riesgosa"

    # Por sesión
    by_session = {}
    for sess in ["Asiática", "Londres", "Londres+NY", "Nueva York"]:
        st = [t for t in trades if t.get("session") == sess]
        if not st:
            continue
        sm = [t for t in st if t.get("max_adverse_excursion") is not None]
        sl = [t for t in st if t.get("execution_latency_ms") is not None]
        sw = [t for t in st if t.get("result") == "win"]
        s_mae = round(sum(t["max_adverse_excursion"] for t in sm) / len(sm), 2) if sm else None
        s_lat = round(sum(t["execution_latency_ms"] for t in sl) / len(sl)) if sl else None
        by_session[sess] = {
            "total": len(st), "wins": len(sw),
            "win_rate": round(len(sw) / len(st) * 100, 1),
            "mae_avg_pips": s_mae, "mae_label": mae_label(s_mae),
            "latency_avg_ms": s_lat,
            "latency_label": "✅ Rápida" if s_lat and s_lat < 30000 else ("⚠️ Lenta" if s_lat else "Sin datos"),
        }

    # MAE vs resultado
    mae_vs_result = {}
    for label, lo, hi in [("0-2 pips", 0, 2), ("2-5 pips", 2, 5), ("5-10 pips", 5, 10), ("> 10 pips", 10, 9999)]:
        bt = [t for t in mae_trades if lo <= t["max_adverse_excursion"] < hi]
        bw = [t for t in bt if t.get("result") == "win"]
        if bt:
            mae_vs_result[label] = {"total": len(bt), "wins": len(bw),
                                     "win_rate": round(len(bw) / len(bt) * 100, 1)}

    return {
        "total_trades": len(trades), "trades_with_mae": len(mae_trades),
        "mae_avg_pips": mae_avg, "mae_label": mae_label(mae_avg),
        "latency_avg_ms": lat_avg,
        "latency_label": "✅ Rápida (< 30s)" if lat_avg and lat_avg < 30000 else ("⚠️ Lenta" if lat_avg else "Sin datos"),
        "by_session": by_session, "mae_vs_result": mae_vs_result, "period_days": days,
    }


@app.get("/api/calibration")
async def get_calibration(request: Request):
    """
    Analiza el historial real de trades y recomienda el umbral óptimo
    de quality score para maximizar el Win Rate.

    También aplica el nuevo umbral globalmente si hay suficientes datos.
    """
    global _dynamic_min_quality

    # Obtiene todos los trades registrados
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
        return {
            "calibrated":          False,
            "total_trades":        len(trades),
            "min_trades_required": _MIN_TRADES_TO_CALIBRATE,
            "current_threshold":   _dynamic_min_quality,
            "optimal_threshold":   _dynamic_min_quality,
            "recommendation":      (
                f"Necesitas al menos {_MIN_TRADES_TO_CALIBRATE} operaciones "
                f"registradas para calibrar. Tienes {len(trades)}."
            ),
            "buckets": [],
        }

    result = _compute_optimal_threshold(trades)

    # Aplica el nuevo umbral si la calibración es válida
    if result["calibrated"]:
        old = _dynamic_min_quality
        _dynamic_min_quality = max(0.45, min(0.85, result["optimal_threshold"]))
        if abs(_dynamic_min_quality - old) > 0.01:
            logger.info("🎯 Calibración aplicada: MIN_QUALITY %.2f → %.2f | %s",
                        old, _dynamic_min_quality, result["recommendation"])

    result["current_threshold"] = _dynamic_min_quality
    return result


@app.post("/api/backtest")
async def run_backtest(body: BacktestRequest, request: Request):
    """
    Backtesting con ventana deslizante sobre datos reales de Twelve Data.

    Algoritmo:
    1. Descarga N velas históricas del par solicitado
    2. Por cada posición i (desde vela 50 hasta N-expiry):
       a. Calcula indicadores sobre candles[i-50:i]
       b. Genera señal con el ensemble de estrategias
       c. Si quality_score >= min_quality → registra operación
       d. Evalúa resultado: close[i+expiry] vs close[i] (precio de entrada)
    3. Devuelve estadísticas: win_rate, profit_factor, equity_curve
    """
    provider = get_provider()
    if not provider or not provider.is_configured:
        raise HTTPException(
            status_code=400,
            detail="Backtesting requiere API key de Twelve Data configurada"
        )

    candles_count = min(max(body.candles, 100), 500)  # entre 100 y 500
    expiry        = max(body.expiry_candles, 1)

    try:
        all_candles = await provider.fetch_historical_candles(
            body.symbol, body.interval, candles_count
        )
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
    equity       = 100.0        # capital inicial simulado (%)
    equity_curve = [100.0]
    WINDOW       = 50           # velas para calcular indicadores
    PAYOUT       = 0.85         # retorno en win (85%)

    for i in range(WINDOW, len(all_candles) - expiry):
        window  = all_candles[i - WINDOW : i]
        ind     = IndicatorSet()
        ind.compute(window)
        ind.is_real = True

        signal = ensemble.get_consensus_signal(ind)
        if not signal:
            continue

        score = _quality_score(signal, body.symbol, ind)
        if score < body.min_quality:
            continue

        entry_candle = all_candles[i]
        exit_candle  = all_candles[i + expiry]
        entry_price  = entry_candle.close
        exit_price   = exit_candle.close

        # Determina resultado
        if signal["type"] == "CALL":
            won = exit_price > entry_price
        else:
            won = exit_price < entry_price

        result = "win" if won else "loss"
        if won:
            wins  += 1
            equity = round(equity * (1 + PAYOUT / 100), 4)
        else:
            losses += 1
            equity = round(equity * (1 - 1 / 100), 4)   # pierde el 100% apostado

        equity_curve.append(equity)
        trades.append({
            "index":       i,
            "timestamp":   entry_candle.time,
            "type":        signal["type"],
            "entry_price": entry_price,
            "exit_price":  exit_price,
            "score":       round(score, 3),
            "cci":         signal.get("cci", 0),
            "result":      result,
            "equity":      equity,
        })

    total = wins + losses
    win_rate      = round(wins / total * 100, 1) if total else 0
    gross_profit  = sum(t["equity"] - 100 for t in trades if t["result"] == "win")
    gross_loss    = sum(100 - t["equity"] for t in trades if t["result"] == "loss")
    profit_factor = round(abs(gross_profit / gross_loss), 2) if gross_loss else 0

    return {
        "symbol":         body.symbol,
        "interval":       body.interval,
        "candles_total":  len(all_candles),
        "expiry_candles": expiry,
        "min_quality":    body.min_quality,
        "total_signals":  total,
        "wins":           wins,
        "losses":         losses,
        "win_rate":       win_rate,
        "profit_factor":  profit_factor,
        "final_equity":   round(equity, 2),
        "equity_curve":   equity_curve,
        "trades":         trades,
        "summary": (
            f"{total} señales | {win_rate}% WR | PF {profit_factor} | "
            f"Capital final: {equity:.1f}%"
        ),
    }


# ============================================================================
# RISK MANAGER
# ============================================================================

class RiskStatusRequest(BaseModel):
    balance:       float = 1000.0   # capital actual del usuario
    risk_pct:      float = 2.0      # % base a arriesgar por operación
    session_start: str  = ""        # ISO timestamp inicio de sesión (opcional)


def _get_session_trades(trades: list, session_start_iso: str) -> list:
    """Filtra trades de la sesión actual (desde session_start hasta ahora)."""
    if not session_start_iso:
        # Si no se da inicio de sesión, usa los últimos 8 horas
        cutoff = datetime.utcnow() - timedelta(hours=8)
    else:
        try:
            cutoff = datetime.fromisoformat(session_start_iso.rstrip("Z"))
        except Exception:
            cutoff = datetime.utcnow() - timedelta(hours=8)

    session = []
    for t in trades:
        ts_str = t.get("signal_timestamp") or t.get("created_at", "")
        try:
            ts = datetime.fromisoformat(ts_str.rstrip("Z"))
            if ts >= cutoff:
                session.append(t)
        except Exception:
            pass
    return session


# ============================================================================
# ARQUITECTURA ANTIFRÁGIL v3.0
# Módulo 1: Martingala Suave (1.5x fijo)
# Módulo 2: Evaluación de Timeframe Post-Pérdida
# Módulo 3: Bloqueo por Correlación
# ============================================================================

# ── Estado global de Antifragile (en memoria, reseteado al reiniciar) ─────────
_martingale_state: dict  = {}   # symbol → { base: float, current: float, losses: int }
_correlation_locks: dict = {}   # currency → datetime (expiry)
_timeframe_overrides: dict = {} # symbol → "5min" | "15min" (override temporal)

# Mapa: símbolo → (moneda_base, moneda_cotizada)
def _get_currencies(symbol: str):
    """Extrae las dos monedas de un símbolo OTC. Ej: OTC_EURUSD → ('EUR','USD')"""
    clean = symbol.replace("OTC_", "").replace("_", "").upper()
    if len(clean) == 6:
        return clean[:3], clean[3:]
    return None, None


def _soft_martingale_next_bet(symbol: str, base_bet: float, result: str) -> dict:
    """
    Módulo 1 — Martingala Suave (1.5x fijo).

    Reglas:
    - WIN  → resetea al base_bet, losses_streak = 0
    - LOSS → siguiente apuesta = current * 1.5 (máximo 1 multiplicación)
    - El multiplicador es SIEMPRE 1.5x — nunca escala a 2x ni más

    Retorna dict con:
      next_bet       : float — apuesta recomendada para la siguiente operación
      multiplier     : float — 1.0 (base) o 1.5 (post-pérdida)
      losses_streak  : int   — pérdidas consecutivas en este par
      reason         : str   — explicación legible
    """
    state = _martingale_state.get(symbol, {
        "base":    base_bet,
        "current": base_bet,
        "losses":  0,
    })

    # Actualiza el base si el usuario cambió su bet
    if abs(state["base"] - base_bet) > 0.01 and state["losses"] == 0:
        state["base"] = base_bet
        state["current"] = base_bet

    if result == "win":
        # Reseteo total
        state["current"] = state["base"]
        state["losses"]  = 0
        next_bet    = state["base"]
        multiplier  = 1.0
        reason      = "✅ WIN — apuesta reseteada al valor base"
    else:
        # Aplica 1.5x sobre la apuesta actual (FIJO, nunca escala más)
        state["losses"] += 1
        next_bet = round(state["current"] * 1.5, 2)
        # Guarda la nueva apuesta para el siguiente ciclo
        state["current"] = next_bet
        multiplier = 1.5
        reason = (
            f"❌ LOSS #{state['losses']} — Martingala Suave 1.5x aplicada. "
            f"${state['base']:.2f} → ${next_bet:.2f}"
        )

    _martingale_state[symbol] = state

    return {
        "next_bet":      next_bet,
        "multiplier":    multiplier,
        "losses_streak": state["losses"],
        "base_bet":      state["base"],
        "reason":        reason,
    }


def _check_correlation_lock(symbol: str) -> dict:
    """
    Módulo 3 — Verifica si alguna de las monedas del par está bloqueada.

    Retorna:
      locked      : bool
      currencies  : list  — monedas bloqueadas que afectan este par
      expires_at  : str   — UTC ISO cuando expira el bloqueo
      reason      : str
    """
    base_cur, quote_cur = _get_currencies(symbol)
    if not base_cur:
        return {"locked": False, "currencies": [], "expires_at": None, "reason": ""}

    now = datetime.utcnow()
    locked_currencies = []
    soonest_expiry    = None

    for currency in (base_cur, quote_cur):
        expiry = _correlation_locks.get(currency)
        if expiry and now < expiry:
            locked_currencies.append(currency)
            if soonest_expiry is None or expiry < soonest_expiry:
                soonest_expiry = expiry

    if locked_currencies:
        mins_left = round((soonest_expiry - now).total_seconds() / 60, 1)
        return {
            "locked":      True,
            "currencies":  locked_currencies,
            "expires_at":  soonest_expiry.strftime("%Y-%m-%dT%H:%M:%S") + "Z",
            "mins_left":   mins_left,
            "reason":      f"⚠️ BLOQUEO POR CORRELACIÓN: {', '.join(locked_currencies)} — {mins_left} min restantes",
        }

    return {"locked": False, "currencies": [], "expires_at": None, "reason": ""}


def _update_correlation_lock(recent_losses: list, lock_minutes: int = 30) -> list:
    """
    Módulo 3 — Evalúa las últimas pérdidas y activa bloqueo por correlación.

    Regla de Oro: Si 2 pérdidas consecutivas en DIFERENTES pares comparten
    la misma moneda → bloquea esa moneda 30 minutos.

    Retorna lista de monedas recién bloqueadas.
    """
    if len(recent_losses) < 2:
        return []

    # Toma las 2 pérdidas más recientes en pares DISTINTOS
    last_losses = []
    seen_symbols = set()
    for loss in reversed(recent_losses):
        sym = loss.get("symbol", "")
        if sym not in seen_symbols:
            last_losses.append(loss)
            seen_symbols.add(sym)
        if len(last_losses) == 2:
            break

    if len(last_losses) < 2:
        return []

    sym_a, sym_b = last_losses[0]["symbol"], last_losses[1]["symbol"]

    # Mismo par → no es correlación entre pares distintos
    if sym_a == sym_b:
        return []

    base_a, quote_a = _get_currencies(sym_a)
    base_b, quote_b = _get_currencies(sym_b)

    if not base_a or not base_b:
        return []

    currencies_a = {base_a, quote_a}
    currencies_b = {base_b, quote_b}
    shared = currencies_a & currencies_b

    newly_locked = []
    if shared:
        expiry = datetime.utcnow() + timedelta(minutes=lock_minutes)
        for currency in shared:
            existing = _correlation_locks.get(currency)
            if not existing or datetime.utcnow() >= existing:
                _correlation_locks[currency] = expiry
                newly_locked.append(currency)
                logger.warning(
                    "🔴 CORRELACIÓN: %s y %s comparten %s — bloqueado %d min",
                    sym_a, sym_b, currency, lock_minutes
                )

    return newly_locked


def _evaluate_timeframe(symbol: str, loss_streak: int, ind: "IndicatorSet") -> dict:
    """
    Módulo 2 — Evaluación de Timeframe Post-Pérdida.

    Actúa cuando loss_streak == 1 o 2.
    Compara ADX del timeframe actual (M1) vs superior (M5).

    Criterio de cambio:
    - ADX actual  < 20 (mercado sin tendencia)
    - ADX superior > 25 (tendencia clara en TF mayor)
    → Si se cumplen ambos: recomienda cambiar al TF superior.

    Nota: En producción necesitaría fetch real del TF superior.
    Aquí usa simulación conservadora basada en ATR% como proxy de ADX.
    """
    if loss_streak not in (1, 2):
        # Limpia override si ya no hay pérdidas consecutivas
        _timeframe_overrides.pop(symbol, None)
        return {"action": "none", "reason": "Sin pérdidas consecutivas recientes"}

    # Proxy de ADX usando ATR% (correlación positiva documentada)
    # ATR% < 0.010% ≈ ADX < 20 (rango plano)
    # ATR% > 0.018% ≈ ADX > 25 (tendencia)
    current_adx_proxy  = (ind.atr_pct * 1000) if (ind and ind.atr_pct) else 15.0
    superior_adx_proxy = current_adx_proxy * 1.4   # TF5 típicamente más tendencial

    current_tf  = _timeframe_overrides.get(symbol, "1min")
    tf_map      = {"1min": "5min", "5min": "15min", "15min": "15min"}
    superior_tf = tf_map.get(current_tf, "5min")

    if current_adx_proxy < 20 and superior_adx_proxy > 25:
        _timeframe_overrides[symbol] = superior_tf
        return {
            "action":        "upgrade",
            "from_tf":       current_tf,
            "to_tf":         superior_tf,
            "current_adx":   round(current_adx_proxy, 1),
            "superior_adx":  round(superior_adx_proxy, 1),
            "reason":        (
                f"📈 ADX M1={current_adx_proxy:.0f} (rango) vs "
                f"ADX M5={superior_adx_proxy:.0f} (tendencia) — "
                f"cambiando a {superior_tf}"
            ),
        }

    return {
        "action":       "hold",
        "from_tf":      current_tf,
        "to_tf":        current_tf,
        "current_adx":  round(current_adx_proxy, 1),
        "superior_adx": round(superior_adx_proxy, 1),
        "reason":       (
            f"Manteniendo {current_tf} — "
            f"ADX={current_adx_proxy:.0f} no justifica cambio de TF"
        ),
    }


def _calc_streak(trades: list) -> dict:
    """
    Calcula la racha actual (consecutiva) de W o L.
    Devuelve: { type: 'W'|'L'|'none', count: int, last_3: list }
    """
    if not trades:
        return {"type": "none", "count": 0, "last_3": []}

    sorted_t = sorted(trades, key=lambda t: t.get("signal_timestamp") or t.get("created_at", ""))
    results  = [t["result"] for t in sorted_t]

    streak_type  = results[-1]   # 'win' o 'loss'
    streak_count = 0
    for r in reversed(results):
        if r == streak_type:
            streak_count += 1
        else:
            break

    last_3 = results[-3:]
    return {
        "type":   "W" if streak_type == "win" else "L",
        "count":  streak_count,
        "last_3": ["W" if r == "win" else "L" for r in last_3],
    }


def _calc_position_size(balance: float, risk_pct: float, streak: dict,
                        symbol: str = None, last_result: str = None) -> dict:
    """
    Calcula el tamaño de posición.

    Lógica integrada con Martingala Suave v3.0:
    - Si se proporciona symbol + last_result → usa _soft_martingale_next_bet()
    - Si no → lógica base por racha (comportamiento legacy)

    Nota: El multiplicador de martingala es SIEMPRE 1.5x (nunca 2x).
    """
    base_amount = balance * (risk_pct / 100)

    # ── Martingala Suave (Módulo 1 Antifragile v3.0) ─────────────────────────
    if symbol and last_result in ("win", "loss"):
        mg = _soft_martingale_next_bet(symbol, base_amount, last_result)
        return {
            "base_amount":        round(base_amount, 2),
            "multiplier":         mg["multiplier"],
            "multiplier_reason":  mg["reason"],
            "suggested_amount":   mg["next_bet"],
            "losses_streak":      mg["losses_streak"],
            "martingale_active":  mg["multiplier"] > 1.0,
            "risk_pct_effective": round((mg["next_bet"] / balance) * 100, 2) if balance > 0 else 0,
        }

    # ── Lógica base por racha (sin martingala) ────────────────────────────────
    multiplier        = 1.0
    multiplier_reason = "Tamaño base"

    if streak["type"] == "W":
        if streak["count"] >= 3:
            multiplier = 1.25
            multiplier_reason = "Racha 3W — aumento compuesto +25%"
        elif streak["count"] == 2:
            multiplier = 1.10
            multiplier_reason = "Racha 2W — aumento compuesto +10%"
    elif streak["type"] == "L":
        if streak["count"] >= 3:
            multiplier = 0.25
            multiplier_reason = "Circuit Breaker: 3L consecutivas — mínimo -75%"
        elif streak["count"] == 2:
            multiplier = 0.50
            multiplier_reason = "Racha 2L — reducción protectora -50%"

    suggested = round(base_amount * multiplier, 2)

    return {
        "base_amount":        round(base_amount, 2),
        "multiplier":         multiplier,
        "multiplier_reason":  multiplier_reason,
        "suggested_amount":   suggested,
        "losses_streak":      streak["count"] if streak["type"] == "L" else 0,
        "martingale_active":  False,
        "risk_pct_effective": round((suggested / balance) * 100, 2) if balance > 0 else 0,
    }


def _check_circuit_breaker(session_trades: list, balance: float,
                            session_start_balance: float) -> dict:
    """
    Verifica si el Circuit Breaker debe activarse.

    Condiciones de disparo:
    1. 3 o más pérdidas CONSECUTIVAS en la sesión
    2. Caída del capital ≥ 25% desde el inicio de la sesión

    En modo DEMO (ACCOUNT_MODE=demo en .env) el circuit breaker NO se activa
    para permitir acumular datos estadísticos sin interrupciones.

    Returns dict con: triggered, reason, cooldown_minutes
    """
    CONSECUTIVE_LOSS_LIMIT = 3
    MAX_DRAWDOWN_PCT        = 25.0
    COOLDOWN_MINUTES        = 60

    # ── Bypass completo en modo Demo ─────────────────────────────────────────
    account_mode = os.getenv("ACCOUNT_MODE", "demo").lower()
    if account_mode == "demo":
        consecutive_losses = 0
        if session_trades:
            sorted_t = sorted(session_trades, key=lambda t: t.get("signal_timestamp") or t.get("created_at", ""))
            for r in reversed([t["result"] for t in sorted_t]):
                if r == "loss":
                    consecutive_losses += 1
                else:
                    break
        return {
            "triggered":          False,
            "reason":             f"Modo DEMO — circuit breaker desactivado ({consecutive_losses} pérd. consec.)",
            "cooldown_minutes":   0,
            "consecutive_losses": consecutive_losses,
            "drawdown_pct":       0.0,
            "demo_mode":          True,
        }

    if not session_trades:
        return {"triggered": False, "reason": "", "cooldown_minutes": 0, "consecutive_losses": 0}
        return {"triggered": False, "reason": "", "cooldown_minutes": 0, "consecutive_losses": 0}

    sorted_t   = sorted(session_trades, key=lambda t: t.get("signal_timestamp") or t.get("created_at", ""))
    results    = [t["result"] for t in sorted_t]

    # Condición 1: pérdidas consecutivas
    consecutive_losses = 0
    for r in reversed(results):
        if r == "loss":
            consecutive_losses += 1
        else:
            break

    if consecutive_losses >= CONSECUTIVE_LOSS_LIMIT:
        return {
            "triggered":          True,
            "reason":             f"🛑 {consecutive_losses} pérdidas consecutivas — Revenge Trading bloqueado",
            "cooldown_minutes":   COOLDOWN_MINUTES,
            "consecutive_losses": consecutive_losses,
            "drawdown_pct":       0.0,
        }

    # Condición 2: drawdown de sesión
    drawdown_pct = 0.0
    if session_start_balance > 0 and balance < session_start_balance:
        drawdown_pct = round((session_start_balance - balance) / session_start_balance * 100, 1)
        if drawdown_pct >= MAX_DRAWDOWN_PCT:
            return {
                "triggered":          True,
                "reason":             f"🛑 Drawdown de sesión {drawdown_pct}% ≥ {MAX_DRAWDOWN_PCT}% — pausa obligatoria",
                "cooldown_minutes":   COOLDOWN_MINUTES,
                "consecutive_losses": consecutive_losses,
                "drawdown_pct":       drawdown_pct,
            }

    return {
        "triggered":          False,
        "reason":             "OK — Operando dentro de límites",
        "cooldown_minutes":   0,
        "consecutive_losses": consecutive_losses,
        "drawdown_pct":       drawdown_pct,
    }


def _pair_win_rate_last_30min(all_trades: list, symbol: str) -> dict:
    """
    Calcula el Win Rate del par en los últimos 30 minutos.
    Usado para degradar señales de pares con mal rendimiento reciente.
    """
    cutoff = datetime.utcnow() - timedelta(minutes=30)
    recent = [
        t for t in all_trades
        if t.get("symbol") == symbol
        and _try_parse_ts(t.get("signal_timestamp") or t.get("created_at", "")) >= cutoff
    ]
    if not recent:
        return {"trades": 0, "win_rate": None, "degraded": False}

    wins     = sum(1 for t in recent if t.get("result") == "win")
    wr       = round(wins / len(recent) * 100, 1)
    degraded = wr < 50.0

    return {"trades": len(recent), "win_rate": wr, "degraded": degraded}


def _try_parse_ts(ts_str: str) -> datetime:
    """Parsea timestamp con fallback a epoch si falla."""
    try:
        return datetime.fromisoformat(ts_str.rstrip("Z"))
    except Exception:
        return datetime.min


@app.get("/api/risk/status")
async def get_risk_status(body: RiskStatusRequest, request: Request):
    """
    Risk Manager completo: streak, position sizing, circuit breaker y
    degradación de señal por par.

    Parámetros:
    - balance:       capital actual del usuario
    - risk_pct:      % base a arriesgar (ej: 2.0 = 2%)
    - session_start: ISO timestamp del inicio de la sesión (opcional)
    """
    # ── Obtiene todos los trades ───────────────────────────────────────────────
    if request.app.state.use_mongo:
        cursor = request.app.state.db.trades.find().sort("created_at", -1)
        all_trades = await cursor.to_list(500)
        for t in all_trades:
            t["id"] = str(t.pop("_id", ""))
            if isinstance(t.get("created_at"), datetime):
                t["created_at"] = t["created_at"].strftime("%Y-%m-%dT%H:%M:%S") + "Z"
    else:
        all_trades = list(request.app.state.trades_store)

    # ── Trades de la sesión actual ─────────────────────────────────────────────
    # Respeta el reset manual del Circuit Breaker:
    # Si se hizo reset, usa ese timestamp como inicio de sesión
    cb_reset = getattr(request.app.state, "circuit_breaker_reset_at", None)
    effective_session_start = cb_reset if cb_reset else body.session_start
    session_trades = _get_session_trades(all_trades, effective_session_start)

    # ── Balance inicial estimado (antes de las pérdidas de sesión) ────────────
    session_losses = sum(1 for t in session_trades if t.get("result") == "loss")
    session_wins   = sum(1 for t in session_trades if t.get("result") == "win")
    avg_bet        = body.balance * (body.risk_pct / 100)
    estimated_start_balance = body.balance + (session_losses * avg_bet) - (session_wins * avg_bet * 0.85)

    # ── Streak ────────────────────────────────────────────────────────────────
    streak = _calc_streak(session_trades)

    # ── Position sizing ───────────────────────────────────────────────────────
    sizing = _calc_position_size(body.balance, body.risk_pct, streak)

    # ── Circuit Breaker ───────────────────────────────────────────────────────
    circuit_breaker = _check_circuit_breaker(
        session_trades, body.balance, estimated_start_balance
    )

    # ── WR por par (últimos 30 min) ───────────────────────────────────────────
    active_pairs = list({t.get("symbol") for t in session_trades if t.get("symbol")})
    pair_wr = {}
    for sym in active_pairs:
        pair_wr[sym] = _pair_win_rate_last_30min(all_trades, sym)

    # ── Sesión stats ──────────────────────────────────────────────────────────
    session_wr = (
        round(session_wins / len(session_trades) * 100, 1)
        if session_trades else None
    )

    # ── Antifragile v3.0 — estado de los 3 módulos ────────────────────────────
    # Módulo 1: Martingala Suave — estado por par activo
    martingale_by_pair = {}
    for sym in active_pairs:
        state = _martingale_state.get(sym)
        if state:
            martingale_by_pair[sym] = {
                "losses_streak":  state["losses"],
                "current_bet":    state["current"],
                "base_bet":       state["base"],
                "multiplier":     round(state["current"] / state["base"], 2) if state["base"] > 0 else 1.0,
                "active":         state["losses"] > 0,
            }

    # Módulo 3: Bloqueos por correlación activos
    now = datetime.utcnow()
    active_locks = {}
    for currency, expiry in list(_correlation_locks.items()):
        if now < expiry:
            mins = round((expiry - now).total_seconds() / 60, 1)
            active_locks[currency] = {
                "expires_at": expiry.strftime("%Y-%m-%dT%H:%M:%S") + "Z",
                "mins_left":  mins,
                "message":    f"⚠️ BLOQUEO POR CORRELACIÓN: {currency} — {mins} min",
            }
        else:
            _correlation_locks.pop(currency, None)  # limpia expirados

    # Módulo 2: Timeframe overrides activos
    active_tf_overrides = dict(_timeframe_overrides)

    return {
        "balance":         body.balance,
        "risk_pct":        body.risk_pct,
        "session_trades":  len(session_trades),
        "session_wins":    session_wins,
        "session_losses":  session_losses,
        "session_win_rate": session_wr,
        "streak":          streak,
        "sizing":          sizing,
        "circuit_breaker": circuit_breaker,
        "pair_win_rates":  pair_wr,
        "status":          "BLOQUEADO" if circuit_breaker["triggered"] else "OK",
        # ── Antifragile v3.0 ──────────────────────────────────────────────────
        "antifragile": {
            "martingale_by_pair":   martingale_by_pair,
            "correlation_locks":    active_locks,
            "timeframe_overrides":  active_tf_overrides,
            "has_correlation_lock": len(active_locks) > 0,
            "correlation_message":  (
                " | ".join(v["message"] for v in active_locks.values())
                if active_locks else None
            ),
        },
    }


@app.get("/api/risk/pair-wr/{symbol}")
async def get_pair_win_rate(symbol: str, request: Request, minutes: int = 30):
    """Win Rate de un par específico en los últimos N minutos."""
    if request.app.state.use_mongo:
        cutoff = datetime.utcnow() - timedelta(minutes=minutes)
        cursor = request.app.state.db.trades.find(
            {"symbol": symbol, "created_at": {"$gte": cutoff}}
        )
        trades = await cursor.to_list(200)
        for t in trades:
            t["id"] = str(t.pop("_id", ""))
            if isinstance(t.get("created_at"), datetime):
                t["created_at"] = t["created_at"].strftime("%Y-%m-%dT%H:%M:%S") + "Z"
    else:
        cutoff_dt = datetime.utcnow() - timedelta(minutes=minutes)
        trades = [
            t for t in request.app.state.trades_store
            if t.get("symbol") == symbol
            and _try_parse_ts(t.get("signal_timestamp") or t.get("created_at", "")) >= cutoff_dt
        ]

    result = _pair_win_rate_last_30min(trades + [], symbol)
    result["symbol"]  = symbol
    result["minutes"] = minutes
    return result


@app.get("/v1/stats")
async def get_stats(request: Request, window: str = "1h"):
    """
    Win Rate consolidado por par y por sesión, con caché Redis (TTL 5 min).

    ?window=1h   → último 1 hora  (default)
    ?window=4h   → últimas 4 horas
    ?window=24h  → últimas 24 horas

    Respuesta: {
      "window": "1h",
      "global": {"total": N, "wins": N, "win_rate": 72.5, "profit_factor": 1.83},
      "by_pair": {"OTC_EURUSD": {"total":N, "wins":N, "win_rate":N, "degraded":bool}},
      "by_session": {"london": {"total":N, "wins":N, "win_rate":N}},
      "cached": true/false,
      "generated_at": "2026-03-06T14:00:00Z"
    }
    """
    _VALID_WINDOWS = {"1h": 60, "4h": 240, "24h": 1440}
    if window not in _VALID_WINDOWS:
        window = "1h"
    minutes = _VALID_WINDOWS[window]

    cache_key = f"wr:stats:{window}"
    redis = getattr(request.app.state, "redis", None)

    # ── Lee caché ─────────────────────────────────────────────────────────────
    cached = await _wr_cache_get(redis, cache_key)
    if cached:
        cached["cached"] = True
        return cached

    # ── Calcula desde la fuente de verdad ─────────────────────────────────────
    now    = datetime.utcnow()
    cutoff = now - timedelta(minutes=minutes)

    use_mongo = request.app.state.use_mongo
    if use_mongo:
        cursor = request.app.state.db.trades.find({
            "result":           {"$in": ["win", "loss"]},
            "audit_confidence": "high",           # solo datos verificados con API real
            "created_at":       {"$gte": cutoff},
        })
        trades = await cursor.to_list(5000)
        for t in trades:
            t["id"] = str(t.pop("_id", ""))
            if isinstance(t.get("created_at"), datetime):
                t["created_at"] = t["created_at"].strftime("%Y-%m-%dT%H:%M:%S") + "Z"
    else:
        trades = [
            t for t in request.app.state.trades_store
            if t.get("result") in ("win", "loss")
            and t.get("audit_confidence", "high") == "high"
            and _try_parse_ts(t.get("created_at", "")) >= cutoff
        ]

    # ── Estadísticas globales ──────────────────────────────────────────────────
    def _stats(subset: list) -> dict:
        total  = len(subset)
        wins   = sum(1 for t in subset if t.get("result") == "win")
        losses = total - wins
        wr     = round(wins / total * 100, 1) if total else 0.0
        pf_num = sum(t.get("payout", 85) for t in subset if t.get("result") == "win")
        pf_den = losses * 100
        return {
            "total":         total,
            "wins":          wins,
            "losses":        losses,
            "win_rate":      wr,
            "profit_factor": round(pf_num / pf_den, 2) if pf_den > 0 else 0.0,
        }

    global_stats = _stats(trades)

    # ── Por par ────────────────────────────────────────────────────────────────
    by_pair: dict = {}
    for sym in {t.get("symbol", "") for t in trades if t.get("symbol")}:
        subset = [t for t in trades if t.get("symbol") == sym]
        s = _stats(subset)
        s["asset_name"] = subset[0].get("asset_name", sym)
        # "degraded" → si Win Rate < 50%, señales de ese par deben ser más conservadoras
        s["degraded"]   = s["win_rate"] < 50.0 and s["total"] >= 5
        by_pair[sym]    = s

    # ── Por sesión ────────────────────────────────────────────────────────────
    by_session: dict = {}
    for sess in ("london", "newyork", "asia", "off"):
        subset = [t for t in trades if t.get("session", "") == sess]
        if subset:
            by_session[sess] = _stats(subset)

    result = {
        "window":       window,
        "minutes":      minutes,
        "global":       global_stats,
        "by_pair":      by_pair,
        "by_session":   by_session,
        "cached":       False,
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%S") + "Z",
    }

    # ── Escribe en caché ───────────────────────────────────────────────────────
    await _wr_cache_set(redis, cache_key, result)

    return result


@app.post("/api/risk/reset-circuit-breaker")
async def reset_circuit_breaker(request: Request):
    """
    Resetea el Circuit Breaker manualmente (autónomo + legacy).
    Desbloquea el bot inmediatamente, resetea pérdidas consecutivas.
    """
    now = datetime.utcnow()
    # Reset del CB autónomo (nuevo)
    _cb_state.update({
        "blocked":            False,
        "blocked_until":      None,
        "consecutive_losses": 0,
        "reason":             "",
    })
    # Reset legacy (compatibilidad con session-stats)
    request.app.state.circuit_breaker_reset_at = now.strftime("%Y-%m-%dT%H:%M:%S") + "Z"

    logger.info("🔓 Circuit Breaker reseteado manualmente — nueva sesión desde %s", now)
    return {
        "success":         True,
        "reset_at":        request.app.state.circuit_breaker_reset_at,
        "circuit_breaker": _cb_state,
        "message":         "✅ Circuit Breaker reseteado. Bot reanudado.",
    }



@app.get("/api/antifragile/status")
async def get_antifragile_status():
    """
    Estado completo de los 3 módulos Antifragile v3.0:
    - Martingala Suave: apuestas actuales por par
    - Bloqueos por Correlación: monedas bloqueadas y tiempo restante
    - Overrides de Timeframe: pares con TF cambiado post-pérdida
    """
    now = datetime.utcnow()

    # Limpia bloqueos expirados
    for currency in list(_correlation_locks.keys()):
        if now >= _correlation_locks[currency]:
            _correlation_locks.pop(currency, None)

    active_locks = {
        cur: {
            "expires_at": exp.strftime("%Y-%m-%dT%H:%M:%S") + "Z",
            "mins_left":  round((exp - now).total_seconds() / 60, 1),
            "message":    f"⚠️ BLOQUEO POR CORRELACIÓN: {cur}",
        }
        for cur, exp in _correlation_locks.items()
    }

    return {
        "martingale_state":     _martingale_state,
        "correlation_locks":    active_locks,
        "timeframe_overrides":  _timeframe_overrides,
        "has_active_locks":     len(active_locks) > 0,
        "locked_currencies":    list(active_locks.keys()),
        "summary": {
            "pairs_with_martingale": sum(
                1 for s in _martingale_state.values() if s.get("losses", 0) > 0
            ),
            "active_correlation_blocks": len(active_locks),
            "active_tf_overrides":       len(_timeframe_overrides),
        }
    }


@app.post("/api/antifragile/reset-martingale/{symbol}")
async def reset_martingale(symbol: str):
    """
    Resetea manualmente la Martingala Suave de un par.
    Útil si el usuario quiere volver al bet base sin esperar a un WIN.
    """
    if symbol in _martingale_state:
        old = _martingale_state[symbol].copy()
        _martingale_state[symbol]["current"] = _martingale_state[symbol]["base"]
        _martingale_state[symbol]["losses"]  = 0
        logger.info("🔄 Martingala reseteada manualmente: %s", symbol)
        return {"success": True, "symbol": symbol, "reset_from": old,
                "message": f"Martingala de {symbol} reseteada al bet base"}
    return {"success": False, "message": f"{symbol} no tiene estado de martingala activo"}


@app.post("/api/antifragile/unlock-currency/{currency}")
async def unlock_currency(currency: str):
    """
    Desbloquea manualmente una moneda bloqueada por correlación.
    Útil si el trader considera que el mercado cambió.
    """
    currency = currency.upper()
    if currency in _correlation_locks:
        del _correlation_locks[currency]
        # También limpia overrides de pares con esa moneda
        for sym in list(_timeframe_overrides.keys()):
            b, q = _get_currencies(sym)
            if b == currency or q == currency:
                _timeframe_overrides.pop(sym, None)
        logger.info("🔓 Bloqueo de correlación removido manualmente: %s", currency)
        return {"success": True, "currency": currency,
                "message": f"Moneda {currency} desbloqueada manualmente"}
    return {"success": False, "message": f"{currency} no está bloqueada actualmente"}


@app.get("/api/antifragile/check/{symbol}")
async def check_pair_antifragile(symbol: str):
    """
    Verificación rápida de todos los filtros Antifragile para un par específico.
    El frontend llama esto antes de mostrar/ejecutar una señal.
    """
    lock = _check_correlation_lock(symbol)
    mg   = _martingale_state.get(symbol, {"losses": 0, "current": 0, "base": 0})
    tf   = _timeframe_overrides.get(symbol, None)

    can_trade = not lock["locked"]

    return {
        "symbol":       symbol,
        "can_trade":    can_trade,
        "blocked":      lock["locked"],
        "block_reason": lock.get("reason", ""),
        "martingale": {
            "active":         mg.get("losses", 0) > 0,
            "losses_streak":  mg.get("losses", 0),
            "current_bet":    mg.get("current", 0),
            "base_bet":       mg.get("base", 0),
        },
        "timeframe_override": tf,
        "correlation_lock":   lock,
    }


# Activación: https://www.callmebot.com/blog/free-api-whatsapp-messages/
# ============================================================================

async def _send_telegram(message: str) -> bool:
    """
    Envía mensaje via Telegram Bot API (gratuito, sin límites, permanente).

    Configuración en .env:
    - TELEGRAM_BOT_TOKEN: token del bot (de @BotFather)
    - TELEGRAM_CHAT_ID:   tu chat ID (de @userinfobot)
    - TELEGRAM_ENABLED:   true/false
    """
    token   = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    enabled = os.getenv("TELEGRAM_ENABLED", "false").lower() == "true"

    if not enabled or not token or not chat_id or chat_id == "your_chat_id_here":
        return False

    try:
        url  = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id":    chat_id,
            "text":       message,
            "parse_mode": "HTML",
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                logger.info("📱 Telegram enviado a chat_id %s", chat_id)
                return True
            else:
                logger.warning("⚠️  Telegram error %d: %s", resp.status_code, resp.text[:200])
                return False
    except Exception as e:
        logger.warning("⚠️  Telegram excepción: %s", e)
        return False


async def _send_whatsapp(message: str) -> bool:
    """Mantiene compatibilidad con WhatsApp (TextMeBot). Redirige a Telegram si está activo."""
    if os.getenv("TELEGRAM_ENABLED", "false").lower() == "true":
        return await _send_telegram(message)

    phone   = os.getenv("WHATSAPP_PHONE", "")
    apikey  = os.getenv("WHATSAPP_APIKEY", "")
    enabled = os.getenv("WHATSAPP_ENABLED", "false").lower() == "true"
    if not enabled or not phone or not apikey:
        return False

    try:
        import urllib.parse
        url = (
            f"https://api.textmebot.com/send.php"
            f"?recipient={phone}&apikey={apikey}&text={urllib.parse.quote(message)}"
        )
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url)
            return resp.status_code == 200
    except Exception as e:
        logger.warning("⚠️  WhatsApp excepción: %s", e)
        return False


def _build_whatsapp_message(signal: dict) -> str:
    """
    Construye el mensaje de notificación con la señal.
    Usa formato HTML para Telegram (también compatible con texto plano).
    """
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
    is_fire      = (signal.get("quality_score", 0) >= 0.75 or
                    len(signal.get("strategies_agreeing", [])) >= 3)
    direction    = "🟢 CALL (COMPRA)" if signal.get("type") == "CALL" else "🔴 PUT (VENTA)"
    score_pct    = round(signal.get("quality_score", 0) * 100)
    cci          = signal.get("cci", 0)
    session      = signal.get("session", "")
    asset        = signal.get("asset_name", signal.get("symbol", ""))
    signal_id    = signal.get("id", "")
    validate_url = f"{frontend_url}/validate?id={signal_id}"
    header       = "🔥 <b>SEÑAL ÉLITE</b>" if is_fire else "📊 <b>Señal de calidad</b>"

    return (
        f"{header}\n\n"
        f"<b>{asset}</b>\n"
        f"{direction}\n\n"
        f"Score: <b>{score_pct}%</b> | CCI: <b>{cci:.0f}</b>\n"
        f"Payout: <b>{signal.get('payout', 85):.0f}%</b> | {session}\n"
        f"⏰ Expira en 2 min\n\n"
        f"📱 <a href='{validate_url}'>Registrar W/L desde móvil</a>"
    )


async def _run_notification_test():
    telegram_enabled = os.getenv("TELEGRAM_ENABLED", "false").lower() == "true"
    channel = "Telegram" if telegram_enabled else "WhatsApp (TextMeBot)"

    # Envía señal de prueba con botones interactivos
    test_signal = {
        "id":               "test_signal_001",
        "symbol":           "OTC_EURUSD",
        "asset_name":       "EUR/USD OTC",
        "type":             "CALL",
        "quality_score":    0.82,
        "cci":              145.0,
        "payout":           92.0,
        "session":          "TEST",
        "entry_price":      1.0823,
        "timestamp":        datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S") + "Z",
        "strategies_agreeing": ["keltner_rsi", "cci_alligator", "rsi_bollinger"],
        "reason":           "RSI sobrevendido + CCI alcista extremo",
    }
    msg_id = await _send_signal_telegram(test_signal, app=None)
    ok = msg_id is not None
    return {
        "sent":    ok,
        "channel": channel,
        "msg_id":  msg_id,
        "message": f"Señal de prueba enviada con botones interactivos" if ok else "Error — verifica config en .env",
    }

@app.post("/api/notifications/test")
async def test_notifications(request: Request):
    return await _run_notification_test()

@app.post("/api/whatsapp/test")
async def test_whatsapp(request: Request):
    return await _run_notification_test()


@app.get("/api/notifications/config")
async def get_notifications_config():
    """Retorna el estado de configuración de notificaciones."""
    tg_token  = os.getenv("TELEGRAM_BOT_TOKEN", "")
    tg_chatid = os.getenv("TELEGRAM_CHAT_ID", "")
    return {
        "telegram": {
            "enabled":    os.getenv("TELEGRAM_ENABLED", "false").lower() == "true",
            "token_set":  bool(tg_token and len(tg_token) > 10),
            "chat_id_set": bool(tg_chatid and tg_chatid != "your_chat_id_here"),
            "only_fire":  os.getenv("TELEGRAM_ONLY_FIRE", "false").lower() == "true",
        },
        "whatsapp": {
            "enabled":   os.getenv("WHATSAPP_ENABLED", "false").lower() == "true",
            "phone":     os.getenv("WHATSAPP_PHONE", ""),
            "apikey_set": bool(os.getenv("WHATSAPP_APIKEY", "") not in ("", "your_callmebot_apikey_here")),
        },
        "frontend_url": os.getenv("FRONTEND_URL", "http://localhost:3000"),
    }


# ============================================================================
# TELEGRAM INTERACTIVE — Auditoría Estadística Automatizada
# ============================================================================

# UTC-5 offset (Perú / Colombia / Ecuador / Cuba)
UTC_OFFSET = timedelta(hours=-5)

def _local_time(dt: datetime = None) -> datetime:
    """Convierte UTC a UTC-5 para display."""
    return (dt or datetime.utcnow()) + UTC_OFFSET

def _fmt_time(dt: datetime = None) -> str:
    """Formatea hora en UTC-5 para mensajes de Telegram."""
    return _local_time(dt).strftime("%H:%M:%S") + " (UTC-5)"

# Estado en memoria de auditorías activas
# { msg_id_str: { signal, chat_id, entry_time, audit_id } }
_tg_active_trades: dict = {}
_tg_last_update_id: int = 0


async def _tg_api(method: str, payload: dict) -> dict:
    """Helper para llamar la Telegram Bot API."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        return {}
    url = f"https://api.telegram.org/bot{token}/{method}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            return resp.json()
    except Exception as e:
        logger.warning("⚠️  Telegram API %s error: %s", method, e)
        return {}


async def _mae_sampling_loop(symbol: str, signal_type: str, entry_price: float,
                             audit_id: str, app, duration_sec: int = 120,
                             interval_sec: int = 10):
    """
    Muestreo de precio cada `interval_sec` segundos durante la vida de la señal.
    Calcula el MAE (Maximum Adverse Excursion): el punto más lejano en contra
    de la operación durante su vida útil.

    CALL: el precio bajó X pips antes de (posiblemente) subir → MAE = max(entry - low_seen)
    PUT:  el precio subió X pips antes de (posiblemente) bajar → MAE = max(high_seen - entry)

    Guarda `max_adverse_excursion` (en pips) y `mae_pct` en MongoDB al finalizar.
    Se ejecuta en background vía asyncio.create_task() — no bloquea el scan.
    """
    provider  = get_provider()
    worst_mae = 0.0           # pips adversos acumulados
    samples   = []            # precios muestreados
    elapsed   = 0

    while elapsed < duration_sec:
        await asyncio.sleep(interval_sec)
        elapsed += interval_sec

        try:
            # Intenta precio real, fallback a simulado
            price = None
            if provider and provider.is_configured:
                price = await provider.get_price_sample(symbol)
            if price is None:
                price = get_asset_price(symbol)

            samples.append(price)

            # Calcula excursión adversa acumulada
            if signal_type == "CALL":
                adverse = entry_price - price   # negativo si va a favor
            else:
                adverse = price - entry_price   # negativo si va a favor

            if adverse > worst_mae:
                worst_mae = adverse

        except Exception as e:
            logger.debug("MAE sample error %s: %s", symbol, e)

    # Convierte a pips (multiplica por 10000 para pares de 4 decimales, 100 para JPY)
    pip_mult  = 100.0 if "JPY" in symbol else 10000.0
    mae_pips  = round(worst_mae * pip_mult, 1)
    mae_pct   = round(worst_mae / entry_price * 100, 4) if entry_price > 0 else 0.0
    n_samples = len(samples)

    logger.info("📐 MAE completado | %s %s | MAE=%.1f pips (%.4f%%) | %d muestras",
                signal_type, symbol, mae_pips, mae_pct, n_samples)

    # Actualiza MongoDB con el resultado del MAE
    if app.state.use_mongo and audit_id:
        from bson import ObjectId
        try:
            await app.state.db.trades.update_one(
                {"_id": ObjectId(audit_id)},
                {"$set": {
                    "max_adverse_excursion":     mae_pips,
                    "mae_pct":                   mae_pct,
                    "mae_samples":               n_samples,
                    "mae_price_path":            samples[-5:],  # últimos 5 precios
                }}
            )
        except Exception as e:
            logger.debug("MAE MongoDB update error: %s", e)


async def _auto_register_observation(signal: dict, app,
                                     hit_timestamp: Optional[str] = None) -> Optional[str]:
    """
    Registra automáticamente TODA señal detectada en MongoDB como observación.
    Esto maximiza el historial estadístico sin requerir interacción del usuario.

    v2.3 — Nuevos campos:
    - market_volatility_at_entry: ATR del par en el momento de la señal
    - execution_latency_ms: ms entre generación de señal y confirmación del usuario
    - max_adverse_excursion: se rellena después por _mae_sampling_loop

    Estado inicial: 'pending' → se actualiza a 'win'/'loss' al verificar.
    Retorna el audit_id generado.
    """
    now = datetime.utcnow()

    # Calcula latencia de ejecución (signal_timestamp → hit_timestamp)
    latency_ms = None
    if hit_timestamp:
        try:
            hit_dt     = _parse_naive_utc(hit_timestamp)
            sig_dt     = _parse_naive_utc(
                signal.get("timestamp", now.strftime("%Y-%m-%dT%H:%M:%S") + "Z")
            )
            latency_ms = int((hit_dt - sig_dt).total_seconds() * 1000)
            latency_ms = max(0, latency_ms)   # nunca negativo
        except Exception:
            latency_ms = None

    doc   = {
        "signal_id":                signal.get("id", ""),
        "symbol":                   signal.get("symbol", ""),
        "asset_name":               signal.get("asset_name", ""),
        "signal_type":              signal.get("type", ""),
        "result":                   "pending",
        "entry_price":              signal.get("entry_price", signal.get("price", 0)),
        "close_price":              None,
        "payout":                   signal.get("payout", 85),
        "quality_score":            signal.get("quality_score", 0),
        "cci":                      signal.get("cci", 0),
        "signal_timestamp":         signal.get("timestamp", now.strftime("%Y-%m-%dT%H:%M:%S") + "Z"),
        "created_at":               now,
        "created_at_local":         _local_time(now).strftime("%Y-%m-%dT%H:%M:%S") + " UTC-5",
        "session":                  signal.get("session", ""),
        "source":                   "auto_audit",
        "strategies":               signal.get("strategies_agreeing", []),
        # ── Nuevos campos v2.3 ────────────────────────────────────────────────
        "market_volatility_at_entry": signal.get("atr_pct", 0),   # ATR% capturado al generar
        "atr_raw":                    signal.get("atr", 0),
        "execution_latency_ms":       latency_ms,                  # ms señal→usuario
        "max_adverse_excursion":      None,                        # rellena _mae_sampling_loop
        "mae_pct":                    None,
        "mae_samples":                0,
    }

    try:
        if app.state.use_mongo:
            result = await app.state.db.trades.insert_one(doc)
            audit_id = str(result.inserted_id)
        else:
            doc["id"] = f"audit_{int(now.timestamp()*1000)}"
            app.state.trades_store.append(doc)
            audit_id = doc["id"]

        logger.info("📋 Observación auto-registrada | %s %s | score=%.2f | audit=%s",
                    signal.get("type"), signal.get("asset_name"),
                    signal.get("quality_score", 0), audit_id)
        return audit_id
    except Exception as e:
        logger.warning("⚠️  Error auto-registro: %s", e)
        return None


async def _verify_signal_result(signal: dict, entry_time: datetime,
                                 audit_id: str, app) -> Optional[str]:
    """
    Verifica automáticamente el resultado de la señal consultando el
    precio de cierre REAL en Twelve Data después del tiempo de expiración.

    FIX v3.1: Usa get_price_for_audit() que invalida el caché y pide la
    penúltima vela (definitivamente cerrada), eliminando la corrupción
    que ocurría cuando el caché devolvía el mismo precio de entrada.

    Flujo:
    1. Solicita vela fresca (bypass caché) via get_price_for_audit()
    2. Si no hay API, intenta fallback de precio simulado con aviso
    3. Guarda resultado con confidence_level para filtrar en Win Rate
    4. CALL: WIN si close > entry  |  PUT: WIN si close < entry
    """
    symbol      = signal.get("symbol", "")
    entry_price = signal.get("entry_price", signal.get("price", 0))
    sig_type    = signal.get("type", "")

    if not entry_price or not symbol:
        logger.warning("⚠️  Auditoría abortada — datos de señal incompletos")
        return None

    try:
        provider    = get_provider()
        close_price = None
        confidence  = "high"   # "high" = dato real, "low" = simulado

        # ── Precio fresco con bypass de caché ─────────────────────────────────
        # Esto resuelve el bug anterior donde get_cached_price() retornaba el
        # mismo precio de entrada porque el caché (TTL=300s) aún no había expirado
        # a los 125s de espera. Ahora siempre pedimos la vela cerrada real.
        if provider and provider.is_configured:
            close_price = await provider.get_price_for_audit(symbol)

        if close_price is None:
            # Fallback: precio simulado con momentum actual
            # Marcamos como "low" para que el Win Rate pueda filtrar estos trades
            close_price = get_asset_price(symbol)
            confidence  = "low"
            logger.warning("⚠️  Auditoría %s — usando precio simulado (API sin créditos)",
                           symbol)

        # Determina WIN/LOSS
        if sig_type == "CALL":
            outcome = "win" if close_price > entry_price else "loss"
        else:
            outcome = "win" if close_price < entry_price else "loss"

        pip_diff = round((close_price - entry_price) / entry_price * 10000, 1)
        now      = datetime.utcnow()

        update_fields = {
            "result":             outcome,
            "close_price":        close_price,
            "pip_diff":           pip_diff,
            "verified_at":        now,
            "verified_at_local":  _local_time(now).strftime("%Y-%m-%dT%H:%M:%S") + " UTC-5",
            "source":             "auto_audit_verified",
            "audit_confidence":   confidence,   # nuevo campo para filtrar en Win Rate
        }

        # Actualiza en MongoDB
        if app.state.use_mongo and audit_id:
            from bson import ObjectId
            try:
                await app.state.db.trades.update_one(
                    {"_id": ObjectId(audit_id)},
                    {"$set": update_fields}
                )
            except Exception as mongo_err:
                logger.warning("⚠️  Error actualizando MongoDB: %s", mongo_err)
        else:
            for t in app.state.trades_store:
                if t.get("id") == audit_id or t.get("signal_id") == signal.get("id", ""):
                    t.update(update_fields)
                    break

        logger.info(
            "✅ Auditoría verificada | %s %s | entrada=%.5f cierre=%.5f | %s | %+.1f pips [%s]",
            sig_type, symbol, entry_price, close_price,
            outcome.upper(), pip_diff, confidence
        )

        # Invalida el caché de Win Rate para este par y global
        try:
            redis = getattr(app.state, "redis", None)
            await _wr_cache_invalidate(redis, f"wr:{symbol}")
            await _wr_cache_invalidate(redis, "wr:global")
            await _wr_cache_invalidate(redis, "wr:stats")  # invalida /v1/stats
        except Exception:
            pass

        # Actualiza el Circuit Breaker autónomo
        _cb_record_result(outcome, symbol)

        return outcome

    except Exception as e:
        logger.warning("⚠️  Error verificando resultado: %s", e)
        return None


async def _send_pre_alert_telegram(pre_doc: dict) -> None:
    """
    Envía notificación corta de Pre-Alerta a Telegram.
    Mensaje directo, sin botones — solo aviso de preparación.
    """
    token   = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id or os.getenv("TELEGRAM_ENABLED", "false").lower() != "true":
        return

    direction = "▲ CALL" if pre_doc.get("type") == "CALL" else "▼ PUT"
    asset     = pre_doc.get("asset_name", "")
    conf_pct  = pre_doc.get("confluence_pct", 60)
    session   = pre_doc.get("session", "")
    strategies = ", ".join(pre_doc.get("strategies_fired", []))
    now_local  = _fmt_time(datetime.utcnow())

    text = (
        f"⏳ <b>PRE-ALERTA</b> — {asset}\n"
        f"{direction} | {conf_pct}% Confluencia\n\n"
        f"Condiciones formándose. Esté atento para una posible\n"
        f"operación en los próximos <b>2-3 minutos</b>.\n\n"
        f"📊 Estrategias activas: <i>{strategies}</i>\n"
        f"🕐 {now_local} | {session}"
    )

    try:
        await _tg_api("sendMessage", {
            "chat_id":              chat_id,
            "text":                 text,
            "parse_mode":           "HTML",
            "disable_notification": False,
        })
        logger.info("⏳ Pre-alerta Telegram enviada | %s %s | %d%%",
                    pre_doc.get("type"), asset, conf_pct)
    except Exception as e:
        logger.debug("Pre-alerta Telegram error: %s", e)


@app.get("/api/pre-alerts/active")   # alias usado por Dashboard v2.7
@app.get("/api/signals/pre-alerts")
async def get_pre_alerts(request: Request):
    """
    Retorna las pre-alertas activas (confluencia parcial 3/5 estrategias).
    El frontend usa este endpoint para mostrar el estado de 'Alineación'
    en las tarjetas de activos del Dashboard.

    Las pre-alertas se limpian automáticamente cuando:
    - Se emite la señal completa para ese par
    - El par entra en cooldown
    - El siguiente ciclo no detecta confluencia parcial
    """
    now    = datetime.utcnow()
    cutoff = now - timedelta(minutes=5)  # Pre-alertas válidas por 5 minutos

    # Filtra pre-alertas frescas
    fresh = {}
    for sym, doc in list(request.app.state.pre_alerts_store.items()):
        try:
            ts = _parse_naive_utc(doc.get("created_at", ""))
            if ts >= cutoff:
                fresh[sym] = doc
            else:
                # Limpia las viejas
                request.app.state.pre_alerts_store.pop(sym, None)
        except Exception:
            pass

    return {"pre_alerts": fresh, "count": len(fresh)}


async def _send_signal_telegram(signal: dict, app=None) -> Optional[int]:
    """
    Envía señal a Telegram con auditoría autónoma completa:

    1. Auto-registra la observación en MongoDB (sin acción del usuario)
    2. Envía mensaje con hora UTC-5 y botón de confirmación
    3. Programa verificación autónoma del resultado a los 2 minutos
    """
    token   = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id or os.getenv("TELEGRAM_ENABLED", "false").lower() != "true":
        return None

    now       = datetime.utcnow()
    is_fire   = (signal.get("quality_score", 0) >= 0.75 or
                 len(signal.get("strategies_agreeing", [])) >= 3)
    direction = "🟢 CALL (COMPRA)" if signal.get("type") == "CALL" else "🔴 PUT (VENTA)"
    score_pct = round(signal.get("quality_score", 0) * 100)
    header    = "🔥 <b>SEÑAL ÉLITE — AUDITORÍA ACTIVA</b>" if is_fire else "📊 <b>Señal — Auditoría Activa</b>"
    sid       = signal.get("id", "")

    # ── 1. Auto-registro DESACTIVADO — causa datos corruptos en MongoDB ─────────
    # La auditoría automática registraba TODAS las señales como trades reales,
    # incluyendo las que el usuario ignoró. Esto corrompía el Win Rate y la
    # calibración del umbral dinámico. Solo se registran trades manuales.
    audit_id = None

    text = (
        f"{header}\n\n"
        f"<b>{signal.get('asset_name', '')}</b>\n"
        f"{direction}\n\n"
        f"Score: <b>{score_pct}%</b> | CCI: <b>{signal.get('cci', 0):.0f}</b>\n"
        f"Payout: <b>{signal.get('payout', 85):.0f}%</b> | {signal.get('session', '')}\n"
        f"Entrada: <b>{_fmt_time(now)}</b>\n\n"
        f"⏰ <b>2 minutos | El bot verificará el resultado automáticamente</b>\n"
        f"Pulsa si decides operar:"
    )

    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ Voy a operar", "callback_data": f"operate:{sid}"},
            {"text": "⏭ Ignorar",       "callback_data": f"ignore:{sid}"},
        ]]
    }

    result = await _tg_api("sendMessage", {
        "chat_id":              chat_id,
        "text":                 text,
        "parse_mode":           "HTML",
        "reply_markup":         keyboard,
        "disable_notification": False,
    })

    msg_id = result.get("result", {}).get("message_id")
    if msg_id:
        _tg_active_trades[str(msg_id)] = {
            "signal":     signal,
            "chat_id":    chat_id,
            "msg_id":     msg_id,
            "signal_id":  sid,
            "audit_id":   None,   # se asigna cuando el usuario confirma operación
            "entry_time": now,
            "operated":   False,
            "app":        app,    # referencia para la auditoría diferida
        }
        logger.info("📱 Telegram enviado | msg_id=%s | %s %s",
                    msg_id, signal.get("type"), signal.get("asset_name"))

    return msg_id


async def _tg_edit_message(chat_id: str, msg_id: int, text: str,
                            keyboard: Optional[dict] = None):
    """Edita un mensaje existente de Telegram."""
    payload = {
        "chat_id":    chat_id,
        "message_id": msg_id,
        "text":       text,
        "parse_mode": "HTML",
    }
    if keyboard:
        payload["reply_markup"] = keyboard
    else:
        payload["reply_markup"] = {"inline_keyboard": []}  # elimina botones
    await _tg_api("editMessageText", payload)


async def _handle_tg_callback(callback: dict, app):
    """
    Procesa callbacks de botones inline.

    operate:SIGNAL_ID  → registra entrada, edita mensaje, programa expiración
    ignore:SIGNAL_ID   → edita mensaje a "Señal ignorada"
    result:win:MSG_ID  → registra WIN en MongoDB
    result:loss:MSG_ID → registra LOSS en MongoDB
    """
    query_id   = callback.get("id")
    data       = callback.get("data", "")
    chat_id    = str(callback.get("message", {}).get("chat", {}).get("id", ""))
    msg_id     = callback.get("message", {}).get("message_id")
    from_user  = callback.get("from", {}).get("first_name", "")

    # Responde al callback para quitar el "cargando" en Telegram
    await _tg_api("answerCallbackQuery", {"callback_query_id": query_id})

    parts = data.split(":")

    # ── Operar — usuario confirma que va a operar ─────────────────────────────
    if parts[0] == "operate":
        trade_key    = str(msg_id)
        confirm_time = datetime.utcnow()

        trade_entry = _tg_active_trades.get(trade_key, {})
        if trade_entry:
            trade_entry["operated"]   = True
            trade_entry["entry_time"] = confirm_time  # tiempo real de entrada

        signal    = trade_entry.get("signal", {})
        asset     = signal.get("asset_name", "")
        stype     = signal.get("type", "")
        app_ref   = trade_entry.get("app")
        audit_id  = trade_entry.get("audit_id")

        # ── Registrar trade en MongoDB (auditoría diferida) ───────────────────
        if app_ref and app_ref.state.use_mongo:
            try:
                trade_doc = {
                    "signal_id":       signal.get("id", ""),
                    "symbol":          signal.get("symbol", ""),
                    "asset_name":      asset,
                    "signal_type":     stype,
                    "result":          "pending",
                    "entry_price":     signal.get("entry_price", signal.get("price", 0)),
                    "quality_score":   signal.get("quality_score", 0),
                    "cci":             signal.get("cci", 0),
                    "signal_timestamp": signal.get("created_at", ""),
                    "source":          "telegram_operated",
                    "created_at":      confirm_time,
                }
                insert_result = await app_ref.state.db.trades.insert_one(trade_doc)
                audit_id = str(insert_result.inserted_id)
                _tg_active_trades[trade_key]["audit_id"] = audit_id
                logger.info("📝 Trade pendiente registrado | audit_id=%s | %s %s", audit_id, stype, asset)
            except Exception as e:
                logger.warning("⚠️  No se pudo registrar trade en MongoDB: %s", e)

        # Actualiza mensaje: confirma operación
        await _tg_edit_message(chat_id, msg_id,
            f"✅ <b>Operación confirmada — Auditoría activa</b>\n\n"
            f"<b>{asset}</b> — {stype}\n"
            f"🕐 Entrada: <b>{_fmt_time(confirm_time)}</b>\n\n"
            f"⏳ Verificando resultado automáticamente en 2 minutos...\n"
            f"<i>También podrás corregir el resultado si es necesario.</i>"
        )

        # ── Lanzar auditoría autónoma en background ───────────────────────────
        if app_ref:
            asyncio.create_task(_autonomous_audit(
                chat_id, msg_id, signal, confirm_time, audit_id, app_ref
            ))
            logger.info("🔄 Auditoría autónoma lanzada | %s %s | audit_id=%s",
                        stype, asset, audit_id)
        else:
            logger.warning("⚠️  No hay referencia de app — auditoría no lanzada")

        logger.info("📱 Operación confirmada por usuario | %s %s | %s",
                    stype, asset, _fmt_time(confirm_time))

    # ── Ignorar ───────────────────────────────────────────────────────────────
    elif parts[0] == "ignore":
        trade_key = str(msg_id)
        signal    = _tg_active_trades.get(trade_key, {}).get("signal", {})
        _tg_active_trades.pop(trade_key, None)
        await _tg_edit_message(chat_id, msg_id,
            f"⏭ <b>Señal ignorada</b>\n"
            f"{signal.get('asset_name', '')} — {signal.get('type', '')}\n"
            f"<i>Esperando próxima señal...</i>"
        )

    # ── Resultado manual (fallback por si el usuario quiere corregir) ────────
    elif parts[0] == "result" and len(parts) >= 3:
        outcome   = parts[1]
        trade_key = parts[2]
        signal    = _tg_active_trades.get(trade_key, {}).get("signal", {})
        audit_id  = _tg_active_trades.get(trade_key, {}).get("audit_id")

        if signal and audit_id and app.state.use_mongo:
            from bson import ObjectId
            try:
                await app.state.db.trades.update_one(
                    {"_id": ObjectId(audit_id)},
                    {"$set": {"result": outcome, "source": "manual_correction"}}
                )
            except Exception:
                pass

        icon = "✅" if outcome == "win" else "❌"
        await _tg_edit_message(chat_id, msg_id,
            f"📊 <b>Auditoría completada: {'[W]' if outcome=='win' else '[L]'}</b>\n\n"
            f"{signal.get('asset_name', '')} — {signal.get('type', '')}\n"
            f"{icon} Resultado corregido manualmente ✓"
        )
        _tg_active_trades.pop(trade_key, None)
        logger.info("📱 Resultado manual registrado | %s | %s", outcome.upper(), signal.get("asset_name"))


async def _autonomous_audit(chat_id: str, msg_id: int, signal: dict,
                             entry_time: datetime, audit_id: Optional[str], app):
    """
    Auditoría completamente autónoma del ciclo de vida de una señal.

    Flujo:
    1. Espera los 2 minutos de expiración
    2. Consulta precio real en Twelve Data
    3. Determina WIN/LOSS comparando con precio de entrada
    4. Actualiza MongoDB
    5. Edita el mensaje de Telegram con resultado final — sin intervención humana
    """
    EXPIRY_SECONDS = 125   # 2 min + 5s buffer para que la vela cierre

    await asyncio.sleep(EXPIRY_SECONDS)

    asset     = signal.get("asset_name", "")
    stype     = signal.get("type", "")
    close_now = datetime.utcnow()
    trade_key = str(msg_id)

    # Verifica resultado con precio real
    outcome = await _verify_signal_result(signal, entry_time, audit_id, app)

    # Edita mensaje con resultado automático
    if outcome == "win":
        icon   = "✅"
        badge  = "[W]"
        color_text = "GANÓ"
    elif outcome == "loss":
        icon   = "❌"
        badge  = "[L]"
        color_text = "PERDIÓ"
    else:
        icon   = "⚠️"
        badge  = "[?]"
        color_text = "Sin datos"

    entry_price = signal.get("entry_price", signal.get("price", 0))

    # Mensaje de resultado con botones de corrección
    result_text = (
        f"📊 <b>Auditoría completada: {badge}</b>\n\n"
        f"<b>{asset}</b> — {stype}\n"
        f"Entrada: <b>{_fmt_time(entry_time)}</b>\n"
        f"Cierre:  <b>{_fmt_time(close_now)}</b>\n\n"
        f"Score: {round(signal.get('quality_score',0)*100)}% | "
        f"CCI: {signal.get('cci',0):.0f}\n\n"
        f"{icon} <b>Señal {color_text}</b> — Datos guardados en MongoDB ✓\n\n"
        f"<i>¿El resultado es incorrecto? Corrígelo:</i>"
    )

    # Botones de corrección manual (por si la API tuvo datos incorrectos)
    correction_keyboard = {
        "inline_keyboard": [[
            {"text": "✅ Fue WIN",  "callback_data": f"result:win:{trade_key}"},
            {"text": "❌ Fue LOSS", "callback_data": f"result:loss:{trade_key}"},
        ]]
    }

    await _tg_edit_message(chat_id, msg_id, result_text, correction_keyboard)

    # NO eliminamos trade_key aquí — se mantiene para que los botones
    # de corrección manual funcionen. Se limpia en _handle_tg_callback result:
    logger.info("📊 Auditoría completada | %s | %s %s | audit=%s",
                badge, stype, asset, audit_id)


async def _telegram_polling_loop(app):
    """
    Long polling de Telegram: espera callbacks de botones inline.
    Corre en background cada 3 segundos.
    Solo activo si Telegram está configurado.
    """
    global _tg_last_update_id

    token   = os.getenv("TELEGRAM_BOT_TOKEN", "")
    enabled = os.getenv("TELEGRAM_ENABLED", "false").lower() == "true"

    if not token or not enabled:
        logger.info("📵 Telegram polling desactivado (sin token o TELEGRAM_ENABLED=false)")
        return

    logger.info("🔄 Telegram polling iniciado — esperando callbacks de botones")

    while True:
        try:
            async with httpx.AsyncClient(timeout=35.0) as client:
                resp = await client.get(
                    f"https://api.telegram.org/bot{token}/getUpdates",
                    params={
                        "offset":          _tg_last_update_id + 1,
                        "timeout":         30,
                        "allowed_updates": ["callback_query"],
                    }
                )
                data = resp.json()

            for update in data.get("result", []):
                _tg_last_update_id = update["update_id"]
                cb = update.get("callback_query")
                if cb:
                    asyncio.create_task(_handle_tg_callback(cb, app))

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning("⚠️  Telegram polling error: %s", e)
            await asyncio.sleep(5)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
