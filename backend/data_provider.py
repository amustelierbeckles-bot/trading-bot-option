"""
data_provider.py — Proveedor de datos de mercado real

Conecta con Twelve Data API (plan gratuito: 800 req/día).
Cache inteligente con TTL configurable para no agotar el límite.
Fallback automático a datos simulados si la API no está configurada.

Indicadores calculados en Python puro (sin pandas, sin numpy):
  RSI(14), CCI(20), EMA(9/21), Bollinger(20,2), Stochastic(14), MACD(12,26)
"""

import os
import time
import math
import random
import logging
import asyncio
from typing import Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# MAPEO OTC → Twelve Data
# Pocket Option usa prefijo OTC_, Twelve Data usa "EUR/USD"
# ─────────────────────────────────────────────────────────────────────────────
OTC_TO_TWELVE: Dict[str, str] = {
    "OTC_EURUSD": "EUR/USD",  "OTC_GBPUSD": "GBP/USD",
    "OTC_USDJPY": "USD/JPY",  "OTC_USDCHF": "USD/CHF",
    "OTC_AUDUSD": "AUD/USD",  "OTC_USDCAD": "USD/CAD",
    "OTC_NZDUSD": "NZD/USD",  "OTC_EURJPY": "EUR/JPY",
    "OTC_EURGBP": "EUR/GBP",  "OTC_EURAUD": "EUR/AUD",
    "OTC_EURCAD": "EUR/CAD",  "OTC_EURCHF": "EUR/CHF",
    "OTC_GBPJPY": "GBP/JPY",  "OTC_GBPAUD": "GBP/AUD",
    "OTC_GBPCAD": "GBP/CAD",  "OTC_GBPCHF": "GBP/CHF",
    "OTC_AUDJPY": "AUD/JPY",  "OTC_AUDCAD": "AUD/CAD",
    "OTC_CADJPY": "CAD/JPY",  "OTC_CHFJPY": "CHF/JPY",
}

# ─────────────────────────────────────────────────────────────────────────────
# CÁLCULO DE INDICADORES — Python puro, sin dependencias externas
# ─────────────────────────────────────────────────────────────────────────────

def calc_rsi(closes: List[float], period: int = 14) -> float:
    """RSI de Wilder con suavizado exponencial real. Retorna 50 si no hay datos."""
    if len(closes) < period + 1:
        return 50.0
    # Primera media: SMA de las primeras 'period' variaciones
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains  = [max(d, 0.0) for d in deltas]
    losses = [max(-d, 0.0) for d in deltas]
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    # Suavizado de Wilder: EMA con factor 1/period
    for i in range(period, len(deltas)):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
    if avg_l == 0:
        return 100.0
    return round(100 - 100 / (1 + avg_g / avg_l), 2)


def calc_cci(highs: List[float], lows: List[float],
             closes: List[float], period: int = 20) -> float:
    """Commodity Channel Index. Retorna 0 si no hay datos suficientes."""
    if len(closes) < period:
        return 0.0
    tp   = [(h + l + c) / 3 for h, l, c in zip(highs[-period:], lows[-period:], closes[-period:])]
    sma  = sum(tp) / period
    mad  = sum(abs(p - sma) for p in tp) / period
    return round((tp[-1] - sma) / (0.015 * mad), 2) if mad else 0.0


def calc_ema(closes: List[float], period: int) -> float:
    """EMA exponencial estándar."""
    if not closes:
        return 0.0
    if len(closes) < period:
        return sum(closes) / len(closes)
    k   = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for price in closes[period:]:
        ema = price * k + ema * (1 - k)
    return round(ema, 6)


def calc_bollinger(closes: List[float],
                   period: int = 20,
                   std_mult: float = 2.0) -> Tuple[float, float, float]:
    """Bandas de Bollinger. Retorna (upper, mid, lower)."""
    if len(closes) < period:
        p = closes[-1] if closes else 1.0
        return p, p, p
    w   = closes[-period:]
    sma = sum(w) / period
    std = math.sqrt(sum((p - sma) ** 2 for p in w) / period)
    return round(sma + std_mult * std, 6), round(sma, 6), round(sma - std_mult * std, 6)


def calc_stochastic(highs: List[float], lows: List[float],
                    closes: List[float], k_period: int = 14) -> float:
    """Oscilador estocástico %K."""
    if len(closes) < k_period:
        return 50.0
    h = max(highs[-k_period:])
    l = min(lows[-k_period:])
    return round((closes[-1] - l) / (h - l) * 100, 2) if h != l else 50.0


def calc_macd(closes: List[float],
              fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[float, float]:
    """
    MACD completo con línea de señal real.
    Retorna (macd_line, histogram).
    histogram = macd_line - signal_line  (positivo = impulso alcista)
    """
    if len(closes) < slow + signal:
        return 0.0, 0.0
    # Calcula MACD line para cada punto desde 'slow' en adelante
    macd_series = []
    for i in range(slow, len(closes) + 1):
        window = closes[:i]
        macd_series.append(calc_ema(window, fast) - calc_ema(window, slow))
    if len(macd_series) < signal:
        return round(macd_series[-1], 6), 0.0
    # Línea de señal = EMA(9) del MACD
    signal_line = calc_ema(macd_series, signal)
    macd_line   = macd_series[-1]
    histogram   = round(macd_line - signal_line, 6)
    return round(macd_line, 6), histogram


def calc_atr(highs: List[float], lows: List[float],
             closes: List[float], period: int = 14) -> float:
    """
    Average True Range (Wilder).

    True Range = max(High-Low, |High-PrevClose|, |Low-PrevClose|)
    ATR = media de los últimos `period` True Ranges.

    Retorna ATR en las mismas unidades del precio (pips implícitos).
    Retorna 0.0 si no hay datos suficientes.
    """
    if len(closes) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(closes)):
        hl  = highs[i]  - lows[i]
        hpc = abs(highs[i]  - closes[i - 1])
        lpc = abs(lows[i]   - closes[i - 1])
        trs.append(max(hl, hpc, lpc))
    return round(sum(trs[-period:]) / period, 6)


# ─────────────────────────────────────────────────────────────────────────────
# ESTRUCTURAS DE DATOS
# ─────────────────────────────────────────────────────────────────────────────

class CandleData:
    __slots__ = ("time", "open", "high", "low", "close", "volume")

    def __init__(self, time: str, open: float, high: float,
                 low: float, close: float, volume: float = 0):
        self.time   = time
        self.open   = open
        self.high   = high
        self.low    = low
        self.close  = close
        self.volume = volume

    def to_dict(self) -> dict:
        return {
            "time":   self.time,
            "open":   self.open,
            "high":   self.high,
            "low":    self.low,
            "close":  self.close,
            "volume": self.volume,
        }


class IndicatorSet:
    """Todos los indicadores técnicos para un par en un momento dado."""

    def __init__(self):
        self.rsi         : float = 50.0
        self.cci         : float = 0.0
        self.ema9        : float = 0.0
        self.ema21       : float = 0.0
        self.bb_upper    : float = 0.0
        self.bb_mid      : float = 0.0
        self.bb_lower    : float = 0.0
        self.stoch_k     : float = 50.0
        self.macd_line   : float = 0.0
        self.macd_hist   : float = 0.0   # Histograma MACD (macd_line - signal_line)
        self.atr         : float = 0.0   # Average True Range (volatilidad)
        self.atr_pct     : float = 0.0   # ATR como % del precio (normalizado)
        self.price       : float = 0.0
        self.price_change: float = 0.0   # % vs vela anterior
        self.trend       : str   = "neutral"
        self.candles     : List[CandleData] = []
        self.is_real     : bool  = False  # True si viene de API real
        self.last_candle_time: str = ""   # Timestamp de la última vela (para data_freshness_ms)
        self.fetch_wall_time : float = 0.0  # time.time() al recibir respuesta de API

    def compute(self, candles: List[CandleData]) -> None:
        """Calcula todos los indicadores a partir de las velas."""
        if not candles:
            return
        closes = [c.close for c in candles]
        highs  = [c.high  for c in candles]
        lows   = [c.low   for c in candles]

        self.price        = closes[-1]
        self.price_change = (
            round((closes[-1] - closes[-2]) / closes[-2] * 100, 4)
            if len(closes) > 1 else 0.0
        )
        self.rsi      = calc_rsi(closes)
        self.cci      = calc_cci(highs, lows, closes)
        self.ema9     = calc_ema(closes, 9)
        self.ema21    = calc_ema(closes, 21)
        self.bb_upper, self.bb_mid, self.bb_lower = calc_bollinger(closes)
        self.stoch_k  = calc_stochastic(highs, lows, closes)
        self.macd_line, self.macd_hist = calc_macd(closes)
        self.atr      = calc_atr(highs, lows, closes)
        self.atr_pct  = round(self.atr / self.price * 100, 4) if self.price > 0 else 0.0
        self.candles  = candles
        self.is_real  = True

        # Tendencia por cruce de EMAs
        if self.ema9 > self.ema21 * 1.0001:
            self.trend = "bullish"
        elif self.ema9 < self.ema21 * 0.9999:
            self.trend = "bearish"
        else:
            self.trend = "neutral"

    def summary(self) -> str:
        return (f"RSI={self.rsi:.1f} CCI={self.cci:.1f} "
                f"Stoch={self.stoch_k:.1f} MACD={self.macd_line:.5f} Hist={self.macd_hist:.5f} "
                f"ATR%={self.atr_pct:.3f} Trend={self.trend} "
                f"{'[REAL]' if self.is_real else '[SIM]'}")


# ─────────────────────────────────────────────────────────────────────────────
# PROVEEDOR TWELVE DATA
# ─────────────────────────────────────────────────────────────────────────────

class TwelveDataProvider:
    """
    Proveedor de datos reales con Twelve Data API.

    - Cache TTL: 5 min por defecto → ~2.5 req/par/hora
    - Con 8 pares × 2.5 × 16h = 320 req/día (muy por debajo del límite)
    - Fallback automático a datos simulados si la API no está configurada
    - Degradación elegante: si una petición falla, usa el cache anterior
    """

    BASE_URL     = "https://api.twelvedata.com"
    DAILY_LIMIT  = int(os.getenv("TWELVE_DATA_DAILY_LIMIT", "700"))  # Plan free:700, Plan $8:5000

    def __init__(self, api_key: Optional[str] = None, cache_ttl: int = 300):
        self.api_key      = api_key or os.getenv("TWELVE_DATA_API_KEY", "")
        self.cache_ttl    = cache_ttl
        self._cache       : Dict[str, dict] = {}
        self._client      : Optional[httpx.AsyncClient] = None
        self._req_today   : int   = 0
        self._req_reset_t : float = time.time() + 86400

        self.is_configured = bool(
            self.api_key and
            self.api_key not in ("", "demo", "your_api_key_here")
        )

        logger.info(
            "📡 TwelveDataProvider | API: %s | Cache TTL: %ds | Límite: %d/día",
            "✅ configurada" if self.is_configured else "❌ modo simulado",
            self.cache_ttl,
            self.DAILY_LIMIT,
        )

    async def start(self):
        self._client = httpx.AsyncClient(timeout=10.0)

    async def stop(self):
        if self._client:
            await self._client.aclose()

    # ── Control de rate limit ─────────────────────────────────────────────────
    def _within_limit(self) -> bool:
        now = time.time()
        if now > self._req_reset_t:
            self._req_today   = 0
            self._req_reset_t = now + 86400
        return self._req_today < self.DAILY_LIMIT

    # ── Obtener indicadores (con cache) ───────────────────────────────────────
    async def get_indicators(self, otc_symbol: str) -> Optional[IndicatorSet]:
        """
        Retorna indicadores reales con cache.
        Si API no configurada o falla → retorna None (se usa simulación).
        """
        cached = self._cache.get(otc_symbol)

        # Cache hit
        if cached and time.time() < cached["expires"]:
            return cached["indicators"]

        # Sin API configurada
        if not self.is_configured:
            return None

        # Límite diario alcanzado
        if not self._within_limit():
            logger.warning("⚠️  Límite diario alcanzado (%d req). Usando cache.", self._req_today)
            return cached["indicators"] if cached else None

        twelve_sym = OTC_TO_TWELVE.get(otc_symbol)
        if not twelve_sym:
            return None

        try:
            t_fetch_start = time.time()
            candles = await self._fetch_candles(twelve_sym, count=50)
            if not candles:
                return None

            ind = IndicatorSet()
            ind.compute(candles)
            ind.fetch_wall_time  = time.time()
            ind.last_candle_time = candles[-1].time if candles else ""

            self._cache[otc_symbol] = {
                "indicators": ind,
                "expires":    time.time() + self.cache_ttl,
            }
            self._req_today += 1

            logger.info(
                "📊 %s | %s | req #%d/%d | fetch=%.1fs",
                otc_symbol, ind.summary(), self._req_today, self.DAILY_LIMIT,
                time.time() - t_fetch_start,
            )
            return ind

        except Exception as exc:
            logger.warning("⚠️  Error %s → %s", otc_symbol, exc)
            # Fallback al cache anterior aunque esté expirado
            return cached["indicators"] if cached else None

    # ── Fetch de velas ────────────────────────────────────────────────────────
    async def _fetch_candles(self, symbol: str, interval: str = "1min",
                              count: int = 50) -> List[CandleData]:
        if not self._client:
            self._client = httpx.AsyncClient(timeout=10.0)

        resp = await self._client.get(
            f"{self.BASE_URL}/time_series",
            params={
                "symbol":     symbol,
                "interval":   interval,
                "outputsize": count,
                "apikey":     self.api_key,
                "format":     "JSON",
            }
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") == "error":
            raise ValueError(data.get("message", "API error"))

        # Twelve Data devuelve newest-first → invertimos para oldest-first
        candles = []
        for v in reversed(data.get("values", [])):
            candles.append(CandleData(
                time   = v["datetime"],
                open   = float(v["open"]),
                high   = float(v["high"]),
                low    = float(v["low"]),
                close  = float(v["close"]),
                volume = float(v.get("volume", 0)),
            ))
        return candles

    # ── Fetch en paralelo de múltiples pares ─────────────────────────────────
    async def get_indicators_batch(self, otc_symbols: List[str],
                                    max_concurrent: int = 2) -> Dict[str, Optional["IndicatorSet"]]:
        """
        Obtiene indicadores en paralelo con semáforo estricto de 2 concurrentes.

        Protección de créditos:
        - Pares en caché válido → respuesta INSTANTÁNEA, 0 requests API
        - Solo pares con caché expirado llegan al semáforo
        - max_concurrent=2 evita ráfagas que quemen el límite diario
        - Si el límite diario está alcanzado, devuelve caché aunque esté expirado

        Con cache_ttl=300s (5 min) y 8 pares:
          - Ciclo 1: 8 requests reales (primer arranque)
          - Ciclos 2-20: 0 requests (caché válido por 5 min)
          - Consumo efectivo: ~8 req cada 5 min = 96 req/día máximo
        """
        # Separa pares en caché válido vs los que necesitan fetch real
        cached_results: Dict[str, Optional["IndicatorSet"]] = {}
        need_fetch: List[str] = []

        for sym in otc_symbols:
            cached = self._cache.get(sym)
            if cached and time.time() < cached["expires"]:
                cached_results[sym] = cached["indicators"]
                logger.debug("📦 Cache hit: %s (sin request API)", sym)
            else:
                need_fetch.append(sym)

        if not need_fetch:
            return cached_results

        # Solo fetcha los que realmente necesitan actualización
        # Semáforo estricto: máximo 2 peticiones simultáneas
        semaphore = asyncio.Semaphore(max_concurrent)

        async def _fetch_one(symbol: str):
            async with semaphore:
                # Pequeña pausa entre requests para no saturar la API
                await asyncio.sleep(0.5)
                ind = await self.get_indicators(symbol)
                return symbol, ind

        logger.info("📡 Batch fetch: %d reales + %d desde caché | budget=%d/%d",
                    len(need_fetch), len(cached_results), self._req_today, self.DAILY_LIMIT)

        tasks   = [asyncio.create_task(_fetch_one(sym)) for sym in need_fetch]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        out = dict(cached_results)  # empieza con los del caché
        for item in results:
            if isinstance(item, Exception):
                logger.warning("⚠️  Batch fetch error: %s", item)
                continue
            symbol, ind = item
            out[symbol] = ind

        return out

    # ── Precio cacheado sin petición extra ────────────────────────────────────
    def get_cached_price(self, otc_symbol: str) -> Optional[float]:
        cached = self._cache.get(otc_symbol)
        if cached and time.time() < cached["expires"]:
            return cached["indicators"].price
        return None

    # ── Muestreo de precio en tiempo real para MAE ────────────────────────────
    async def get_price_sample(self, otc_symbol: str) -> Optional[float]:
        """
        Obtiene el precio actual del par de forma ligera (sin recalcular
        todos los indicadores). Diseñado para el muestreo de MAE cada 10s
        durante la auditoría autónoma.

        Prioridad:
        1. Cache fresco → retorna directo (0 requests)
        2. API real → fetch de 5 velas (mínimo posible)
        3. None → el llamador usa precio simulado
        """
        # 1. Usa cache si está fresco
        cached_price = self.get_cached_price(otc_symbol)
        if cached_price:
            return cached_price

        # 2. Fetch mínimo (5 velas) para obtener precio sin gastar budget
        if not self.is_configured or not self._within_limit():
            return None

        twelve_sym = OTC_TO_TWELVE.get(otc_symbol)
        if not twelve_sym:
            return None

        try:
            candles = await self._fetch_candles(twelve_sym, count=5)
            if candles:
                price = candles[-1].close
                # Actualiza solo el precio en cache existente (sin cambiar TTL)
                # No crea entrada nueva de cache - evita requests extra del MAE
                existing = self._cache.get(otc_symbol)
                if existing:
                    existing["indicators"].price = price
                    # Extiende el TTL existente otros 60s para evitar re-fetch inmediato
                    existing["expires"] = max(existing["expires"], time.time() + 60)
                self._req_today += 1
                return price
        except Exception as e:
            logger.debug("MAE price sample error %s: %s", otc_symbol, e)

        return None

    # ── Historial para backtesting ─────────────────────────────────────────────
    async def fetch_historical_candles(
        self,
        otc_symbol: str,
        interval: str = "1min",
        count: int = 300,
    ) -> List[CandleData]:
        """
        Descarga velas históricas para backtesting.
        Máximo recomendado: 300 velas (1 req del límite diario).
        No usa caché — siempre datos frescos del historial.
        """
        if not self.is_configured:
            raise ValueError("API key no configurada — backtesting requiere datos reales")

        if not self._within_limit():
            raise ValueError(f"Límite diario alcanzado ({self._req_today} req). Inténtalo mañana.")

        twelve_sym = OTC_TO_TWELVE.get(otc_symbol)
        if not twelve_sym:
            raise ValueError(f"Símbolo {otc_symbol} no soportado por Twelve Data")

        candles = await self._fetch_candles(twelve_sym, interval=interval, count=count)
        self._req_today += 1
        logger.info("📜 Historial backtesting | %s | %d velas | req #%d/%d",
                    otc_symbol, len(candles), self._req_today, self.DAILY_LIMIT)
        return candles

    # ── Estadísticas ──────────────────────────────────────────────────────────
    def stats(self) -> dict:
        return {
            "api_configured":  self.is_configured,
            "requests_today":  self._req_today,
            "requests_limit":  self.DAILY_LIMIT,
            "symbols_cached":  len(self._cache),
            "cache_ttl_sec":   self.cache_ttl,
        }


# ─────────────────────────────────────────────────────────────────────────────
# GENERADOR DE DATOS SIMULADOS (fallback sin API)
# ─────────────────────────────────────────────────────────────────────────────

# Precios base por símbolo (se actualizan con momentum)
_sim_state: Dict[str, dict] = {}
_BASE_PRICES = {
    "OTC_EURUSD": 1.0823, "OTC_GBPUSD": 1.2654, "OTC_USDJPY": 150.12,
    "OTC_USDCHF": 0.8823, "OTC_AUDUSD": 0.6523, "OTC_USDCAD": 1.3512,
    "OTC_NZDUSD": 0.5912, "OTC_EURJPY": 162.45, "OTC_EURGBP": 0.8556,
    "OTC_EURAUD": 1.6589, "OTC_EURCAD": 1.4623, "OTC_EURCHF": 0.9545,
    "OTC_GBPJPY": 189.90, "OTC_GBPAUD": 1.9398, "OTC_GBPCAD": 1.7098,
    "OTC_GBPCHF": 1.1162, "OTC_AUDJPY": 97.90,  "OTC_AUDCAD": 0.8812,
    "OTC_CADJPY": 111.09, "OTC_CHFJPY": 170.16,
}


def simulate_candles(otc_symbol: str, count: int = 50) -> List[CandleData]:
    """Genera velas simuladas con momentum persistente (mean-reverting)."""
    base = _BASE_PRICES.get(otc_symbol, 1.0)
    st   = _sim_state.setdefault(otc_symbol, {"price": base, "momentum": 0.0})

    candles = []
    price   = st["price"]
    mom     = st["momentum"]

    for _ in range(count):
        drift = (base - price) * 0.002
        noise = random.gauss(0, base * 0.0002)
        mom   = mom * 0.85 + drift + noise
        price = max(price + mom, base * 0.5)  # evita precios negativos

        spread = base * 0.0002
        high   = price + random.uniform(0, spread)
        low    = price - random.uniform(0, spread)
        open_  = price + random.uniform(-spread / 2, spread / 2)
        candles.append(CandleData(
            time   = "",
            open   = round(open_, 5),
            high   = round(high, 5),
            low    = round(low, 5),
            close  = round(price, 5),
            volume = random.randint(100, 2000),
        ))

    st["price"]    = price
    st["momentum"] = mom
    return candles


def get_simulated_indicators(otc_symbol: str) -> IndicatorSet:
    """Indicadores calculados sobre velas simuladas con momentum."""
    candles = simulate_candles(otc_symbol, count=50)
    ind = IndicatorSet()
    ind.compute(candles)
    ind.is_real = False  # marca como simulado
    return ind


# ─────────────────────────────────────────────────────────────────────────────
# SINGLETON GLOBAL
# ─────────────────────────────────────────────────────────────────────────────
_provider: Optional[TwelveDataProvider] = None


def init_provider() -> TwelveDataProvider:
    global _provider
    _provider = TwelveDataProvider(
        api_key   = os.getenv("TWELVE_DATA_API_KEY", ""),
        cache_ttl = int(os.getenv("TWELVE_DATA_CACHE_TTL", "300")),
    )
    return _provider


def get_provider() -> Optional[TwelveDataProvider]:
    return _provider


async def get_indicators_for(otc_symbol: str) -> IndicatorSet:
    """
    Función principal: retorna indicadores reales si API está configurada,
    o simulados si no lo está. NUNCA lanza excepción.
    """
    if _provider and _provider.is_configured:
        real = await _provider.get_indicators(otc_symbol)
        if real:
            return real
    return get_simulated_indicators(otc_symbol)

