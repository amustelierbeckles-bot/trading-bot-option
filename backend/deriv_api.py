"""
Deriv WebSocket API — Ejecutor de trades.

Misma interfaz pública que po_websocket.py:
  place_trade(symbol, direction, amount, expiry_seconds, is_demo) → dict
  get_latest_price(symbol, max_age_seconds) → Optional[float]
  get_cached_price(symbol) → Optional[float]
  is_connected: bool

Documentación oficial: https://api.deriv.com/
App ID: 36544 (público Deriv) o crear propio en developers.deriv.com
Token: app.deriv.com → Settings → Security → API Token (scopes: Read + Trade)
"""
import asyncio
import json
import logging
import os
import time
from typing import Dict, Optional

import websockets

logger = logging.getLogger(__name__)

WS_URL = "wss://ws.derivws.com/websockets/v3?app_id={app_id}"

# Mapeo símbolos internos → símbolos Deriv
SYMBOL_MAP: Dict[str, str] = {
    "OTC_EURUSD":  "frxEURUSD",
    "OTC_GBPUSD":  "frxGBPUSD",
    "OTC_USDJPY":  "frxUSDJPY",
    "OTC_USDCHF":  "frxUSDCHF",
    "OTC_AUDUSD":  "frxAUDUSD",
    "OTC_NZDUSD":  "frxNZDUSD",
    "OTC_EURGBP":  "frxEURGBP",
    "OTC_EURJPY":  "frxEURJPY",
    "OTC_GBPJPY":  "frxGBPJPY",
    "OTC_AUDJPY":  "frxAUDJPY",
    "OTC_CADJPY":  "frxCADJPY",
    "OTC_CHFJPY":  "frxCHFJPY",
    "OTC_EURCHF":  "frxEURCHF",
    "OTC_GBPCHF":  "frxGBPCHF",
    "OTC_GBPAUD":  "frxGBPAUD",
    "OTC_EURAUD":  "frxEURAUD",
    "OTC_EURCAD":  "frxEURCAD",
    "OTC_USDCAD":  "frxUSDCAD",
}

# Cache de precios en tiempo real (tick subscriptions)
_price_cache: Dict[str, Dict] = {}  # internal_symbol → {"price": float, "ts": float}


class DerivAPIProvider:
    """Conexión permanente a Deriv WebSocket API con streaming de precios."""

    def __init__(self):
        self._token:        str   = ""
        self._app_id:       int   = 36544
        self._is_demo:      bool  = True
        self._is_virtual:   bool  = True   # se actualiza tras auth con Deriv
        self.is_configured: bool  = False
        self.is_connected:  bool  = False
        self._ws                  = None
        self._task                = None
        self._req_id:       int   = 0
        self._pending:      Dict[int, asyncio.Future] = {}
        self._account_id:   Optional[str] = None
        self._balance:      float = 0.0
        self._lock:         asyncio.Lock = asyncio.Lock()

    # ── Configuración ─────────────────────────────────────────────────────────

    def configure(self, token: str, is_demo: bool = True, app_id: int = 36544):
        self._token        = token
        self._is_demo      = is_demo
        self._app_id       = app_id
        self.is_configured = bool(token)
        logger.info("🔌 DerivAPI configurado | modo=%s | app_id=%d",
                    "DEMO" if is_demo else "REAL", app_id)

    # ── Ciclo de vida ──────────────────────────────────────────────────────────

    async def start(self):
        if not self.is_configured:
            logger.warning("⚠️  DerivAPI no configurado — falta DERIV_API_TOKEN")
            return
        self._task = asyncio.create_task(self._run())

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self.is_connected = False
        self._ws          = None

    # ── Helpers internos ──────────────────────────────────────────────────────

    def _next_req_id(self) -> int:
        self._req_id += 1
        return self._req_id

    async def _send_and_wait(self, payload: dict, req_id: int,
                              timeout: float = 15.0) -> dict:
        """Envía payload y espera respuesta con req_id correspondiente."""
        if not self._ws:
            return {"error": {"message": "WebSocket no conectado"}}
        loop = asyncio.get_event_loop()
        fut  = loop.create_future()
        self._pending[req_id] = fut
        try:
            await self._ws.send(json.dumps(payload))
            return await asyncio.wait_for(asyncio.shield(fut), timeout=timeout)
        except asyncio.TimeoutError:
            return {"error": {"message": f"timeout req_id={req_id}"}}
        finally:
            self._pending.pop(req_id, None)

    # ── Loop principal ─────────────────────────────────────────────────────────

    async def _run(self):
        RECONNECT_DELAY = 15
        while True:
            try:
                url = WS_URL.format(app_id=self._app_id)
                async with websockets.connect(
                    url,
                    ping_interval=30,
                    ping_timeout=20,
                    close_timeout=10,
                ) as ws:
                    self._ws = ws

                    # ── Autorización ──────────────────────────────────────────
                    await ws.send(json.dumps({"authorize": self._token, "req_id": 1}))
                    raw_auth = await asyncio.wait_for(ws.recv(), timeout=15.0)
                    auth_resp = json.loads(raw_auth)

                    if "error" in auth_resp:
                        logger.error("❌ DerivAPI auth error: %s",
                                     auth_resp["error"]["message"])
                        await asyncio.sleep(RECONNECT_DELAY)
                        continue

                    acct          = auth_resp.get("authorize", {})
                    self._account_id = acct.get("loginid", "?")
                    self._balance    = acct.get("balance", 0.0)
                    is_virtual        = bool(acct.get("is_virtual", False))
                    self._is_virtual  = is_virtual
                    self.is_connected = True

                    if self._is_demo and not is_virtual:
                        logger.warning(
                            "⚠️  ACCOUNT_MODE=demo pero el token es de cuenta REAL (%s). "
                            "Usa el token de cuenta virtual para operar en demo.",
                            self._account_id,
                        )
                    elif not self._is_demo and is_virtual:
                        logger.warning(
                            "⚠️  ACCOUNT_MODE=real pero el token es de cuenta VIRTUAL (%s).",
                            self._account_id,
                        )

                    logger.info(
                        "✅ DerivAPI autorizado | cuenta=%s | balance=%.2f | %s",
                        self._account_id, self._balance,
                        "VIRTUAL" if is_virtual else "REAL",
                    )

                    # ── Suscripción de ticks de precio ────────────────────────
                    for i, (_, deriv_sym) in enumerate(SYMBOL_MAP.items()):
                        await ws.send(json.dumps({
                            "ticks":     deriv_sym,
                            "subscribe": 1,
                            "req_id":    100 + i,
                        }))
                        await asyncio.sleep(0.05)
                    logger.info("📡 DerivAPI suscrito a %d pares", len(SYMBOL_MAP))

                    # ── Loop de mensajes ──────────────────────────────────────
                    async for raw in ws:
                        try:
                            msg = json.loads(raw)
                            self._handle_message(msg)
                        except Exception as e:
                            logger.debug("Error procesando mensaje Deriv: %s", e)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(
                    "⚠️  DerivAPI desconectado: %s — reconectando en %ds",
                    type(e).__name__, RECONNECT_DELAY,
                )
            finally:
                self.is_connected = False
                self._ws          = None
                # Resolver futures pendientes con error de conexión
                for fut in list(self._pending.values()):
                    if not fut.done():
                        fut.set_result({"error": {"message": "conexión perdida"}})
                self._pending.clear()

            await asyncio.sleep(RECONNECT_DELAY)

    def _handle_message(self, msg: dict):
        """Enruta mensajes: resuelve futures pendientes o actualiza cache de precios."""
        req_id = msg.get("req_id")

        # Resolver future pendiente (respuestas a send_and_wait)
        if req_id and req_id in self._pending:
            fut = self._pending[req_id]
            if not fut.done():
                fut.set_result(msg)
            return

        msg_type = msg.get("msg_type")

        # Tick de precio en tiempo real
        if msg_type == "tick":
            tick      = msg.get("tick", {})
            deriv_sym = tick.get("symbol", "")
            price     = tick.get("quote", 0.0)
            if deriv_sym and price:
                for internal, dsym in SYMBOL_MAP.items():
                    if dsym == deriv_sym:
                        _price_cache[internal] = {"price": price, "ts": time.time()}
                        break

    # ── API pública ────────────────────────────────────────────────────────────

    def get_latest_price(self, internal_symbol: str,
                         max_age_seconds: int = 60) -> Optional[float]:
        cached = _price_cache.get(internal_symbol)
        if not cached:
            return None
        if time.time() - cached["ts"] > max_age_seconds:
            return None
        return cached["price"]

    def get_cached_price(self, internal_symbol: str) -> Optional[float]:
        cached = _price_cache.get(internal_symbol)
        return cached["price"] if cached else None

    async def place_trade(self, symbol: str, direction: str, amount: float,
                          expiry_seconds: int = 120,
                          is_demo: bool = True) -> dict:
        """
        Coloca un trade binario en Deriv.

        Retorna:
          {"status": "success", "order_id": int, "buy_price": float, ...}
          {"status": "error",   "reason": str}
        """
        if not self.is_connected:
            return {"status": "error", "reason": "DerivAPI no conectado"}

        # Guard: ACCOUNT_MODE=demo requiere cuenta virtual obligatoriamente.
        # Si hay mismatch (token real + modo demo) → bloqueo duro, sin excepción.
        if self._is_demo and not self._is_virtual:
            logger.error(
                "🚫 Trade BLOQUEADO — ACCOUNT_MODE=demo pero el token es de cuenta REAL (%s). "
                "Configura DERIV_API_TOKEN con el token de tu cuenta virtual.",
                self._account_id,
            )
            return {
                "status": "error",
                "reason": (
                    "BLOQUEADO: ACCOUNT_MODE=demo pero el token es de cuenta REAL. "
                    "Usa el token de tu cuenta virtual de Deriv."
                ),
            }

        deriv_sym = SYMBOL_MAP.get(symbol)
        if not deriv_sym:
            return {"status": "error", "reason": f"Símbolo {symbol} sin mapeo Deriv"}

        contract_type = "CALL" if direction.upper() in ("CALL",) else "PUT"
        duration      = max(1, expiry_seconds // 60)  # mínimo 1 minuto

        async with self._lock:
            # Paso 1: Propuesta — verifica disponibilidad y obtiene precio
            prop_id = self._next_req_id()
            prop_resp = await self._send_and_wait({
                "proposal":      1,
                "amount":        amount,
                "basis":         "stake",
                "contract_type": contract_type,
                "currency":      "USD",
                "duration":      duration,
                "duration_unit": "m",
                "symbol":        deriv_sym,
                "req_id":        prop_id,
            }, prop_id)

            if "error" in prop_resp:
                reason = prop_resp["error"].get("message", "error desconocido")
                logger.warning("⚠️  Deriv proposal error | %s %s: %s",
                               contract_type, deriv_sym, reason)
                return {"status": "error", "reason": reason}

            proposal_id = prop_resp.get("proposal", {}).get("id")
            if not proposal_id:
                return {"status": "error", "reason": "Sin proposal_id en respuesta Deriv"}

            # Paso 2: Comprar contrato
            buy_id = self._next_req_id()
            buy_resp = await self._send_and_wait({
                "buy":    proposal_id,
                "price":  amount,
                "req_id": buy_id,
            }, buy_id)

        if "error" in buy_resp:
            reason = buy_resp["error"].get("message", "error desconocido")
            logger.warning("⚠️  Deriv buy error | %s %s: %s",
                           contract_type, deriv_sym, reason)
            return {"status": "error", "reason": reason}

        buy_data    = buy_resp.get("buy", {})
        contract_id = buy_data.get("contract_id")
        buy_price   = buy_data.get("buy_price", amount)
        start_time  = buy_data.get("start_time")

        logger.info("✅ Trade Deriv | %s %s $%.2f | contract_id=%s | buy_price=%.4f",
                    contract_type, deriv_sym, amount, contract_id, buy_price)

        return {
            "status":      "success",
            "order_id":    contract_id,
            "buy_price":   buy_price,
            "symbol":      deriv_sym,
            "direction":   contract_type,
            "start_time":  start_time,
        }

    @property
    def account_info(self) -> dict:
        return {
            "account_id": self._account_id,
            "balance":    self._balance,
            "is_demo":    self._is_demo,
        }


# ── Singleton ──────────────────────────────────────────────────────────────────

_deriv_provider: Optional[DerivAPIProvider] = None


def init_deriv_provider(token: str, is_demo: bool = True,
                         app_id: int = 36544) -> DerivAPIProvider:
    global _deriv_provider
    if _deriv_provider is None:
        _deriv_provider = DerivAPIProvider()
    _deriv_provider.configure(token, is_demo, app_id)
    return _deriv_provider


def get_deriv_provider() -> Optional[DerivAPIProvider]:
    return _deriv_provider
