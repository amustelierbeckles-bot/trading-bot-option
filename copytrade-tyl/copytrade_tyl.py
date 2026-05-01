"""
copytrade_tyl.py — versión HTTP para deploy en container.

Se comunica con el bot principal vía HTTP interno (red Docker `trading-network`):
  - POST /api/internal/copytrade/place_trade
  - GET  /api/internal/copytrade/indicators
  - POST /api/internal/copytrade/notify

Vars de entorno:
  COPYTRADE_TYL_ENABLED, ACCOUNT_MODE,
  TELEGRAM_API_ID, TELEGRAM_API_HASH, TYL_CHANNEL_ID,
  BOT_API_URL, COPYTRADE_INTERNAL_TOKEN,
  COPYTRADE_CB_ENABLED, COPYTRADE_CB_COOLDOWN_MINUTES.
"""
from __future__ import annotations

import asyncio
import time
import json
import logging
import os
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

import httpx
from telethon import TelegramClient, events


# ============================================================
# Config
# ============================================================
COPYTRADE_TYL_ENABLED = os.getenv("COPYTRADE_TYL_ENABLED", "false").lower() == "true"
ACCOUNT_MODE = os.getenv("ACCOUNT_MODE", "demo").lower()

def _envint(name: str, default: int = 0) -> int:
    v = os.getenv(name, "").strip()
    if not v:
        return default
    try:
        return int(v)
    except ValueError:
        return default


TELEGRAM_API_ID = _envint("TELEGRAM_API_ID", 0)
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "").strip()
TYL_CHANNEL_ID_RAW = os.getenv("TYL_CHANNEL_ID", "").strip()
try:
    TYL_CHANNEL_ID: int | str = int(TYL_CHANNEL_ID_RAW) if TYL_CHANNEL_ID_RAW else 0
except ValueError:
    TYL_CHANNEL_ID = TYL_CHANNEL_ID_RAW  # username

BOT_API_URL = os.getenv("BOT_API_URL", "http://trading-bot-api:8000").rstrip("/")
INTERNAL_TOKEN = os.getenv("COPYTRADE_INTERNAL_TOKEN", "")

COPYTRADE_CB_ENABLED = os.getenv("COPYTRADE_CB_ENABLED", "false").lower() == "true"
COPYTRADE_CB_COOLDOWN_MINUTES = _envint("COPYTRADE_CB_COOLDOWN_MINUTES", 30)

TREND_EMA_PERIOD = 9
TREND_CCI_PERIOD = 20
TREND_CCI_THRESHOLD = 100
TREND_LOOKBACK = 5
TREND_CONSECUTIVE_REQUIRED = 5

AMOUNT_NORMAL = {1: 25, 2: 50, 3: 100}
AMOUNT_POST_DEFEAT = {1: 50, 2: 50, 3: 100}

PAYOUT_ESTIMATE = 0.92
SESSION_TZ = timezone(timedelta(hours=1))
DATA_DIR = Path(os.getenv("COPYTRADE_DATA_DIR", "/app/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
STATS_FILE = DATA_DIR / "copytrade_tyl_stats.json"
SESSION_FILE_DIR = DATA_DIR / "telethon"
SESSION_FILE_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("copytrade_tyl")


# ============================================================
# Modelos
# ============================================================
class Direction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class TradeResult(str, Enum):
    WIN = "WIN"
    WIN_GALE = "WIN_GALE"
    LOSS = "LOSS"
    SKIPPED = "SKIPPED"
    DISCARDED = "DISCARDED"


@dataclass
class Signal:
    pair: str
    direction: Direction
    entry_time: datetime
    martingale_1: datetime
    martingale_2: datetime
    expiration_minutes: int = 5
    received_at: datetime = field(default_factory=lambda: datetime.now(SESSION_TZ))

    def signal_id(self) -> str:
        return f"{self.pair}_{self.entry_time.isoformat()}"

    def time_for_window(self, w: int) -> datetime:
        return {1: self.entry_time, 2: self.martingale_1, 3: self.martingale_2}[w]


@dataclass
class TradeRecord:
    signal_id: str
    pair: str
    direction: str
    window: int
    amount: float
    entry_time: str
    expiration_minutes: int
    is_demo: bool
    is_post_defeat: bool
    trend_check: dict
    result: Optional[str] = None
    profit: Optional[float] = None
    closed_at: Optional[str] = None
    order_id: Optional[str] = None


# ============================================================
# Estado
# ============================================================
class SessionState:
    def __init__(self) -> None:
        self.post_defeat: bool = False
        self.consecutive_losses: int = 0
        self.cb_active_until: Optional[datetime] = None
        self.session_start: Optional[datetime] = None
        self.active_signal: Optional[Signal] = None
        self.active_records: list[TradeRecord] = []
        self.window_tasks: list[asyncio.Task] = []
        self.v1_error: bool = False

    def reset_session(self) -> None:
        self.post_defeat = False
        self.consecutive_losses = 0
        self.cb_active_until = None
        self.session_start = datetime.now(SESSION_TZ)
        self._cancel_pending_windows()
        self.v1_error = False
        self.active_signal = None
        self.active_records = []
        logger.info("session reset")
        asyncio.create_task(notify("🟢 COPYTRADE — Sesión nueva. Estado reseteado."))

    def in_cooldown(self) -> bool:
        if not COPYTRADE_CB_ENABLED or self.cb_active_until is None:
            return False
        return datetime.now(SESSION_TZ) < self.cb_active_until

    def _cancel_pending_windows(self) -> None:
        for t in self.window_tasks:
            if not t.done():
                t.cancel()
        self.window_tasks = []


state = SessionState()


# ============================================================
# Mapeo de formato TYL → bot principal
# ============================================================
def to_otc_symbol(pair: str) -> str:
    """AUD/CHF → OTC_AUDCHF, EUR/USD → OTC_EURUSD."""
    return "OTC_" + pair.replace("/", "").upper()


def to_po_direction(direction: Direction) -> str:
    """BUY → call, SELL → put."""
    return "call" if direction == Direction.BUY else "put"


# ============================================================
# Cliente HTTP al bot principal
# ============================================================
_http: Optional[httpx.AsyncClient] = None


def get_http() -> httpx.AsyncClient:
    global _http
    if _http is None:
        _http = httpx.AsyncClient(
            base_url=BOT_API_URL,
            headers={"X-Internal-Token": INTERNAL_TOKEN},
            timeout=15.0,
        )
    return _http


async def api_place_trade(symbol: str, direction: str, amount: float, expiry_seconds: int, is_demo: bool) -> dict:
    r = await get_http().post(
        "/api/internal/copytrade/place_trade",
        json={
            "symbol": symbol,
            "direction": direction,
            "amount": amount,
            "expiry_seconds": expiry_seconds,
            "is_demo": is_demo,
        },
    )
    r.raise_for_status()
    return r.json()


async def api_indicators(otc_symbol: str) -> dict:
    r = await get_http().get(
        "/api/internal/copytrade/indicators",
        params={
            "pair": otc_symbol,
            "timeframe": "M1",
            "lookback": TREND_LOOKBACK,
            "ema_period": TREND_EMA_PERIOD,
            "cci_period": TREND_CCI_PERIOD,
        },
    )
    r.raise_for_status()
    return r.json()


async def notify(message: str) -> None:
    try:
        r = await get_http().post("/api/internal/copytrade/notify", json={"message": message})
        r.raise_for_status()
    except Exception as e:
        logger.warning("notify failed: %s", e)


# ============================================================
# Parsers
# ============================================================
SIGNAL_PATTERN = re.compile(
    r"([A-Z]{3}/[A-Z]{3})\s*OTC\s*"
    r".*?Expiration\s*(\d+)\s*minutes?\s*"
    r".*?Entry\s*at\s*(\d{1,2}:\d{2})\s*"
    r".*?(BUY|SELL)\s*"
    r".*?MARTINGALE\s*AT\s*(\d{1,2}:\d{2})\s*"
    r".*?MARTINGALE\s*AT\s*(\d{1,2}:\d{2})",
    re.IGNORECASE | re.DOTALL,
)
SESSION_START_PATTERNS = (
    re.compile(r"let'?s\s+start\s+the\s+operations", re.IGNORECASE),
    re.compile(r"session\s+starts", re.IGNORECASE),
)
RESULT_LOSS = re.compile(r"❌\s*LOSS|\bX\s*LOSS\b", re.IGNORECASE)
RESULT_WIN_GALE = re.compile(r"VICTORY\s+AT\s+GALE", re.IGNORECASE)
RESULT_WIN = re.compile(r"\bGAIN\b", re.IGNORECASE)


def parse_signal(text: str) -> Optional[Signal]:
    if not text:
        return None
    m = SIGNAL_PATTERN.search(text)
    if not m:
        return None
    pair, exp, entry, direction, gale1, gale2 = m.groups()
    today = datetime.now(SESSION_TZ).date()

    def to_dt(hhmm: str) -> datetime:
        h, mn = (int(x) for x in hhmm.split(":"))
        return datetime(today.year, today.month, today.day, h, mn, tzinfo=SESSION_TZ)

    return Signal(
        pair=pair.upper(),
        direction=Direction(direction.upper()),
        entry_time=to_dt(entry),
        martingale_1=to_dt(gale1),
        martingale_2=to_dt(gale2),
        expiration_minutes=int(exp),
    )


def is_session_start(text: str) -> bool:
    return bool(text) and any(p.search(text) for p in SESSION_START_PATTERNS)


def parse_result(text: str) -> Optional[TradeResult]:
    if not text:
        return None
    if RESULT_LOSS.search(text):
        return TradeResult.LOSS
    if RESULT_WIN_GALE.search(text):
        return TradeResult.WIN_GALE
    if RESULT_WIN.search(text):
        return TradeResult.WIN
    return None


PLACE_BUDGET_S: float = 6.0
PLACE_BACKOFF: tuple = (0.4, 0.8, 1.5)
RECOVERABLE_KEYWORDS: tuple = (
    "timeout", "ws_disconnected", "no_session",
    "ratelimit", "reconnecting", "temporarily",
)


def _is_recoverable(reason: str) -> bool:
    r = (reason or "").lower()
    return any(k in r for k in RECOVERABLE_KEYWORDS)


# ============================================================
# Trend filter (vía HTTP)
# ============================================================
async def is_trend_against(pair: str, direction: Direction) -> tuple[bool, dict]:
    otc = to_otc_symbol(pair)
    try:
        data = await api_indicators(otc)
    except Exception as e:
        logger.warning("indicators fetch failed for %s: %s", otc, e)
        return False, {"error": str(e)}

    if not data.get("ready"):
        return False, {"error": "not_ready", "detail": data.get("reason"), "count": data.get("count")}

    candles = data["candles"]
    ema = data["ema_series"]
    cci = data["cci_series"]
    if len(candles) < TREND_LOOKBACK or len(ema) < TREND_LOOKBACK or len(cci) < TREND_LOOKBACK:
        return False, {"error": "insufficient_series"}

    breakdown = []
    for c, e, x in zip(candles[-TREND_LOOKBACK:], ema[-TREND_LOOKBACK:], cci[-TREND_LOOKBACK:]):
        close = c["close"]
        if direction == Direction.BUY:
            against = (close < e) and (x < -TREND_CCI_THRESHOLD)
        else:
            against = (close > e) and (x > TREND_CCI_THRESHOLD)
        breakdown.append({"close": close, "ema": e, "cci": x, "against": against})

    last_consec = breakdown[-TREND_CONSECUTIVE_REQUIRED:]
    consecutive = all(b["against"] for b in last_consec)
    return consecutive, {
        "breakdown": breakdown,
        "consecutive_required": TREND_CONSECUTIVE_REQUIRED,
        "consecutive_against": consecutive,
    }


async def analyze_trend(pair: str, direction) -> dict:
    _, debug = await is_trend_against(pair, direction)
    return debug


# ============================================================
# Stats
# ============================================================
def append_stat(record: TradeRecord) -> None:
    data: list = []
    if STATS_FILE.exists():
        try:
            data = json.loads(STATS_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("stats file corrupt, starting new")
            data = []
    data.append(asdict(record))
    STATS_FILE.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


async def place_with_retry(
    otc: str, po_dir: str, amount: float,
    expiry_s: int, is_demo: bool, deadline_ts: float,
) -> tuple:
    import json as _j
    last_err = None
    for i, backoff in enumerate((0.0,) + PLACE_BACKOFF):
        if backoff:
            await asyncio.sleep(backoff)
        if time.time() >= deadline_ts:
            return None, f"deadline_exceeded attempt={i} last={last_err}"
        try:
            result = await api_place_trade(
                symbol=otc, direction=po_dir, amount=amount,
                expiry_seconds=expiry_s, is_demo=is_demo,
            )
        except (httpx.TimeoutException, httpx.TransportError) as e:
            last_err = f"network:{type(e).__name__}:{e}"
            continue
        except httpx.HTTPStatusError as e:
            return None, f"http_{e.response.status_code}:{e.response.text[:200]}"
        if result.get("status") == "placed":
            return result, None
        reason = result.get("reason") or result.get("error_code")
        if not reason:
            logger.warning("place_no_reason raw=%s", _j.dumps(result)[:500])
            reason = f"no_reason_raw={str(result)[:120]}"
        if _is_recoverable(reason):
            last_err = reason
            continue
        return None, reason
    return None, last_err or "retry_budget_exhausted"


# ============================================================
# Ejecutor
# ============================================================
async def execute_window(signal: Signal, window: int) -> None:
    target = signal.time_for_window(window)
    deadline_ts = target.timestamp() + PLACE_BUDGET_S
    delay = (target - datetime.now(SESSION_TZ)).total_seconds()
    if delay > 0:
        await asyncio.sleep(delay)

    if state.in_cooldown():
        logger.info("window %s skipped: cooldown", window)
        return

    if window > 1 and state.v1_error:
        logger.info("window %s cancelled: v1_error", window)
        await notify(
            f"🟡 COPYTRADE — V{window} {signal.pair} cancelada (V1 falló con error)"
        )
        return

    amount_table = AMOUNT_POST_DEFEAT if state.post_defeat else AMOUNT_NORMAL
    amount = amount_table[window]
    is_demo = ACCOUNT_MODE == "demo"

    trend = await analyze_trend(signal.pair, signal.direction)
    logger.info(
        "trend_telemetry pair=%s window=%s direction=%s against=%s",
        signal.pair, window, signal.direction.value,
        trend.get("consecutive_against", "?"),
    )

    record = TradeRecord(
        signal_id=signal.signal_id(),
        pair=signal.pair,
        direction=signal.direction.value,
        window=window,
        amount=amount,
        entry_time=target.isoformat(),
        expiration_minutes=signal.expiration_minutes,
        is_demo=is_demo,
        is_post_defeat=state.post_defeat,
        trend_check=trend,
    )

    otc = to_otc_symbol(signal.pair)
    po_dir = to_po_direction(signal.direction)
    result, err = await place_with_retry(
        otc, po_dir, amount, signal.expiration_minutes * 60, is_demo, deadline_ts,
    )
    if result is None:
        record.result = "ERROR"
        state.active_records.append(record)
        append_stat(record)
        await notify(f"⚠️ COPYTRADE — Error en V{window} {signal.pair}: {err}")
        if window == 1:
            state.v1_error = True
        return

    record.order_id = result.get("order_id")
    state.active_records.append(record)
    label = "Original" if window == 1 else f"Martingala {window - 1}"
    close_t = target + timedelta(minutes=signal.expiration_minutes)
    _msg_parts = [
        f"🤖 COPYTRADING — {signal.pair} OTC",
        f"Señal: {signal.direction.value} | TYL Trading",
        f"Ventana: {window} ({label})",
        f"Monto: ${amount}",
        f"Entrada: {target.strftime('%H:%M')} UTC+1",
        f"Cierre: {close_t.strftime('%H:%M')} UTC+1",
    ]
    await notify("\n".join(_msg_parts))


async def process_signal(signal: Signal) -> None:
    if state.in_cooldown():
        logger.info("signal ignored: cooldown")
        return

    state._cancel_pending_windows()
    state.active_signal = signal
    state.active_records = []
    state.window_tasks = [asyncio.create_task(execute_window(signal, w)) for w in (1, 2, 3)]
    try:
        await asyncio.gather(*state.window_tasks, return_exceptions=True)
    except asyncio.CancelledError:
        pass

    if state.active_records and all(
        r.result == TradeResult.SKIPPED.value for r in state.active_records
    ):
        for r in state.active_records:
            r.result = TradeResult.DISCARDED.value
        await notify(
            f"🔴 COPYTRADE — Señal DESCARTADA: 3 ventanas con tendencia en contra\n"
            f"{signal.pair} {signal.direction.value}"
        )


async def handle_result(result: TradeResult) -> None:
    if state.active_signal is None:
        return
    placed = [r for r in state.active_records if r.result is None]
    last = placed[-1] if placed else None

    if result in (TradeResult.WIN, TradeResult.WIN_GALE):
        state._cancel_pending_windows()
        state.consecutive_losses = 0
        if last is not None:
            last.result = result.value
            last.profit = round(last.amount * PAYOUT_ESTIMATE, 2)
            last.closed_at = datetime.now(SESSION_TZ).isoformat()
            append_stat(last)
            await notify(
                f"📊 COPYTRADE — {result.value}\n"
                f"{last.pair} {last.direction} V{last.window} ${last.amount} → +${last.profit}"
            )
    else:
        state.post_defeat = True
        state.consecutive_losses += 1
        if last is not None:
            last.result = TradeResult.LOSS.value
            last.profit = -last.amount
            last.closed_at = datetime.now(SESSION_TZ).isoformat()
            append_stat(last)
            await notify(
                f"📊 COPYTRADE — LOSS\n"
                f"{last.pair} {last.direction} V{last.window} ${last.amount} → -${last.amount}\n"
                f"Racha pérdidas: {state.consecutive_losses}"
            )
        if COPYTRADE_CB_ENABLED and state.consecutive_losses >= 3:
            state.cb_active_until = datetime.now(SESSION_TZ) + timedelta(
                minutes=COPYTRADE_CB_COOLDOWN_MINUTES
            )
            await notify(f"🚨 COPYTRADE CB activado — pausa {COPYTRADE_CB_COOLDOWN_MINUTES} min")

    state.active_signal = None
    state.active_records = []


# ============================================================
# Listener Telegram (cliente lazy: se crea sólo cuando hay creds)
# ============================================================
client: Optional[TelegramClient] = None


async def on_telegram_message(event):
    if not COPYTRADE_TYL_ENABLED:
        return
    text = event.message.message or ""
    logger.info("tg_msg recv [%d chars]: %r", len(text), text[:120])

    if is_session_start(text):
        state.reset_session()
        return

    result = parse_result(text)
    if result is not None:
        await handle_result(result)
        return

    sig = parse_signal(text)
    if sig is not None:
        asyncio.create_task(process_signal(sig))
    elif text.strip():
        logger.info("tg_msg no_match: %r", text[:120])


def build_client() -> TelegramClient:
    global client
    client = TelegramClient(
        str(SESSION_FILE_DIR / "copytrade_tyl_session"),
        TELEGRAM_API_ID,
        TELEGRAM_API_HASH,
    )
    client.add_event_handler(on_telegram_message, events.NewMessage(chats=TYL_CHANNEL_ID))
    return client


# ============================================================
# Main
# ============================================================
async def _idle_forever(reason: str) -> None:
    logger.warning("idle: %s", reason)
    while True:
        await asyncio.sleep(3600)


async def start() -> None:
    if not COPYTRADE_TYL_ENABLED:
        await _idle_forever("disabled (set COPYTRADE_TYL_ENABLED=true)")
        return
    if ACCOUNT_MODE != "demo":
        await _idle_forever("ACCOUNT_MODE != demo (15-day demo lock)")
        return
    if not all([TELEGRAM_API_ID, TELEGRAM_API_HASH, TYL_CHANNEL_ID, INTERNAL_TOKEN]):
        await _idle_forever("missing env vars: TELEGRAM_API_ID/HASH, TYL_CHANNEL_ID, COPYTRADE_INTERNAL_TOKEN")
        return

    # Health check al bot principal
    try:
        r = await get_http().get("/api/internal/copytrade/health")
        r.raise_for_status()
        logger.info("bot main API healthy: %s", r.json())
    except Exception as e:
        logger.error("cannot reach bot main API at %s: %s", BOT_API_URL, e)
        return

    tg = build_client()
    await tg.start()
    logger.info("telethon listener started on channel %s", TYL_CHANNEL_ID)
    await notify("🟢 COPYTRADE — Listener arrancado, esperando señales TYL")
    await tg.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(start())
