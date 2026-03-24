"""
Auto-ejecución y loop de escaneo automático de señales.

  _auto_execute_trade : ejecuta trade en PocketOption cuando AUTO_EXECUTE=true
  _auto_scan_loop     : motor de escaneo paralelo v2.3
"""
import asyncio
import logging
import os
from collections import deque
from datetime import datetime, timedelta
from typing import Optional

_last_wr_blocked: bool = False

# Rotación round-robin para fallback Twelve Data cuando PO no está listo (ver CONTEXT.md).
_td_fallback_queue: deque = deque()

logger = logging.getLogger(__name__)


async def _auto_execute_trade(doc: dict, app, quality_score: float):
    """
    Ejecuta automáticamente un trade en PocketOption Demo.

    Gates de seguridad (todos deben cumplirse):
    - AUTO_EXECUTE=true en .env
    - Circuit Breaker no activo
    - WebSocket PO conectado y autenticado
    - Win Rate de últimas ops >= AUTO_EXECUTE_MIN_WR (si hay suficientes datos)

    Variables: AUTO_EXECUTE_MIN_WR, AUTO_EXECUTE_MIN_OPS, AUTO_EXECUTE_AMOUNT,
    AUTO_EXECUTE_MODE (demo|real). Si AUTO_EXECUTE_MODE=demo, place_trade fuerza
    cuenta demo y el WR solo cuenta ops con po_is_demo=true (no mezcla con REAL).
    """
    from circuit_breaker import cb_is_blocked
    from services.audit_service import autonomous_audit
    from services.telegram_service import tg_api

    global _last_wr_blocked
    try:
        if cb_is_blocked():
            logger.warning("🛑 Auto-exec bloqueado — Circuit Breaker activo")
            return

        auto_min_wr  = float(os.getenv("AUTO_EXECUTE_MIN_WR", "55.0"))
        auto_min_ops = int(os.getenv("AUTO_EXECUTE_MIN_OPS", "20"))
        auto_mode    = os.getenv("AUTO_EXECUTE_MODE", "demo").lower()

        wr_filter = {
            "result":         {"$in": ["W", "L", "win", "loss"]},
            "execution_mode": "auto",
        }
        if auto_mode == "demo":
            wr_filter["po_is_demo"] = True
        elif auto_mode == "real":
            wr_filter["po_is_demo"] = False

        if app.state.use_mongo:
            cursor = app.state.db.signals.find(wr_filter).sort("created_at", -1).limit(auto_min_ops)
            recent = await cursor.to_list(auto_min_ops)
        else:
            def _wr_match(t: dict) -> bool:
                if t.get("result") not in ("W", "L", "win", "loss"):
                    return False
                if t.get("execution_mode") != "auto":
                    return False
                if auto_mode == "demo":
                    return t.get("po_is_demo") is True
                if auto_mode == "real":
                    return t.get("po_is_demo") is False
                return True

            recent = [t for t in app.state.trades_store if _wr_match(t)][-auto_min_ops:]

        if len(recent) >= auto_min_ops:
            wins      = sum(1 for t in recent if t.get("result") in ("W", "win"))
            wr_recent = wins / len(recent) * 100
            if wr_recent < auto_min_wr:
                logger.warning(
                    "🛑 Auto-exec bloqueado — WR %.1f%% < umbral %.1f%% (%d ops)",
                    wr_recent, auto_min_wr, len(recent)
                )
                if not _last_wr_blocked:
                    _last_wr_blocked = True
                    from services.telegram_service import send_telegram
                    asyncio.create_task(send_telegram(
                        f"🟡 AUTO-EXECUTE bloqueado\n"
                        f"WR reciente: {wr_recent:.1f}% < umbral {auto_min_wr:.1f}%\n"
                        f"El bot pausó la ejecución automática."
                    ))
                return
            else:
                if _last_wr_blocked:
                    _last_wr_blocked = False
                    from services.telegram_service import send_telegram
                    asyncio.create_task(send_telegram(
                        f"🟢 AUTO-EXECUTE DESBLOQUEADO\n"
                        f"WR reciente: {wr_recent:.1f}% ≥ umbral {auto_min_wr:.1f}%\n"
                        f"El bot comenzará a ejecutar trades automáticamente."
                    ))
        else:
            logger.info(
                "📊 Auto-exec recolección — %d/%d ops verificadas",
                len(recent), auto_min_ops
            )

        from po_websocket import get_po_provider
        po = get_po_provider()
        if not po or not po.is_connected:
            logger.warning("🛑 Auto-exec bloqueado — PO WebSocket no conectado")
            return

        symbol    = doc.get("symbol", "")
        direction = doc.get("type", "").lower()
        amount    = float(os.getenv("AUTO_EXECUTE_AMOUNT", "100"))
        # Guard: AUTO_EXECUTE_MODE=demo → siempre orden demo en PO (no dinero real).
        if auto_mode == "demo":
            is_demo = True
        else:
            is_demo = os.getenv("ACCOUNT_MODE", "demo").lower() == "demo"

        result = await po.place_trade(
            symbol         = symbol,
            direction      = direction,
            amount         = amount,
            expiry_seconds = 120,
            is_demo        = is_demo,
        )

        now    = datetime.utcnow()
        sig_id = doc.get("id", "")
        update = {
            "execution_mode":    "auto",
            "executed_at":       now,
            "executed_amount":   amount,
            "po_order_id":       result.get("order_id"),
            "po_is_demo":        is_demo,
            "auto_execute_mode": auto_mode,
        }

        if app.state.use_mongo and sig_id:
            from bson import ObjectId
            try:
                await app.state.db.signals.update_one(
                    {"_id": ObjectId(sig_id)},
                    {"$set": update},
                )
            except Exception:
                pass
        else:
            for s in app.state.signals_store:
                if s.get("id") == sig_id:
                    s.update(update)
                    s["executed_at"] = now.strftime("%Y-%m-%dT%H:%M:%S") + "Z"
                    break

        logger.info(
            "🤖 Auto-exec | %s %s $%.0f | order=%s | status=%s",
            direction.upper(), symbol, amount,
            result.get("order_id", "?")[:16], result.get("status", "?")
        )

        audit_id = None
        if app and app.state.use_mongo:
            try:
                trade_doc = {
                    "symbol":            symbol,
                    "asset_name":        doc.get("asset_name", symbol),
                    "type":              direction.upper(),
                    "entry_price":       doc.get("entry_price", doc.get("price", 0)),
                    "quality_score":     quality_score,
                    "execution_mode":    "auto",
                    "amount":            amount,
                    "po_order_id":       result.get("order_id"),
                    "po_status":         result.get("status"),
                    "audit_confidence":  "high",
                    "result":            None,
                    "created_at":        now,
                    "session":           doc.get("session", ""),
                    "strategies":        doc.get("strategies_agreeing", []),
                    "po_is_demo":        is_demo,
                    "auto_execute_mode": auto_mode,
                }
                ins      = await app.state.db.signals.insert_one(trade_doc)
                audit_id = str(ins.inserted_id)
                logger.info("📝 Trade auto-exec registrado | audit_id=%s", audit_id)
            except Exception as e:
                logger.warning("⚠️  No se pudo registrar auto-exec: %s", e)

        chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        token   = os.getenv("TELEGRAM_BOT_TOKEN", "")
        demo_tag = "🏷 <b>DEMO</b> — cuenta de práctica PO\n" if is_demo else ""
        auto_msg_text = (
            f"🤖 <b>AUTO-EXEC</b>\n"
            f"{demo_tag}\n"
            f"Par: <b>{doc.get('asset_name', symbol)}</b>\n"
            f"Dirección: <b>{direction.upper()}</b>\n"
            f"Monto: <b>${amount:.0f}</b>\n"
            f"Score: <b>{quality_score*100:.0f}%</b>\n"
            f"Orden: <code>{result.get('order_id','?')[:12]}</code>\n"
            f"Estado: <code>{result.get('status','?')}</code>\n\n"
            f"⏰ Verificando resultado en 2 minutos automáticamente..."
        )
        if token and chat_id:
            tg_result = await tg_api("sendMessage", {
                "chat_id":    chat_id,
                "text":       auto_msg_text,
                "parse_mode": "HTML",
            })
            auto_msg_id = tg_result.get("result", {}).get("message_id")

            if audit_id and auto_msg_id and app:
                asyncio.create_task(autonomous_audit(
                    chat_id, auto_msg_id, doc, now, audit_id, app
                ))
                logger.info("🔄 Auditoría autónoma lanzada para auto-exec | %s %s",
                            direction.upper(), symbol)

    except Exception as e:
        logger.error("❌ Error en auto-exec: %s", e)


async def _auto_scan_loop(app):
    """
    Motor de escaneo PARALELO v2.3 — asyncio.gather() para todos los pares.

    Optimización de créditos:
      - Máximo 8 pares por sesión
      - Cache TTL 600s
      - Solo emite señales con datos reales (no simulados)
    """
    from data_provider import get_provider, get_simulated_indicators
    from market_session import get_market_session, ALL_20_PAIRS
    from calibration import (get_dynamic_threshold, set_dynamic_threshold,
                              compute_optimal_threshold, _MIN_TRADES_TO_CALIBRATE)
    from scoring import quality_score as calc_quality_score
    from assets import get_asset_name, get_asset_price
    from circuit_breaker import cb_is_blocked, _cb_state
    from win_rate_cache import wr_cache_get, wr_cache_invalidate, hour_bucket, day_bucket
    from antifragile import check_correlation_lock
    from services.telegram_service import send_telegram, send_pre_alert_telegram, send_signal_telegram
    from services.audit_service import verify_every_signal

    INTERVAL         = 120
    # Máximo de pares a rellenar vía Twelve Data por ciclo cuando PO no está listo
    # (caché 300s + este tope reducen req/día frente al límite del plan).
    MAX_TD_FALLBACK_PER_CYCLE = 5
    MIN_CONFIDENCE   = 0.68
    MIN_QUALITY_BASE = 0.55
    MAX_PER_CYCLE    = 2
    COOLDOWN_SECONDS = 240
    MAX_STORE        = 20

    cooldown_map: dict = {}

    await asyncio.sleep(5)
    logger.info("🚀 Auto-scan PARALELO v2.3 iniciado — gather() · %ds ciclo", INTERVAL)

    calibration_cycle = 0

    while True:
        cycle_start = datetime.utcnow()
        try:
            ensemble  = app.state.ensemble
            store     = app.state.signals_store
            use_mongo = app.state.use_mongo
            db        = app.state.db
            now       = cycle_start

            calibration_cycle += 1
            if calibration_cycle % 10 == 0:
                try:
                    if use_mongo:
                        cursor     = db.trades.find({"audit_confidence": "high"})
                        all_trades = await cursor.to_list(2000)
                        for t in all_trades:
                            t["id"] = str(t.pop("_id", ""))
                            if isinstance(t.get("created_at"), datetime):
                                t["created_at"] = t["created_at"].strftime("%Y-%m-%dT%H:%M:%S") + "Z"
                    else:
                        all_trades = [t for t in app.state.trades_store
                                      if t.get("audit_confidence") == "high"]

                    if len(all_trades) >= _MIN_TRADES_TO_CALIBRATE:
                        cal = compute_optimal_threshold(all_trades)
                        if cal["calibrated"]:
                            set_dynamic_threshold(cal["optimal_threshold"])
                            logger.info("🎯 Auto-calibración | Umbral → %.2f | %s",
                                        get_dynamic_threshold(), cal["recommendation"])
                except Exception as cal_err:
                    logger.warning("⚠️  Error en auto-calibración: %s", cal_err)

            effective_base = get_dynamic_threshold()
            try:
                if use_mongo:
                    cursor_h = db.trades.find({"audit_confidence": "high"})
                    all_t_h  = await cursor_h.to_list(1000)
                    for t in all_t_h:
                        if isinstance(t.get("created_at"), datetime):
                            t["created_at"] = t["created_at"].strftime("%Y-%m-%dT%H:%M:%S") + "Z"
                else:
                    all_t_h = [t for t in app.state.trades_store
                               if t.get("audit_confidence") == "high"]

                from services.telegram_service import parse_naive_utc
                hour_trades = [
                    t for t in all_t_h
                    if parse_naive_utc(
                        t.get("signal_timestamp") or t.get("created_at", "")
                    ).hour == now.hour
                ]
                if len(hour_trades) >= 10:
                    hw      = sum(1 for t in hour_trades if t.get("result") == "win")
                    hour_wr = hw / len(hour_trades)
                    if hour_wr >= 0.65:
                        effective_base = max(0.45, effective_base - 0.05)
                    elif hour_wr < 0.45:
                        effective_base = min(0.80, effective_base + 0.07)
            except Exception:
                pass

            session       = get_market_session(now.hour, now.minute)
            QUALITY_PAIRS = session["pairs"] if session["pairs"] else ALL_20_PAIRS
            MIN_QUALITY   = effective_base - session["quality_boost"]

            if not session["active"]:
                logger.info("🌙 [%s] %s — sin escaneo. Próximo ciclo en %ds.",
                            session["display"], session["description"], INTERVAL)
                await asyncio.sleep(INTERVAL)
                continue

            pairs_to_scan = []
            for symbol in QUALITY_PAIRS:
                last_entry = cooldown_map.get(symbol)
                if last_entry:
                    last_time, last_score = last_entry
                    adaptive_cd = COOLDOWN_SECONDS if last_score < 0.65 else 120
                    if (now - last_time).total_seconds() < adaptive_cd:
                        continue
                lock = check_correlation_lock(symbol)
                if lock["locked"]:
                    logger.debug("🔴 %s bloqueado por correlación", symbol)
                    continue
                pairs_to_scan.append(symbol)

            if not pairs_to_scan:
                logger.info("⏳ Todos los pares en cooldown — próximo ciclo en %ds", INTERVAL)
                await asyncio.sleep(INTERVAL)
                continue

            fetch_start = datetime.utcnow()
            provider    = get_provider()
            po_prov     = getattr(app.state, "po_provider", None)

            # ── Bootstrap único por sesión ────────────────────────────────────
            # Siembra los buffers de PO con 35 velas históricas de TwelveData
            # UNA sola vez por par. Después, el buffer se mantiene vivo con ticks
            # y nunca vuelve a necesitar TwelveData para indicadores.
            # Máximo MAX_TD_FALLBACK_PER_CYCLE pares por ciclo: el plan gratuito de TD
            # limita ~8 req/min; disparar 20 bootstrap en segundos agotaba el cupo (429).
            if po_prov and provider and provider.is_configured:
                from data_provider import CandleData as _CD
                needs_boot = [
                    sym for sym in pairs_to_scan
                    if not po_prov.is_ready(sym)
                    and not getattr(app.state, "_po_bootstrapped", set()).issuperset({sym})
                ][:MAX_TD_FALLBACK_PER_CYCLE]
                if needs_boot:
                    if not hasattr(app.state, "_po_bootstrapped"):
                        app.state._po_bootstrapped = set()
                    logger.info("🌱 Bootstrap PO buffer | %d pares sin datos", len(needs_boot))
                    boot_sem = asyncio.Semaphore(2)

                    async def _boot_one(sym: str):
                        async with boot_sem:
                            await asyncio.sleep(0.5)
                            ind = await provider.get_indicators(sym)
                            if ind and ind.candles:
                                added = po_prov.seed_from_candles(sym, ind.candles)
                                app.state._po_bootstrapped.add(sym)
                                logger.info("🌱 %s sembrado con %d velas", sym, added)

                    boot_tasks = [asyncio.create_task(_boot_one(s)) for s in needs_boot]
                    await asyncio.gather(*boot_tasks, return_exceptions=True)

            # ── Fuente de indicadores: PO WebSocket (sin depender de is_connected)
            # Los buffers persisten entre reconexiones — si hay datos, se usan.
            indicators_map: dict = {}
            po_ready = 0

            if po_prov and not po_prov._kill_switch_active:
                from data_provider import CandleData, IndicatorSet
                for sym in pairs_to_scan:
                    if not po_prov.is_ready(sym):
                        continue
                    candles_raw = po_prov.get_candles(sym)
                    if not candles_raw:
                        continue
                    candles = [
                        CandleData(
                            time  = datetime.utcfromtimestamp(c["time"]).strftime("%Y-%m-%d %H:%M:%S"),
                            open  = c["open"],
                            high  = c["high"],
                            low   = c["low"],
                            close = c["close"],
                        )
                        for c in candles_raw
                    ]
                    ind = IndicatorSet()
                    ind.compute(candles)
                    ind.last_candle_time = candles[-1].time if candles else ""
                    indicators_map[sym]  = ind
                    po_ready += 1

                # PO conectado pero par sin tick reciente (is_ready False): Twelve Data
                # real con caché (TTL típico 300s). Máximo MAX_TD_FALLBACK_PER_CYCLE pares
                # por ciclo en paralelo — reduce req/día y latencia vs. 20× await en serie.
                if provider and provider.is_configured:
                    global _td_fallback_queue
                    pending = [s for s in pairs_to_scan if s not in indicators_map]
                    pairs_for_td: list = []
                    if pending:
                        if (not _td_fallback_queue
                                or set(_td_fallback_queue) != set(pending)):
                            _td_fallback_queue = deque(pending)
                        n_pick = min(MAX_TD_FALLBACK_PER_CYCLE, len(_td_fallback_queue))
                        for _ in range(n_pick):
                            pairs_for_td.append(_td_fallback_queue[0])
                            _td_fallback_queue.rotate(-1)
                    if pairs_for_td:
                        results = await asyncio.gather(
                            *[provider.get_indicators(s) for s in pairs_for_td],
                            return_exceptions=True,
                        )
                        for sym, ind in zip(pairs_for_td, results):
                            if isinstance(ind, Exception):
                                continue
                            if ind is None:
                                continue
                            indicators_map[sym] = ind

            fetch_elapsed = (datetime.utcnow() - fetch_start).total_seconds()
            td_fallback   = len(pairs_to_scan) - po_ready

            if po_prov and not po_prov._kill_switch_active:
                logger.info(
                    "⚡ PO WebSocket %d/%d pares | TwelveData fallback %d pares | %.1fs",
                    po_ready, len(pairs_to_scan), td_fallback, fetch_elapsed,
                )
            else:
                if provider and provider.is_configured:
                    indicators_map = await provider.get_indicators_batch(pairs_to_scan)
                else:
                    indicators_map = {sym: get_simulated_indicators(sym) for sym in pairs_to_scan}
                logger.info("⚡ Fetch paralelo %.1fs para %d pares", fetch_elapsed, len(pairs_to_scan))

            real_count      = sum(1 for s in pairs_to_scan if indicators_map.get(s) and indicators_map[s].is_real)
            simulated_count = len(pairs_to_scan) - real_count

            if simulated_count > 0 and real_count == 0:
                now_ts       = datetime.utcnow()
                last_sim_warn = getattr(app.state, "_last_sim_warn", None)
                if not last_sim_warn or (now_ts - last_sim_warn).total_seconds() > 1800:
                    app.state._last_sim_warn = now_ts
                    logger.warning("⚠️  MODO SIMULADO ACTIVO — API sin créditos. Señales suspendidas.")
                    asyncio.create_task(send_telegram(
                        "⚠️ <b>ATENCIÓN: Bot en modo simulado</b>\n\n"
                        "Los créditos de Twelve Data se han agotado.\n"
                        "🚫 <b>Las señales están SUSPENDIDAS</b> hasta que se renueven.\n\n"
                        "<i>No ejecutes operaciones manualmente.</i>"
                    ))
            elif real_count > 0:
                last_sim_warn = getattr(app.state, "_last_sim_warn", None)
                if last_sim_warn:
                    app.state._last_sim_warn = None
                    asyncio.create_task(send_telegram(
                        f"✅ <b>API real activa</b> — {real_count}/{len(pairs_to_scan)} pares. "
                        "Las señales han sido reanudadas."
                    ))

            candidates = []
            for symbol in pairs_to_scan:
                ind = indicators_map.get(symbol) or get_simulated_indicators(symbol)

                if not ind.is_real:
                    logger.debug("⏭  %s omitido — datos simulados", symbol)
                    continue

                if ind.is_real and ind.atr_pct > 0:
                    atr_threshold = 0.015 if session["name"] in ("london", "newyork") else 0.010
                    if ind.atr_pct < atr_threshold:
                        continue

                signal = ensemble.get_consensus_signal(ind)
                if not signal:
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
                        asyncio.create_task(send_pre_alert_telegram(pre_doc))
                    else:
                        app.state.pre_alerts_store.pop(symbol, None)
                    continue

                if signal["confidence"] < MIN_CONFIDENCE:
                    continue

                score = calc_quality_score(signal, symbol, ind)

                pair_min_quality = MIN_QUALITY
                try:
                    redis       = getattr(app.state, "redis", None)
                    cached_stats = await wr_cache_get(redis, "wr:stats:1h")
                    if cached_stats:
                        pair_data = cached_stats.get("by_pair", {}).get(symbol, {})
                        if pair_data.get("degraded", False):
                            pair_min_quality = MIN_QUALITY + 0.10
                except Exception:
                    pass

                if score < pair_min_quality:
                    continue

                candidates.append((score, symbol, signal, ind))

            candidates.sort(key=lambda x: x[0], reverse=True)
            top = candidates[:MAX_PER_CYCLE]

            cycle_elapsed = (datetime.utcnow() - cycle_start).total_seconds()

            for score, symbol, signal, ind in top:
                price     = ind.price if (ind and ind.is_real) else get_asset_price(symbol)
                emit_time = datetime.utcnow()
                ts        = emit_time.strftime("%Y-%m-%dT%H:%M:%S") + "Z"

                data_freshness_ms = None
                if ind and ind.is_real and ind.last_candle_time:
                    try:
                        candle_dt         = datetime.strptime(ind.last_candle_time, "%Y-%m-%d %H:%M:%S")
                        data_freshness_ms = int((emit_time - candle_dt).total_seconds() * 1000)
                    except Exception:
                        pass

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
                    "hour_bucket":         hour_bucket(emit_time),
                    "day_bucket":          day_bucket(emit_time),
                    "data_source":         "real" if (ind and ind.is_real) else "simulated",
                    "audit_confidence":    "high" if (ind and ind.is_real) else "low",
                    "data_freshness_ms":   data_freshness_ms,
                    "scan_elapsed_ms":     round(cycle_elapsed * 1000),
                    "fetch_elapsed_ms":    round(fetch_elapsed * 1000),
                    "execution_mode":      "unexecuted",
                    "executed_at":         None,
                    "executed_amount":     None,
                    "close_price":         None,
                    "pip_diff":            None,
                    "pct_diff":            None,
                    "result":              None,
                    "theoretical_result":  None,
                    "po_order_id":         None,
                }

                if use_mongo:
                    db_doc = {**doc, "created_at": emit_time}
                    db_doc.pop("id", None)
                    result_ins = await db.signals.insert_one(db_doc)
                    doc["id"]  = str(result_ins.inserted_id)
                    asyncio.create_task(verify_every_signal(doc["id"], doc, app))
                else:
                    cutoff = emit_time - timedelta(minutes=5)
                    store[:] = [
                        s for s in store
                        if _parse_ts(s["created_at"]) >= cutoff
                    ]
                    if len(store) >= MAX_STORE:
                        store.pop(0)
                    store.append(doc)

                cooldown_map[symbol] = (emit_time, score)
                app.state.pre_alerts_store.pop(symbol, None)
                logger.info(
                    "✅ Señal | %s %s | score=%.2f | conf=%.2f | ATR%%=%.4f | scan=%.1fs",
                    signal["type"], symbol, score, signal["confidence"],
                    ind.atr_pct if ind else 0, cycle_elapsed,
                )

                if cb_is_blocked():
                    logger.warning("🛑 CB activo — señal %s %s bloqueada", signal["type"], symbol)
                else:
                    only_fire = os.getenv("TELEGRAM_ONLY_FIRE", "false").lower() == "true"
                    is_fire   = score >= 0.75 or len(signal.get("strategies_agreeing", [])) >= 3
                    if not only_fire or is_fire:
                        asyncio.create_task(send_signal_telegram(doc, app))

                    auto_execute = os.getenv("AUTO_EXECUTE", "false").lower() == "true"
                    if auto_execute:
                        asyncio.create_task(_auto_execute_trade(doc, app, score))

            if not top:
                logger.info("🔍 Ciclo sin señales (umbral %.2f) | scan=%.1fs",
                            MIN_QUALITY, cycle_elapsed)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("❌ Error en auto-scan: %s", e)

        elapsed = (datetime.utcnow() - cycle_start).total_seconds()
        await asyncio.sleep(max(5.0, INTERVAL - elapsed))


def _parse_ts(ts: str) -> datetime:
    """Parse de timestamp ISO UTC para comparaciones en el store in-memory."""
    try:
        return datetime.strptime(ts.replace("Z", ""), "%Y-%m-%dT%H:%M:%S")
    except Exception:
        return datetime.utcnow()
