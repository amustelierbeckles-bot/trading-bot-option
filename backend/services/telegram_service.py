"""
Subsistema completo de Telegram para el trading bot.

Incluye:
  - Helpers de tiempo local (DST-aware Cuba/Eastern)
  - API wrapper (_tg_api, _tg_edit_message)
  - Notificaciones: _send_telegram, _send_pre_alert_telegram, _send_signal_telegram
  - Manejo de callbacks inline (_handle_tg_callback)
  - Long polling (_telegram_polling_loop)
"""
import asyncio
import html
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Estado en memoria de auditorías activas
# { msg_id_str: { signal, chat_id, entry_time, audit_id, operated, app } }
_tg_active_trades: dict = {}
_tg_last_update_id: int = 0


# ============================================================================
# Helpers de tiempo local (DST Cuba/Eastern)
# ============================================================================

def get_local_offset() -> timedelta:
    """Devuelve el offset UTC correcto según DST de Cuba/Eastern."""
    now_utc   = datetime.utcnow()
    year      = now_utc.year
    dst_start = datetime(year, 3, 8) + timedelta(days=(6 - datetime(year, 3, 8).weekday()) % 7)
    dst_end   = datetime(year, 11, 1) + timedelta(days=(6 - datetime(year, 11, 1).weekday()) % 7)
    if dst_start <= now_utc < dst_end:
        return timedelta(hours=-4)
    return timedelta(hours=-5)


def local_time(dt: datetime = None) -> datetime:
    """Convierte UTC al horario local (DST-aware)."""
    return (dt or datetime.utcnow()) + get_local_offset()


def fmt_time(dt: datetime = None) -> str:
    """Formatea hora local para mensajes de Telegram."""
    offset = get_local_offset()
    label  = "UTC-4" if offset.total_seconds() == -4 * 3600 else "UTC-5"
    return local_time(dt).strftime("%H:%M:%S") + f" ({label})"


def parse_naive_utc(ts: str) -> datetime:
    """Parsea timestamps ISO sin zona horaria como UTC naive."""
    ts = ts.replace("Z", "").replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(ts, fmt)
        except ValueError:
            continue
    return datetime.utcnow()


# ============================================================================
# Telegram API wrappers
# ============================================================================

async def tg_api(method: str, payload: dict) -> dict:
    """Wrapper para llamar la Telegram Bot API."""
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


async def tg_edit_message(chat_id: str, msg_id: int, text: str,
                           keyboard: Optional[dict] = None):
    """Edita un mensaje existente de Telegram."""
    payload = {
        "chat_id":    chat_id,
        "message_id": msg_id,
        "text":       text,
        "parse_mode": "HTML",
    }
    payload["reply_markup"] = keyboard if keyboard else {"inline_keyboard": []}
    await tg_api("editMessageText", payload)


async def send_telegram(message: str) -> bool:
    """Envía mensaje simple via Telegram Bot API."""
    token   = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    enabled = os.getenv("TELEGRAM_ENABLED", "false").lower() == "true"

    if not enabled or not token or not chat_id or chat_id == "your_chat_id_here":
        return False

    try:
        url     = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                return True
            logger.warning("⚠️  Telegram error %d: %s", resp.status_code, resp.text[:200])
            return False
    except Exception as e:
        logger.warning("⚠️  Telegram excepción: %s", e)
        return False


async def send_pre_alert_telegram(pre_doc: dict) -> None:
    """Envía notificación corta de Pre-Alerta sin botones."""
    token   = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id or os.getenv("TELEGRAM_ENABLED", "false").lower() != "true":
        return

    direction  = "▲ CALL" if pre_doc.get("type") == "CALL" else "▼ PUT"
    asset      = pre_doc.get("asset_name", "")
    conf_pct   = pre_doc.get("confluence_pct", 60)
    session    = pre_doc.get("session", "")
    strategies = ", ".join(str(s) for s in pre_doc.get("strategies_fired", []))
    now_local  = fmt_time(datetime.utcnow())

    asset_e = html.escape(str(asset))
    session_e = html.escape(str(session))
    strategies_e = html.escape(strategies)

    text = (
        f"⏳ <b>PRE-ALERTA</b> — {asset_e}\n"
        f"{direction} | {conf_pct}% Confluencia\n\n"
        f"Condiciones formándose. Esté atento para una posible\n"
        f"operación en los próximos <b>2-3 minutos</b>.\n\n"
        f"📊 Estrategias activas: <i>{strategies_e}</i>\n"
        f"🕐 {now_local} | {session_e}"
    )

    try:
        await tg_api("sendMessage", {
            "chat_id":              chat_id,
            "text":                 text,
            "parse_mode":           "HTML",
            "disable_notification": False,
        })
        logger.info("⏳ Pre-alerta Telegram | %s %s | %d%%",
                    pre_doc.get("type"), asset, conf_pct)
    except Exception as e:
        logger.debug("Pre-alerta Telegram error: %s", e)


async def send_signal_telegram(signal: dict, app=None) -> Optional[int]:
    """
    Envía señal a Telegram con botones inline y auditoría autónoma.

    1. Envía mensaje con botones "Voy a operar" / "Ignorar"
    2. Almacena referencia en _tg_active_trades para el callback handler
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

    # Auto-registro desactivado — solo se registran trades cuando el usuario confirma
    audit_id = None

    asset_safe = html.escape(str(signal.get("asset_name", "")))
    session_safe = html.escape(str(signal.get("session", "")))

    text = (
        f"{header}\n\n"
        f"<b>{asset_safe}</b>\n"
        f"{direction}\n\n"
        f"Score: <b>{score_pct}%</b> | CCI: <b>{signal.get('cci', 0):.0f}</b>\n"
        f"Payout: <b>{signal.get('payout', 85):.0f}%</b> | {session_safe}\n"
        f"Entrada: <b>{fmt_time(now)}</b>\n\n"
        f"⏰ <b>2 minutos | El bot verificará el resultado automáticamente</b>\n"
        f"Pulsa si decides operar:"
    )

    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ Voy a operar", "callback_data": f"operate:{sid}"},
            {"text": "⏭ Ignorar",       "callback_data": f"ignore:{sid}"},
        ]]
    }

    result = await tg_api("sendMessage", {
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
            "audit_id":   None,
            "entry_time": now,
            "operated":   False,
            "app":        app,
        }
        logger.info("📱 Telegram enviado | msg_id=%s | %s %s",
                    msg_id, signal.get("type"), signal.get("asset_name"))

    return msg_id


# ============================================================================
# Callback handler
# ============================================================================

async def handle_tg_callback(callback: dict, app):
    """
    Procesa callbacks de botones inline:
      operate:SIGNAL_ID  → registra entrada, programa auditoría
      ignore:SIGNAL_ID   → edita mensaje a "Señal ignorada"
      result:win:MSG_ID  → registra WIN manual
      result:loss:MSG_ID → registra LOSS manual
    """
    from services.audit_service import autonomous_audit

    query_id  = callback.get("id")
    data      = callback.get("data", "")
    chat_id   = str(callback.get("message", {}).get("chat", {}).get("id", ""))
    msg_id    = callback.get("message", {}).get("message_id")

    await tg_api("answerCallbackQuery", {"callback_query_id": query_id})

    parts = data.split(":")

    if parts[0] == "operate":
        trade_key    = str(msg_id)
        confirm_time = datetime.utcnow()

        trade_entry = _tg_active_trades.get(trade_key, {})
        if trade_entry:
            trade_entry["operated"]   = True
            trade_entry["entry_time"] = confirm_time

        signal  = trade_entry.get("signal", {})
        asset   = signal.get("asset_name", "")
        stype   = signal.get("type", "")
        app_ref = trade_entry.get("app")
        audit_id = trade_entry.get("audit_id")

        if app_ref and app_ref.state.use_mongo:
            try:
                trade_doc = {
                    "signal_id":        signal.get("id", ""),
                    "symbol":           signal.get("symbol", ""),
                    "asset_name":       asset,
                    "signal_type":      stype,
                    "result":           "pending",
                    "entry_price":      signal.get("entry_price", signal.get("price", 0)),
                    "quality_score":    signal.get("quality_score", 0),
                    "cci":              signal.get("cci", 0),
                    "signal_timestamp": signal.get("created_at", ""),
                    "source":           "telegram_operated",
                    "created_at":       confirm_time,
                }
                ins      = await app_ref.state.db.trades.insert_one(trade_doc)
                audit_id = str(ins.inserted_id)
                _tg_active_trades[trade_key]["audit_id"] = audit_id
                logger.info("📝 Trade pendiente | audit_id=%s | %s %s", audit_id, stype, asset)
            except Exception as e:
                logger.warning("⚠️  No se pudo registrar trade: %s", e)

        asset_esc = html.escape(str(asset))
        stype_esc = html.escape(str(stype))
        await tg_edit_message(chat_id, msg_id,
            f"✅ <b>Operación confirmada — Auditoría activa</b>\n\n"
            f"<b>{asset_esc}</b> — {stype_esc}\n"
            f"🕐 Entrada: <b>{fmt_time(confirm_time)}</b>\n\n"
            f"⏳ Verificando resultado automáticamente en 2 minutos...\n"
            f"<i>También podrás corregir el resultado si es necesario.</i>"
        )

        if app_ref:
            asyncio.create_task(autonomous_audit(
                chat_id, msg_id, signal, confirm_time, audit_id, app_ref
            ))
            logger.info("🔄 Auditoría autónoma lanzada | %s %s | audit_id=%s",
                        stype, asset, audit_id)

    elif parts[0] == "ignore":
        trade_key = str(msg_id)
        signal    = _tg_active_trades.pop(trade_key, {}).get("signal", {})
        ign_asset = html.escape(str(signal.get("asset_name", "")))
        ign_type = html.escape(str(signal.get("type", "")))
        await tg_edit_message(chat_id, msg_id,
            f"⏭ <b>Señal ignorada</b>\n"
            f"{ign_asset} — {ign_type}\n"
            f"<i>Esperando próxima señal...</i>"
        )

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
        res_asset = html.escape(str(signal.get("asset_name", "")))
        res_type = html.escape(str(signal.get("type", "")))
        await tg_edit_message(chat_id, msg_id,
            f"📊 <b>Auditoría completada: {'[W]' if outcome=='win' else '[L]'}</b>\n\n"
            f"{res_asset} — {res_type}\n"
            f"{icon} Resultado corregido manualmente ✓"
        )
        _tg_active_trades.pop(trade_key, None)
        logger.info("📱 Resultado manual | %s | %s", outcome.upper(), signal.get("asset_name"))


# ============================================================================
# Telegram polling loop
# ============================================================================

async def telegram_polling_loop(app):
    """
    Long polling de Telegram. Espera callbacks de botones inline.
    Corre en background; solo activo si TELEGRAM_ENABLED=true.
    """
    global _tg_last_update_id

    token   = os.getenv("TELEGRAM_BOT_TOKEN", "")
    enabled = os.getenv("TELEGRAM_ENABLED", "false").lower() == "true"

    if not token or not enabled:
        logger.info("📵 Telegram polling desactivado (sin token o TELEGRAM_ENABLED=false)")
        return

    logger.info("🔄 Telegram polling iniciado — esperando callbacks")

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
                    asyncio.create_task(handle_tg_callback(cb, app))

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning("⚠️  Telegram polling error: %s", e)
            await asyncio.sleep(5)
