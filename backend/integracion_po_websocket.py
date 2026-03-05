"""
INSTRUCCIONES DE INTEGRACIÓN — WebSocket PO en server.py
==========================================================
Este archivo explica exactamente qué agregar y dónde en server.py
para activar el WebSocket de PocketOption.

NO reemplaza server.py completo — son bloques quirúrgicos.
"""

# ════════════════════════════════════════════════════════════
# BLOQUE 1 — Agregar al inicio de server.py (imports)
# Después de: from data_provider import ...
# ════════════════════════════════════════════════════════════

BLOQUE_IMPORTS = '''
# WebSocket PocketOption (datos reales OTC)
from po_websocket import (
    POWebSocketProvider, init_po_provider, get_po_provider,
    OTC_SYMBOL_MAP
)
'''

# ════════════════════════════════════════════════════════════
# BLOQUE 2 — En la función lifespan(), después de init_provider()
# ════════════════════════════════════════════════════════════

BLOQUE_LIFESPAN = '''
    # ── WebSocket PocketOption ────────────────────────────────────────────
    po_ssid = os.getenv("PO_SSID", "")
    if po_ssid:
        po_provider = init_po_provider(
            ssid    = po_ssid,
            user_id = int(os.getenv("PO_USER_ID", "0")),
        )
        app.state.po_provider = po_provider
        await po_provider.start()
        logger.info("🔌 WebSocket PO iniciado con SSID configurado")
    else:
        app.state.po_provider = None
        logger.warning("⚠️  PO_SSID no configurado — usando Twelve Data como fuente")
'''

# ════════════════════════════════════════════════════════════
# BLOQUE 3 — En _auto_scan_loop(), reemplazar get_indicators_batch()
# Buscar: indicators_map = await provider.get_indicators_batch(pairs_to_scan)
# Reemplazar con:
# ════════════════════════════════════════════════════════════

BLOQUE_SCAN_LOOP = '''
            # ── Fuente de datos: PO WebSocket (prioritario) o Twelve Data ────
            po_prov = getattr(app.state, "po_provider", None)
            use_po  = (po_prov and po_prov.is_connected and
                       not po_prov._kill_switch_active)

            if use_po:
                # Construye IndicatorSet desde datos reales de PO
                indicators_map = {}
                for symbol in pairs_to_scan:
                    if po_prov.is_ready(symbol):
                        candles_raw = po_prov.get_candles(symbol)
                        if candles_raw:
                            from data_provider import CandleData, IndicatorSet
                            candles = [
                                CandleData(
                                    open  = c["open"],
                                    high  = c["high"],
                                    low   = c["low"],
                                    close = c["close"],
                                    time  = c["time"],
                                )
                                for c in candles_raw
                            ]
                            ind = IndicatorSet()
                            ind.compute(candles)
                            ind.is_real  = True
                            ind.source   = "po_websocket"
                            indicators_map[symbol] = ind
                logger.info("⚡ Datos PO WebSocket | %d/%d pares listos",
                            len(indicators_map), len(pairs_to_scan))
            else:
                # Fallback a Twelve Data
                indicators_map = await provider.get_indicators_batch(pairs_to_scan)
                if po_prov and po_prov._kill_switch_active:
                    logger.warning("🔴 [ALERTA: EVASIÓN ACTIVADA] — usando Twelve Data")
'''

# ════════════════════════════════════════════════════════════
# BLOQUE 4 — Nuevo endpoint para el dashboard
# Agregar después de /api/data-provider/status
# ════════════════════════════════════════════════════════════

BLOQUE_ENDPOINT = '''
@app.get("/api/po-websocket/status")
async def get_po_websocket_status(request: Request):
    """Estado del WebSocket de PocketOption para el dashboard."""
    po_prov = getattr(request.app.state, "po_provider", None)
    if not po_prov:
        return {
            "enabled":       False,
            "status":        "not_configured",
            "message":       "Configura PO_SSID en .env para activar",
            "kill_switch":   False,
            "source":        "twelve_data",
        }
    status = po_prov.get_status()
    status["alert"] = po_prov._kill_switch_active  # para dashboard rojo parpadeante
    return status


@app.post("/api/po-websocket/reset")
async def reset_po_websocket(request: Request):
    """Resetea el kill-switch y reconecta."""
    po_prov = getattr(request.app.state, "po_provider", None)
    if not po_prov:
        raise HTTPException(status_code=404, detail="WebSocket PO no configurado")
    po_prov.reset_kill_switch()
    await po_prov.start()
    return {"success": True, "message": "WebSocket PO reconectando..."}
'''

# ════════════════════════════════════════════════════════════
# BLOQUE 5 — Variables a agregar al .env
# ════════════════════════════════════════════════════════════

ENV_VARS = """
# PocketOption WebSocket (ejecuta po_session_helper.py para obtener el SSID)
PO_SSID=
PO_USER_ID=124946260
"""

if __name__ == "__main__":
    print("=" * 60)
    print("INTEGRACIÓN WEBSOCKET PO — Resumen de cambios")
    print("=" * 60)
    print("\n1. Copia po_websocket.py → backend/")
    print("2. Copia po_session_helper.py → backend/")
    print("3. Ejecuta: python po_session_helper.py")
    print("4. Aplica los 4 bloques de código en server.py")
    print("5. Agrega al .env:")
    print(ENV_VARS)
    print("6. Reinicia el bot")
    print("\nEl bot detectará PO_SSID y usará WebSocket automáticamente.")
    print("Si PO bloquea → Kill-Switch → fallback a Twelve Data")
