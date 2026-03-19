"""
Servicio de auditoría autónoma de señales.

Módulos:
  - MAE sampling (Maximum Adverse Excursion)
  - Auto-registro de observaciones
  - Verificación de resultado de señal (Twelve Data / PO WebSocket)
  - Verificación universal de todas las señales
  - Auditoría autónoma completa del ciclo de vida
"""
import asyncio
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


async def mae_sampling_loop(symbol: str, signal_type: str, entry_price: float,
                            audit_id: str, app, duration_sec: int = 120,
                            interval_sec: int = 10):
    """
    Muestreo de precio cada interval_sec durante la vida de la señal.
    Calcula MAE (Maximum Adverse Excursion) en pips y lo guarda en MongoDB.
    """
    from data_provider import get_provider
    from assets import get_asset_price
    from po_websocket import get_po_provider

    provider  = get_provider()
    worst_mae = 0.0
    samples   = []
    elapsed   = 0

    while elapsed < duration_sec:
        await asyncio.sleep(interval_sec)
        elapsed += interval_sec
        try:
            price = None
            # Prioridad 1: PO WebSocket (0 créditos API)
            po_prov = get_po_provider()
            if po_prov and po_prov.is_connected:
                price = po_prov.get_cached_price(symbol)
            # Prioridad 2: Twelve Data
            if price is None and provider and provider.is_configured:
                price = await provider.get_price_sample(symbol)
            # Prioridad 3: precio estático del asset
            if price is None:
                price = get_asset_price(symbol)
            samples.append(price)

            adverse = (entry_price - price) if signal_type == "CALL" else (price - entry_price)
            if adverse > worst_mae:
                worst_mae = adverse
        except Exception as e:
            logger.debug("MAE sample error %s: %s", symbol, e)

    pip_mult  = 100.0 if "JPY" in symbol else 10000.0
    mae_pips  = round(worst_mae * pip_mult, 1)
    mae_pct   = round(worst_mae / entry_price * 100, 4) if entry_price > 0 else 0.0

    logger.info("📐 MAE | %s %s | MAE=%.1f pips | %d muestras",
                signal_type, symbol, mae_pips, len(samples))

    if app.state.use_mongo and audit_id:
        from bson import ObjectId
        try:
            await app.state.db.trades.update_one(
                {"_id": ObjectId(audit_id)},
                {"$set": {
                    "max_adverse_excursion": mae_pips,
                    "mae_pct":               mae_pct,
                    "mae_samples":           len(samples),
                    "mae_price_path":        samples[-5:],
                }}
            )
        except Exception as e:
            logger.debug("MAE MongoDB update error: %s", e)


async def auto_register_observation(signal: dict, app,
                                    hit_timestamp: Optional[str] = None) -> Optional[str]:
    """
    Registra automáticamente toda señal en MongoDB como observación.
    Maximiza el historial estadístico sin requerir interacción del usuario.
    Retorna el audit_id generado.
    """
    from services.telegram_service import local_time, parse_naive_utc

    now        = datetime.utcnow()
    latency_ms = None
    if hit_timestamp:
        try:
            hit_dt     = parse_naive_utc(hit_timestamp)
            sig_dt     = parse_naive_utc(
                signal.get("timestamp", now.strftime("%Y-%m-%dT%H:%M:%S") + "Z")
            )
            latency_ms = max(0, int((hit_dt - sig_dt).total_seconds() * 1000))
        except Exception:
            latency_ms = None

    doc = {
        "signal_id":                   signal.get("id", ""),
        "symbol":                      signal.get("symbol", ""),
        "asset_name":                  signal.get("asset_name", ""),
        "signal_type":                 signal.get("type", ""),
        "result":                      "pending",
        "entry_price":                 signal.get("entry_price", signal.get("price", 0)),
        "close_price":                 None,
        "payout":                      signal.get("payout", 85),
        "quality_score":               signal.get("quality_score", 0),
        "cci":                         signal.get("cci", 0),
        "signal_timestamp":            signal.get("timestamp", now.strftime("%Y-%m-%dT%H:%M:%S") + "Z"),
        "created_at":                  now,
        "created_at_local":            local_time(now).strftime("%Y-%m-%dT%H:%M:%S") + " UTC-5",
        "session":                     signal.get("session", ""),
        "source":                      "auto_audit",
        "strategies":                  signal.get("strategies_agreeing", []),
        "market_volatility_at_entry":  signal.get("atr_pct", 0),
        "atr_raw":                     signal.get("atr", 0),
        "execution_latency_ms":        latency_ms,
        "max_adverse_excursion":       None,
        "mae_pct":                     None,
        "mae_samples":                 0,
    }

    try:
        if app.state.use_mongo:
            result   = await app.state.db.trades.insert_one(doc)
            audit_id = str(result.inserted_id)
        else:
            doc["id"] = f"audit_{int(now.timestamp()*1000)}"
            app.state.trades_store.append(doc)
            audit_id = doc["id"]

        logger.info("📋 Observación registrada | %s %s | score=%.2f | audit=%s",
                    signal.get("type"), signal.get("asset_name"),
                    signal.get("quality_score", 0), audit_id)
        return audit_id
    except Exception as e:
        logger.warning("⚠️  Error auto-registro: %s", e)
        return None


async def verify_signal_result(signal: dict, entry_time: datetime,
                                audit_id: str, app) -> Optional[str]:
    """
    Verifica el resultado consultando precio real (PO WS → Twelve Data).
    Actualiza trade document en MongoDB.
    Retorna "win" | "loss" | None.
    """
    from data_provider import get_provider
    from win_rate_cache import wr_cache_invalidate
    from circuit_breaker import cb_record_result
    from services.telegram_service import fmt_time

    symbol      = signal.get("symbol", "")
    entry_price = signal.get("entry_price", signal.get("price", 0))
    sig_type    = signal.get("type", "")

    if not entry_price or not symbol:
        logger.warning("⚠️  Auditoría abortada — datos incompletos")
        return None

    try:
        close_price = None
        confidence  = "high"

        try:
            from po_websocket import get_po_provider
            po = get_po_provider()
            if po and not po._kill_switch_active:
                po_price = po.get_latest_price(symbol, max_age_seconds=180)
                if po_price and po_price > 0:
                    close_price = po_price
                    logger.info("📡 Precio auditoría desde PO WS | %s = %.5f", symbol, close_price)
        except Exception:
            pass

        if close_price is None:
            provider = get_provider()
            if provider and provider.is_configured:
                close_price = await provider.get_price_for_audit(symbol)

        if close_price is None:
            confidence = "low"
            logger.warning("⚠️  Auditoría %s — sin precio real, omitido", symbol)
            return None

        pip_diff = round((close_price - entry_price) / entry_price * 10000, 1)
        pct_diff = round((close_price - entry_price) / entry_price * 100, 4)

        is_otc       = "OTC_" in symbol
        min_pip_move = 0.5 if is_otc else 0.1
        if abs(pip_diff) < min_pip_move:
            logger.info("⚖️  Auditoría %s — zona muerta (pip_diff=%.2f) → inconclusive",
                        symbol, pip_diff)
            return None

        outcome = ("win" if close_price > entry_price else "loss") if sig_type == "CALL" \
             else ("win" if close_price < entry_price else "loss")
        now     = datetime.utcnow()

        update_fields = {
            "result":            outcome,
            "close_price":       close_price,
            "pip_diff":          pip_diff,
            "pct_diff":          pct_diff,
            "verified_at":       now,
            "verified_at_local": fmt_time(now),
            "source":            "auto_audit_verified",
            "audit_confidence":  confidence,
        }

        if app.state.use_mongo and audit_id:
            from bson import ObjectId
            try:
                await app.state.db.trades.update_one(
                    {"_id": ObjectId(audit_id)},
                    {"$set": update_fields}
                )
            except Exception as e:
                logger.warning("⚠️  Error actualizando trade: %s", e)
        else:
            for t in app.state.trades_store:
                if t.get("id") == audit_id or t.get("signal_id") == signal.get("id", ""):
                    t.update(update_fields)
                    break

        signal_id = signal.get("id", "")
        if app.state.use_mongo and signal_id:
            from bson import ObjectId
            try:
                await app.state.db.signals.update_one(
                    {"_id": ObjectId(signal_id)},
                    {"$set": {
                        "result":      outcome,
                        "close_price": close_price,
                        "pip_diff":    pip_diff,
                        "pct_diff":    pct_diff,
                        "verified_at": now,
                    }}
                )
            except Exception:
                pass

        logger.info(
            "✅ Auditoría | %s %s | entrada=%.5f cierre=%.5f | %s | %+.1f pips [%s]",
            sig_type, symbol, entry_price, close_price,
            outcome.upper(), pip_diff, confidence
        )

        try:
            redis = getattr(app.state, "redis", None)
            await wr_cache_invalidate(redis, f"wr:{symbol}")
            await wr_cache_invalidate(redis, "wr:global")
            await wr_cache_invalidate(redis, "wr:stats")
        except Exception:
            pass

        cb_record_result(outcome, symbol)
        return outcome

    except Exception as e:
        logger.warning("⚠️  Error verificando resultado: %s", e)
        return None


async def verify_every_signal(signal_id: str, signal: dict, app) -> None:
    """
    Verificación universal — corre para TODAS las señales sin importar ejecución.
    Registra resultado teórico en la colección `signals` (no `trades`).
    """
    from data_provider import get_provider

    await asyncio.sleep(125)

    symbol      = signal.get("symbol", "")
    entry_price = float(signal.get("entry_price") or signal.get("price") or 0)
    sig_type    = signal.get("type", "")

    if not entry_price or not symbol or not signal_id:
        return

    try:
        close_price = None

        try:
            from po_websocket import get_po_provider
            po = get_po_provider()
            if po and not po._kill_switch_active:
                po_price = po.get_latest_price(symbol, max_age_seconds=180)
                if po_price and po_price > 0:
                    close_price = po_price
        except Exception:
            pass

        if close_price is None:
            provider = get_provider()
            if provider and provider.is_configured:
                close_price = await provider.get_price_for_audit(symbol)

        if close_price is None:
            logger.warning("⚠️  _verify_every_signal %s — sin precio real", symbol)
            return

        pip_diff = round((close_price - entry_price) / entry_price * 10000, 1)
        pct_diff = round((close_price - entry_price) / entry_price * 100, 4)

        is_otc       = "OTC_" in symbol
        min_pip_move = 0.5 if is_otc else 0.1
        if abs(pip_diff) < min_pip_move:
            return

        outcome = ("win" if close_price > entry_price else "loss") if sig_type == "CALL" \
             else ("win" if close_price < entry_price else "loss")
        now     = datetime.utcnow()

        update_fields: dict = {
            "theoretical_result": outcome,
            "close_price":        close_price,
            "pip_diff":           pip_diff,
            "pct_diff":           pct_diff,
            "verified_at":        now,
            "audit_confidence":   "high",
        }

        if app.state.use_mongo:
            from bson import ObjectId
            doc = await app.state.db.signals.find_one(
                {"_id": ObjectId(signal_id)}, {"execution_mode": 1}
            )
            current_mode = (doc or {}).get("execution_mode", "unexecuted")
            if current_mode == "unexecuted":
                update_fields["result"] = outcome

            await app.state.db.signals.update_one(
                {"_id": ObjectId(signal_id)},
                {"$set": update_fields},
            )
            logger.info("📊 Verificación universal | %s %s | %s | %+.1f pips | mode=%s",
                        sig_type, symbol, outcome.upper(), pip_diff, current_mode)
        else:
            for s in app.state.signals_store:
                if s.get("id") == signal_id:
                    s.update({k: v for k, v in update_fields.items() if k != "verified_at"})
                    s["verified_at"] = now.strftime("%Y-%m-%dT%H:%M:%S") + "Z"
                    if s.get("execution_mode") == "unexecuted":
                        s["result"] = outcome
                    break

    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.error("❌ Error en verify_every_signal %s: %s", signal_id, exc)


async def autonomous_audit(chat_id: str, msg_id: int, signal: dict,
                           entry_time: datetime, audit_id: Optional[str], app):
    """
    Auditoría autónoma del ciclo de vida de una señal.

    1. Espera 2 minutos de expiración
    2. Consulta precio real
    3. Determina WIN/LOSS
    4. Actualiza MongoDB
    5. Edita el mensaje de Telegram con resultado — sin intervención humana
    """
    from services.telegram_service import tg_edit_message, fmt_time, tg_api

    EXPIRY_SECONDS = 125

    await asyncio.sleep(EXPIRY_SECONDS)

    asset     = signal.get("asset_name", "")
    stype     = signal.get("type", "")
    close_now = datetime.utcnow()
    trade_key = str(msg_id)

    outcome = await verify_signal_result(signal, entry_time, audit_id, app)

    if outcome == "win":
        icon       = "✅"
        badge      = "[W]"
        color_text = "GANÓ"
    elif outcome == "loss":
        icon       = "❌"
        badge      = "[L]"
        color_text = "PERDIÓ"
    else:
        icon       = "⚠️"
        badge      = "[?]"
        color_text = "Sin datos"

    entry_price = signal.get("entry_price", signal.get("price", 0))

    result_text = (
        f"📊 <b>Auditoría completada: {badge}</b>\n\n"
        f"<b>{asset}</b> — {stype}\n"
        f"Entrada: <b>{fmt_time(entry_time)}</b>\n"
        f"Cierre:  <b>{fmt_time(close_now)}</b>\n\n"
        f"Score: {round(signal.get('quality_score', 0)*100)}% | "
        f"CCI: {signal.get('cci', 0):.0f}\n\n"
        f"{icon} <b>Señal {color_text}</b> — Datos guardados en MongoDB ✓\n\n"
        f"<i>¿El resultado es incorrecto? Corrígelo:</i>"
    )

    correction_keyboard = {
        "inline_keyboard": [[
            {"text": "✅ Fue WIN",  "callback_data": f"result:win:{trade_key}"},
            {"text": "❌ Fue LOSS", "callback_data": f"result:loss:{trade_key}"},
        ]]
    }

    await tg_edit_message(chat_id, msg_id, result_text, correction_keyboard)
    logger.info("📊 Auditoría completada | %s | %s %s | audit=%s",
                badge, stype, asset, audit_id)
