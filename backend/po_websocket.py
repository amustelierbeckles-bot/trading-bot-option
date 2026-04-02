"""
PocketOption WebSocket Provider v1.0
=====================================
Conexión directa a wss://events-po.com/socket.io/ con:
  - Camuflaje TLS (headers idénticos a Chrome 145)
  - Jitter humano en suscripciones
  - Heartbeat con variación aleatoria
  - Kill-Switch automático con fallback a Twelve Data
  - Renovación automática de sesión

Protocolo: Socket.IO v4 sobre WebSocket
"""

import asyncio
import json
import logging
import os
import random
import time
import urllib.parse
from collections import defaultdict, deque
from datetime import datetime
from typing import Callable, Dict, List, Optional

import websockets
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger(__name__)

# ── Mapeo OTC symbol → símbolo interno de PO ─────────────────────────────────
# Extraído del protocolo observado en Network tab
OTC_SYMBOL_MAP = {
    "OTC_EURUSD":  "EURUSD_otc",
    "OTC_GBPUSD":  "GBPUSD_otc",
    "OTC_USDJPY":  "USDJPY_otc",
    "OTC_USDCHF":  "USDCHF_otc",
    "OTC_AUDUSD":  "AUDUSD_otc",
    "OTC_NZDUSD":  "NZDUSD_otc",
    "OTC_USDCAD":  "USDCAD_otc",
    "OTC_EURJPY":  "EURJPY_otc",
    "OTC_EURGBP":  "EURGBP_otc",
    "OTC_EURAUD":  "EURAUD_otc",
    "OTC_EURCAD":  "EURCAD_otc",
    "OTC_EURCHF":  "EURCHF_otc",
    "OTC_GBPJPY":  "GBPJPY_otc",
    "OTC_GBPAUD":  "GBPAUD_otc",
    "OTC_GBPCAD":  "GBPCAD_otc",
    "OTC_GBPCHF":  "GBPCHF_otc",
    "OTC_AUDJPY":  "AUDJPY_otc",
    "OTC_AUDCAD":  "AUDCAD_otc",
    "OTC_CADJPY":  "CADJPY_otc",
    "OTC_CHFJPY":  "CHFJPY_otc",
}

# Inverso: símbolo PO → símbolo OTC
PO_TO_OTC = {v: k for k, v in OTC_SYMBOL_MAP.items()}

# ── Headers seguros para websockets lib (NO incluir Connection/Upgrade/Sec-*
#    porque la librería websockets los gestiona automáticamente y duplicarlos
#    causa HTTP 400) ──────────────────────────────────────────────────────────
CHROME_HEADERS = {
    "User-Agent":       "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/145.0.0.0 Safari/537.36 Edg/145.0.0.0",
    "Origin":           "https://pocketoption.com",
    "Accept-Language":  "es-419,es;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control":    "no-cache",
    "Pragma":           "no-cache",
}

# ── Constantes ────────────────────────────────────────────────────────────────
WS_URL_DEMO = "wss://demo-api-eu.po.market/socket.io/?EIO=4&transport=websocket"
WS_URL_REAL = "wss://api-eu.po.market/socket.io/?EIO=4&transport=websocket"
WS_URL      = WS_URL_DEMO  # Cambia a WS_URL_REAL para cuenta real
PING_INTERVAL   = 25    # segundos base para heartbeat
PING_JITTER     = 3     # ± segundos de variación aleatoria
SUB_DELAY_MIN   = 1.2   # delay mínimo entre suscripciones (comportamiento humano)
SUB_DELAY_MAX   = 3.5   # delay máximo
CANDLE_HISTORY  = 60    # velas a mantener en memoria por par
RECONNECT_DELAY = 5     # segundos antes de reconectar
# Tick en vivo requerido para considerar el buffer "listo" (evita CCI congelado con solo seed TD)
BUFFER_DATA_MAX_AGE_SEC = 120


class CandleBuffer:
    """Buffer circular de velas para un par."""
    def __init__(self, maxlen: int = CANDLE_HISTORY):
        self.candles: deque = deque(maxlen=maxlen)
        self.last_price: float = 0.0
        self.last_update: float = 0.0

    def update(self, price: float, timestamp: float):
        """Agrega tick y construye velas de 1 minuto."""
        self.last_price = price
        self.last_update = timestamp

        # Construye vela del minuto actual
        minute = int(timestamp // 60) * 60
        if self.candles and self.candles[-1]["time"] == minute:
            c = self.candles[-1]
            c["high"]  = max(c["high"], price)
            c["low"]   = min(c["low"],  price)
            c["close"] = price
        else:
            self.candles.append({
                "time":  minute,
                "open":  price,
                "high":  price,
                "low":   price,
                "close": price,
            })

    def get_closes(self) -> List[float]:
        return [c["close"] for c in self.candles]

    def get_highs(self) -> List[float]:
        return [c["high"] for c in self.candles]

    def get_lows(self) -> List[float]:
        return [c["low"] for c in self.candles]

    @property
    def is_ready(self) -> bool:
        """True si hay ≥30 velas y un tick reciente (seed histórico solo no basta)."""
        if len(self.candles) < 30 or self.last_update <= 0:
            return False
        return (time.time() - self.last_update) < BUFFER_DATA_MAX_AGE_SEC


class POWebSocketProvider:
    """
    Proveedor de datos en tiempo real desde PocketOption via WebSocket.
    Reemplaza a TwelveDataProvider con datos 100% exactos de PO.
    """

    def __init__(self):
        self.is_connected:   bool = False
        self.is_configured:  bool = False
        self.source:         str  = "po_websocket"
        self.status:         str  = "disconnected"  # disconnected | connecting | active | evading

        # Buffers de datos por par
        self._buffers: Dict[str, CandleBuffer] = {
            sym: CandleBuffer() for sym in OTC_SYMBOL_MAP
        }

        # Contador por par para log DEBUG de ticks binarios (cada 100 ticks / par)
        self._binary_tick_log_counts: Dict[str, int] = defaultdict(int)

        # Callbacks externos
        self._price_callbacks: List[Callable] = []

        # Estado interno
        self._ws             = None
        self._task           = None
        self._ssid:    str   = ""   # session ID de PO
        self._secret:  str   = ""   # secret token de autenticación
        self._user_id: int   = 0
        self._is_demo: bool = True  # refleja configure(); usado en 42["auth", ...]

        # Kill-switch
        self._kill_switch_active: bool  = False
        self._kill_switch_activated_at: float = 0.0
        self._kill_switch_alert_sent: bool = False
        self._consecutive_errors: int   = 0
        self._max_errors:         int   = 3

        # Estadísticas
        self.ticks_received:  int   = 0
        self.connected_since: float = 0.0

        # Órdenes pendientes: request_id → asyncio.Future
        self._pending_orders: Dict[str, asyncio.Future] = {}

        # Alerta expiración PO_SSID
        self._ssid_configured_at: float = 0.0
        self._ssid_alert_sent: bool = False

        # Proxy residencial para evadir bloqueo de IPs datacenter
        self._proxy_url: str = ""  # formato: "http://user:pass@host:port" o "socks5://..."

    # ── Configuración ─────────────────────────────────────────────────────────

    def configure(self, ssid: str, secret: str = "", user_id: int = 0,
                  full_cookie: str = "", is_demo: bool = True,
                  proxy_url: str = ""):
        """
        Configura las credenciales de sesión.
        ssid: valor de la cookie 'ci_session' de PO
        full_cookie: cadena completa de cookies (opcional, más confiable)
        is_demo: True para cuenta demo, False para cuenta real
        """
        self._ssid       = urllib.parse.unquote(ssid)   # H1: decodificar %3A, %7B, etc.
        self._ssid_configured_at = time.time()
        self._ssid_alert_sent    = False
        self._secret     = secret
        self._user_id    = user_id
        self._is_demo    = is_demo
        self._full_cookie = full_cookie
        self._proxy_url   = proxy_url
        self.is_configured = bool((secret and user_id) or ssid or full_cookie)
        self._ws_url = WS_URL_DEMO if is_demo else WS_URL_REAL
        if proxy_url:
            logger.info("🔌 POWebSocket configurado | user_id=%d | modo=%s | proxy=%s",
                        user_id, "DEMO" if is_demo else "REAL", proxy_url.split("@")[-1])
        else:
            logger.info("🔌 POWebSocket configurado | user_id=%d | modo=%s | sin proxy",
                        user_id, "DEMO" if is_demo else "REAL")

    # ── Inicio ────────────────────────────────────────────────────────────────

    async def start(self):
        """Arranca el loop de conexión en background.

        Idempotente: si ya hay una tarea corriendo no lanza un segundo loop.
        """
        if not self.is_configured:
            logger.warning("⚠️  POWebSocket no configurado — falta SSID")
            return
        if self._task and not self._task.done():
            logger.debug("♻️  POWebSocket ya en ejecución — start() no-op")
            return
        self._task = asyncio.create_task(self._connection_loop())
        logger.info("🚀 POWebSocket iniciado")

    async def stop(self):
        """Detiene la conexión limpiamente y espera a que el loop termine."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
        self._ws = None
        self.is_connected = False
        self.status = "disconnected"
        logger.info("🛑 POWebSocket detenido")

    # ── Loop principal ────────────────────────────────────────────────────────

    async def _connection_loop(self):
        """Reconecta automáticamente si se pierde la conexión."""
        while True:
            try:
                self.status = "connecting"
                logger.info("🔄 Conectando a PO WebSocket...")
                await self._connect_and_run()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._consecutive_errors += 1
                err_str = str(e)
                logger.warning("⚠️  Error WebSocket: %s (intento %d)",
                               e, self._consecutive_errors)

                # HTTP 400 con cookie → PO rechaza por IP mismatch.
                # Reintenta sin cookie (demo acepta conexiones anónimas).
                if "400" in err_str and not getattr(self, "_skip_cookie", False):
                    self._skip_cookie = True
                    self._consecutive_errors = 0
                    logger.info("🔄 Cookie rechazada por IP — reintentando sin cookie")
                    await asyncio.sleep(2)
                    continue

                if self._consecutive_errors >= self._max_errors:
                    self._activate_kill_switch()

                delay = RECONNECT_DELAY * self._consecutive_errors
                logger.info("⏳ Reconectando en %ds...", delay)
                await asyncio.sleep(delay)

    async def _connect_and_run(self):
        """Establece conexión y maneja mensajes."""
        headers = {**CHROME_HEADERS}

        # Cookie de sesión — solo incluir si el SSID fue obtenido desde la
        # misma IP del VPS.  Si PO rechaza con HTTP 400, reconectamos sin cookie
        # (el endpoint demo acepta conexiones anónimas para price feeds).
        if not getattr(self, "_skip_cookie", False):
            if getattr(self, "_full_cookie", ""):
                headers["Cookie"] = self._full_cookie
            elif self._ssid:
                headers["Cookie"] = f"ci_session={self._ssid}"

        connect_kwargs = dict(
            additional_headers=headers,
            ping_interval=None,   # manejamos ping manualmente con jitter
            ping_timeout=30,
            close_timeout=10,
            max_size=10 * 1024 * 1024,
        )
        if self._proxy_url:
            # websockets usa python-socks internamente para SOCKS; sin el paquete falla en runtime
            scheme = self._proxy_url.split("://", 1)[0].lower() if "://" in self._proxy_url else ""
            if scheme.startswith("socks"):
                try:
                    import python_socks  # noqa: F401  # type: ignore[import-untyped]
                except ImportError as exc:
                    logger.error(
                        "PO_PROXY_URL es SOCKS5 pero falta python-socks — "
                        "añade python-socks[asyncio] a backend/requirements.txt y rebuild"
                    )
                    raise RuntimeError(
                        "connecting through a SOCKS proxy requires python-socks"
                    ) from exc
            connect_kwargs["proxy"] = self._proxy_url
            logger.info("🌐 Conectando vía proxy → %s", self._proxy_url.split("@")[-1])

        async with websockets.connect(self._ws_url, **connect_kwargs) as ws:
            self._ws             = ws
            self.is_connected    = True
            self.connected_since = time.time()
            self.status          = "active"
            self._consecutive_errors = 0

            logger.info("✅ POWebSocket conectado a events-po.com")

            try:
                # Lanza tasks paralelas
                await asyncio.gather(
                    self._message_handler(ws),
                    self._heartbeat_loop(ws),
                )
            finally:
                # El servidor cerró la conexión (timeout normal) — marcar desconectado
                # para que los logs reflejen el estado real durante el warmup
                self.is_connected = False
                self.status       = "connecting"

    # ── Handshake y autenticación ─────────────────────────────────────────────

    async def _handle_handshake(self, ws, data: str):
        """Procesa el mensaje inicial de Socket.IO."""
        # Mensaje 0: {"sid":"...","upgrades":[],"pingInterval":...}
        try:
            info = json.loads(data)
            sid  = info.get("sid", "")
            logger.info("🤝 Socket.IO handshake | sid=%s", sid[:8])
        except Exception:
            pass

        # Responde con upgrade a WebSocket (mensaje "40")
        await ws.send("40")

        # Crear auth_event aquí para que esté listo cuando llegue el "40" de PO
        self._auth_event = asyncio.Event()

        # Suscripción diferida: espera confirmación de auth antes de suscribir pares
        asyncio.create_task(self._subscribe_after_auth(ws))

    async def _subscribe_pairs(self, ws):
        """Suscripción progresiva con jitter humano."""
        symbols = list(OTC_SYMBOL_MAP.values())
        logger.info("📡 Suscribiendo %d pares con jitter humano...", len(symbols))

        for i, po_sym in enumerate(symbols):
            await ws.send(f'42{json.dumps(["subscribeSymbol", {"asset": "#" + po_sym}])}')

            # Delay aleatorio entre suscripciones (comportamiento humano)
            if i < len(symbols) - 1:
                delay = random.uniform(SUB_DELAY_MIN, SUB_DELAY_MAX)
                await asyncio.sleep(delay)

        logger.info("✅ Suscripción completa a %d pares", len(symbols))

    async def _subscribe_after_auth(self, ws, timeout: float = 5.0):
        """
        Espera la confirmación de auth de PO (evento successauth / user_ready) antes
        de enviar las suscripciones de pares.  Si PO no emite el evento en `timeout`
        segundos, suscribe de todas formas como fallback — mismo comportamiento que
        el sleep ciego anterior, pero disparado DESPUÉS de que el auth fue aceptado.

        El guard `self._ws is ws` descarta la operación si el socket fue reemplazado
        por una reconexión durante la espera.
        """
        auth_event = getattr(self, "_auth_event", None)
        if auth_event:
            try:
                await asyncio.wait_for(auth_event.wait(), timeout=timeout)
                logger.info("✅ Auth PO confirmado por servidor — suscribiendo pares")
            except asyncio.TimeoutError:
                logger.warning(
                    "⚠️  Auth PO sin confirmación en %.1fs — suscribiendo de todas formas (fallback)",
                    timeout,
                )
        else:
            # Sin evento (no debería ocurrir): esperar el timeout directamente
            await asyncio.sleep(timeout)

        if self._ws is not ws:
            logger.debug("🔄 Socket reemplazado durante espera de auth — suscripción cancelada")
            return
        await self._subscribe_pairs(ws)

    # ── Handler de mensajes ───────────────────────────────────────────────────

    async def _message_handler(self, ws):
        """Procesa todos los mensajes entrantes."""
        async for raw in ws:
            try:
                await self._process_message(ws, raw)
            except Exception as e:
                logger.debug("Error procesando mensaje: %s", e)

    async def _process_message(self, ws, raw):
        """Decodifica y enruta cada mensaje de Socket.IO."""

        # ── Mensajes BINARIOS: ["SYMBOL_otc", price_integer] ─────────────────
        # Formato confirmado por ingeniería inversa del protocolo PO:
        # bytes UTF-8 → ["EURJPY_otc", 186742000] → precio = 186742000 / 1_000_000
        if isinstance(raw, bytes):
            await self._handle_binary_price(raw)
            return

        if not isinstance(raw, str):
            return

        # Socket.IO prefix
        if raw.startswith("0"):
            await self._handle_handshake(ws, raw[1:])
            return

        if raw == "2":
            # Ping del servidor → responder con pong
            await ws.send("3")
            return

        if raw.startswith("40"):
            # Namespace confirmado por PO → enviamos auth con user_init
            logger.info("🔍 Socket.IO msg-40 | namespace confirmado, enviando auth...")
            if self._user_id and self._secret:
                auth_msg = json.dumps(["user_init", {
                    "id":     self._user_id,
                    "secret": self._secret,
                }])
                await ws.send(f"42{auth_msg}")
                logger.info("🔐 Auth enviado | user_id=%d", self._user_id)
            return

        # Mensajes con adjunto binario: "451-[...]" → el binario llega aparte
        if raw.startswith("45"):
            try:
                bracket = raw.index("[")
                payload = json.loads(raw[bracket:])
                event   = payload[0] if payload else ""
                data    = payload[1] if len(payload) > 1 else {}
                await self._handle_event(event, data)
            except (json.JSONDecodeError, ValueError):
                pass
            return

        if raw.startswith("42"):
            try:
                payload = json.loads(raw[2:])
                event   = payload[0] if payload else ""
                data    = payload[1] if len(payload) > 1 else {}
                await self._handle_event(event, data)
            except json.JSONDecodeError:
                pass

    async def _handle_binary_price(self, raw: bytes):
        """
        Decodifica mensajes binarios de precio de PO.
        Formato: ["SYMBOL_otc", price_integer]
        Precio real = price_integer / 1_000_000

        Confirmado por ingeniería inversa:
          bytes: 5B 22 45 55 52 4A 50 59 5F 6F 74 63 22 2C 31 37 37 32 33 31 31 37 36 5D
          texto: ["EURJPY_otc",177231176]
          precio: 177231176 / 1_000_000 = 177.231176

        Diagnóstico si no ves logs DEBUG "tick binary | ..." (cada 100 ticks por par):
          - SSID/cookie inválidos o IP distinta a la del navegador (PO corta el feed).
          - Feed solo por JSON (updateStream) y no por frames binarios → revisar _handle_price.
          - Suscripción enviada pero activo sin cotización en demo / mercado cerrado.
          - Activar logging DEBUG en ``po_websocket``; sin ticks no aparecerá ninguna línea.
        """
        try:
            text   = raw.decode("utf-8", errors="replace")
            parsed = json.loads(text)

            if not isinstance(parsed, list) or len(parsed) < 2:
                return

            symbol    = parsed[0]   # "EURJPY_otc"
            price_raw = parsed[1]   # 186742000 (entero)

            if not isinstance(symbol, str) or not isinstance(price_raw, (int, float)):
                return

            price   = float(price_raw) / 1_000_000
            ts      = time.time()
            otc_sym = PO_TO_OTC.get(symbol, symbol)

            if otc_sym not in self._buffers:
                return

            self._buffers[otc_sym].update(price, ts)
            self.ticks_received += 1

            self._binary_tick_log_counts[otc_sym] += 1
            if self._binary_tick_log_counts[otc_sym] % 100 == 0:
                logger.debug(
                    "tick binary | %s price=%.6f ticks_total=%d (cada 100 ticks/par)",
                    otc_sym, price, self.ticks_received,
                )

            # Diagnóstico agregado (INFO cada 50 ticks globales)
            buf = self._buffers[otc_sym]
            if self.ticks_received % 50 == 0:
                logger.info(
                    "📊 %s | price=%.5f | ts=%.0f | velas=%d | ready=%s",
                    otc_sym, price, ts, len(buf.candles), buf.is_ready
                )

            for cb in self._price_callbacks:
                try:
                    asyncio.create_task(cb(otc_sym, price))
                except Exception:
                    pass

        except (json.JSONDecodeError, KeyError, TypeError):
            pass

    async def _handle_event(self, event: str, data):
        """Enruta eventos por tipo."""

        # Precio en tiempo real
        if event in ("updateStream", "candle", "tick", "price_update"):
            await self._handle_price(data)

        # Autenticación exitosa — desbloquea la suscripción de pares
        elif event in ("user_ready", "successauth", "authenticated", "updateAssets", "auth/success"):
            logger.info("✅ Auth PO confirmado — evento='%s'", event)
            auth_event = getattr(self, "_auth_event", None)
            if auth_event and not auth_event.is_set():
                auth_event.set()

        # Error de autenticación
        elif event in ("notauthorized", "error"):
            logger.warning("🔴 Error de auth PO: %s", data)
            from services.telegram_service import send_telegram
            asyncio.create_task(send_telegram(
                "🔴 PO_SSID rechazado por PocketOption\n"
                "El bot perdió conexión. Actualiza ci_session en .env y reinicia."
            ))
            self._activate_kill_switch()

        # Candle histórica
        elif event in ("candles", "history"):
            await self._handle_history(data)

        # Respuesta de orden abierta
        elif event in ("openOrder", "successOpenOrder", "order_placed"):
            await self._handle_order_response(data)

        # Resultado final de orden (win/loss)
        elif event in ("closeOrder", "successCloseOrder"):
            await self._handle_order_close(data)

        else:
            snippet = str(data)[:120] if data is not None else ""
            logger.info("🔍 evento PO desconocido | %s | %s", event, snippet)

    async def _handle_price(self, data: dict):
        """Procesa tick de precio y actualiza buffer."""
        if not isinstance(data, dict):
            return

        # Diferentes formatos posibles de PO
        asset = (data.get("asset") or data.get("symbol") or
                 data.get("active") or "")
        price = (data.get("price") or data.get("value") or
                 data.get("close") or 0.0)
        ts    = data.get("time") or data.get("timestamp") or time.time()

        if not asset or not price:
            return

        # Convertir símbolo PO → símbolo OTC interno
        otc_sym = PO_TO_OTC.get(asset, asset)
        if otc_sym not in self._buffers:
            return

        self._buffers[otc_sym].update(float(price), float(ts))
        self.ticks_received += 1

        # Diagnóstico temporal — quitar tras verificar ticks/velas
        buf = self._buffers[otc_sym]
        if self.ticks_received % 50 == 0:
            logger.info(
                "📊 [JSON] %s | price=%.5f | ts=%.0f | velas=%d | ready=%s",
                otc_sym, float(price), float(ts), len(buf.candles), buf.is_ready
            )

        # Notifica callbacks externos (para el scan loop)
        for cb in self._price_callbacks:
            try:
                asyncio.create_task(cb(otc_sym, float(price)))
            except Exception:
                pass

        if self.ticks_received % 100 == 0:
            logger.debug("📈 %d ticks recibidos | último: %s=%.5f",
                         self.ticks_received, otc_sym, price)

    async def _handle_history(self, data):
        """Carga velas históricas al conectar."""
        if not isinstance(data, dict):
            return
        asset   = data.get("asset", "")
        candles = data.get("candles") or data.get("data") or []
        otc_sym = PO_TO_OTC.get(asset, asset)

        if otc_sym not in self._buffers:
            return

        buf = self._buffers[otc_sym]
        for c in candles[-CANDLE_HISTORY:]:
            price = c.get("close") or c.get("value") or 0.0
            ts    = c.get("time")  or c.get("timestamp") or 0
            if price and ts:
                buf.update(float(price), float(ts))

        logger.info("📚 Historial cargado | %s | %d velas", otc_sym, len(candles))

    # ── Gestión de órdenes ────────────────────────────────────────────────────

    async def _handle_order_response(self, data: dict):
        """Resuelve el future pendiente cuando PO confirma la apertura de una orden."""
        if not isinstance(data, dict):
            return
        req_id = str(data.get("requestId") or data.get("request_id") or "")
        if req_id and req_id in self._pending_orders:
            fut = self._pending_orders.pop(req_id)
            if not fut.done():
                order_id = str(data.get("id") or data.get("order_id") or req_id)
                fut.set_result({
                    "order_id":  order_id,
                    "status":    "placed",
                    "raw":       data,
                })
            logger.info("✅ Orden confirmada por PO | order_id=%s", req_id[:12])

    async def _handle_order_close(self, data: dict):
        """Loguea el resultado de una orden cerrada (win/loss)."""
        if not isinstance(data, dict):
            return
        order_id = data.get("id") or data.get("order_id") or "?"
        profit   = data.get("profit") or data.get("amount") or 0
        win      = float(profit) > 0 if profit else None
        logger.info("📋 Orden cerrada | id=%s | resultado=%s | profit=%s",
                    order_id, "WIN" if win else "LOSS", profit)

    async def place_trade(
        self,
        symbol:          str,
        direction:       str,
        amount:          float = 100.0,
        expiry_seconds:  int   = 120,
        is_demo:         bool  = True,
        timeout:         float = 10.0,
    ) -> dict:
        """
        Envía una orden de opción binaria a PocketOption vía WebSocket.

        Parámetros:
            symbol         - símbolo OTC interno (e.g. "OTC_EURUSD")
            direction      - "call" o "put" (case-insensitive)
            amount         - monto en USD (default $100)
            expiry_seconds - duración del trade en segundos (default 120s = 2min)
            is_demo        - True para cuenta demo, False para real
            timeout        - segundos a esperar confirmación de PO

        Retorna:
            {"order_id": "...", "status": "placed"} si exitoso
            {"order_id": None,  "status": "error",  "reason": "..."} si falla
        """
        if not self.is_connected or not self._ws:
            return {"order_id": None, "status": "error", "reason": "WebSocket no conectado"}
        if self._kill_switch_active:
            return {"order_id": None, "status": "error", "reason": "Kill-switch activo"}

        po_symbol  = OTC_SYMBOL_MAP.get(symbol, f"#{symbol.replace('OTC_', '')}_otc")
        action     = direction.lower()
        request_id = f"radar_{int(time.time() * 1000)}_{random.randint(1000, 9999)}"

        order_msg = json.dumps(["openOrder", {
            "asset":      po_symbol,
            "amount":     amount,
            "action":     action,
            "isDemo":     1 if is_demo else 0,
            "requestId":  request_id,
            "optionType": 100,   # binaria estándar
            "time":       expiry_seconds,
        }])

        # Crea future para esperar la confirmación
        loop = asyncio.get_running_loop()
        fut  = loop.create_future()
        self._pending_orders[request_id] = fut

        try:
            await self._ws.send(f"42{order_msg}")
            logger.info("▶️  Orden enviada a PO | %s %s $%.0f %ds [req=%s]",
                        action.upper(), po_symbol, amount, expiry_seconds, request_id[:16])

            # Espera confirmación con timeout
            result = await asyncio.wait_for(asyncio.shield(fut), timeout=timeout)
            return result

        except asyncio.TimeoutError:
            self._pending_orders.pop(request_id, None)
            logger.warning("⏱️  Timeout esperando confirmación de PO | req=%s", request_id[:16])
            # Aún reportamos como colocada (PO puede ejecutarla sin confirmar)
            return {"order_id": request_id, "status": "placed_unconfirmed"}

        except Exception as e:
            self._pending_orders.pop(request_id, None)
            logger.error("❌ Error al colocar orden: %s", e)
            return {"order_id": None, "status": "error", "reason": str(e)}

    # ── Heartbeat con jitter ──────────────────────────────────────────────────

    async def _heartbeat_loop(self, ws):
        """Envía ping-server con variación aleatoria (no robótico)."""
        _last_ssid_check = 0.0
        _last_kill_switch_check = 0.0
        SSID_CHECK_INTERVAL = 3600.0  # 1 hora
        KILL_SWITCH_CHECK_INTERVAL = 300.0  # 5 minutos
        SSID_EXPIRY_DAYS = 28
        KILL_SWITCH_ALERT_THRESHOLD = 1800  # 30 minutos

        while True:
            # Intervalo con jitter: 25s ± 3s aleatorio
            interval = PING_INTERVAL + random.uniform(-PING_JITTER, PING_JITTER)
            await asyncio.sleep(interval)

            try:
                now = time.time()

                # Check kill-switch activo > 30 min cada 5 minutos
                if now - _last_kill_switch_check >= KILL_SWITCH_CHECK_INTERVAL:
                    _last_kill_switch_check = now
                    if (self._kill_switch_active
                            and not self._kill_switch_alert_sent
                            and self._kill_switch_activated_at > 0
                            and (now - self._kill_switch_activated_at) >= KILL_SWITCH_ALERT_THRESHOLD):
                        self._kill_switch_alert_sent = True
                        from services.telegram_service import send_telegram
                        asyncio.create_task(send_telegram(
                            "🔴 KILL-SWITCH activo hace más de 30 minutos\n"
                            "El bot NO está operando.\n"
                            "Verifica la conexión a PocketOption y renueva el SSID si es necesario."
                        ))

                # Check expiración SSID cada hora
                if now - _last_ssid_check >= SSID_CHECK_INTERVAL:
                    _last_ssid_check = now
                    if (self._ssid_configured_at > 0
                            and not self._ssid_alert_sent
                            and (now - self._ssid_configured_at) >= SSID_EXPIRY_DAYS * 86400):
                        self._ssid_alert_sent = True
                        from services.telegram_service import send_telegram
                        asyncio.create_task(send_telegram(
                            "⚠️ PO_SSID expira pronto\n"
                            "Han pasado 28 días desde la última configuración.\n"
                            "Renueva ci_session en .env y reinicia el bot."
                        ))

                ping_msg = json.dumps(["ping-server"])
                await ws.send(f"42{ping_msg}")
                logger.debug("💓 Heartbeat enviado (%.1fs)", interval)
            except ConnectionClosed:
                break

    # ── Kill-Switch ───────────────────────────────────────────────────────────

    def _activate_kill_switch(self):
        """
        Activa modo seguro:
        - Desconecta WebSocket
        - Señaliza fallback a Twelve Data
        - Dashboard muestra ALERTA ROJA
        """
        if not self._kill_switch_active:
            self._kill_switch_active = True
            if self._kill_switch_activated_at == 0.0:
                self._kill_switch_activated_at = time.time()
                self._kill_switch_alert_sent = False
            self.status = "evading"
            self.is_connected = False
            logger.warning("🔴 KILL-SWITCH ACTIVADO — Fallback a Twelve Data")

    def reset_kill_switch(self):
        """Resetea el kill-switch para intentar reconectar."""
        self._kill_switch_active = False
        self._kill_switch_activated_at = 0.0
        self._kill_switch_alert_sent = False
        self._consecutive_errors = 0
        self.status = "disconnected"
        logger.info("🟢 Kill-switch reseteado — intentando reconectar")

    # ── API pública para el bot ───────────────────────────────────────────────

    def seed_from_candles(self, otc_symbol: str, candles: list) -> int:
        """
        Siembra el buffer con velas históricas (CandleData de TwelveData).
        Se llama UNA sola vez al inicio por par para evitar el warmup de 30 min.
        Retorna el número de velas agregadas.
        """
        buf = self._buffers.get(otc_symbol)
        if not buf:
            return 0
        added = 0
        for c in candles:
            try:
                ts     = datetime.strptime(c.time, "%Y-%m-%d %H:%M:%S").timestamp()
                minute = int(ts // 60) * 60
                if buf.candles and buf.candles[-1]["time"] == minute:
                    buf.candles[-1]["close"] = c.close
                    buf.candles[-1]["high"]  = max(buf.candles[-1]["high"], c.high)
                    buf.candles[-1]["low"]   = min(buf.candles[-1]["low"],  c.low)
                else:
                    buf.candles.append({
                        "time":  minute,
                        "open":  c.open,
                        "high":  c.high,
                        "low":   c.low,
                        "close": c.close,
                    })
                    added += 1
            except Exception:
                pass
        # No tocar last_update: solo ticks en vivo (update / _handle_binary_price)
        # deben marcar datos como recientes; si no, is_ready=False y el scan hace fallback.
        if added:
            buf.last_price = candles[-1].close if candles else buf.last_price
        return added

    def get_cached_price(self, otc_symbol: str) -> Optional[float]:
        """Retorna el último precio conocido del par (válido si tiene < 60s)."""
        return self.get_latest_price(otc_symbol, max_age_seconds=60)

    def get_latest_price(self, otc_symbol: str, max_age_seconds: int = 180) -> Optional[float]:
        """
        Retorna el último precio conocido del par con tolerancia de edad configurable.
        Diseñado para auditoría: acepta precios hasta max_age_seconds de antigüedad.
        Útil cuando el WebSocket se reconecta brevemente durante la ventana de verificación.
        """
        buf = self._buffers.get(otc_symbol)
        if buf and buf.last_price > 0:
            if time.time() - buf.last_update < max_age_seconds:
                return buf.last_price
        return None

    def get_candles(self, otc_symbol: str) -> List[dict]:
        """Retorna las velas acumuladas del par."""
        buf = self._buffers.get(otc_symbol)
        return list(buf.candles) if buf else []

    def is_ready(self, otc_symbol: str) -> bool:
        """True si hay suficientes datos para generar señales."""
        buf = self._buffers.get(otc_symbol)
        return buf.is_ready if buf else False

    def seconds_since_last_tick(self) -> Optional[float]:
        """
        Segundos transcurridos desde el tick más reciente en cualquier par.
        None si nunca se recibió tick en vivo (last_update == 0 en todos).
        """
        latest = 0.0
        for buf in self._buffers.values():
            if buf.last_update > latest:
                latest = buf.last_update
        if latest <= 0:
            return None
        return round(time.time() - latest, 3)

    def get_status(self) -> dict:
        """Estado completo del proveedor para el dashboard."""
        ready_pairs = sum(
            1 for sym in OTC_SYMBOL_MAP
            if self._buffers[sym].is_ready
        )
        return {
            "source":            self.source,
            "status":            self.status,
            "is_connected":      self.is_connected,
            "kill_switch":       self._kill_switch_active,
            "ticks_received":    self.ticks_received,
            "ready_pairs":       ready_pairs,
            "total_pairs":       len(OTC_SYMBOL_MAP),
            "connected_since":   datetime.utcfromtimestamp(
                                     self.connected_since
                                 ).isoformat() if self.connected_since else None,
            "uptime_minutes":    round(
                                     (time.time() - self.connected_since) / 60, 1
                                 ) if self.connected_since else 0,
        }

    def on_price_update(self, callback: Callable):
        """Registra callback para recibir updates de precio en tiempo real."""
        self._price_callbacks.append(callback)


# ── Singleton global ──────────────────────────────────────────────────────────
_po_provider: Optional[POWebSocketProvider] = None


def get_po_provider() -> Optional[POWebSocketProvider]:
    return _po_provider


def init_po_provider(ssid: str, secret: str = "", user_id: int = 0,
                     full_cookie: str = "", is_demo: bool = True,
                     proxy_url: str = "") -> POWebSocketProvider:
    """Devuelve el singleton POWebSocketProvider, reutilizando la instancia
    existente cuando ya hay una — preserva _buffers, _price_callbacks y
    _pending_orders sin necesidad de copiar estado entre objetos.

    Primera llamada: crea la instancia.
    Llamadas siguientes: solo reconfigura credenciales; start() es idempotente
    por lo que el _connection_loop en curso no se duplica.
    """
    global _po_provider
    resolved_proxy = proxy_url or os.getenv("PO_PROXY_URL", "")
    if _po_provider is not None:
        _po_provider.configure(ssid, secret, user_id, full_cookie, is_demo,
                               proxy_url=resolved_proxy)
        return _po_provider
    _po_provider = POWebSocketProvider()
    _po_provider.configure(ssid, secret, user_id, full_cookie, is_demo,
                           proxy_url=resolved_proxy)
    return _po_provider
