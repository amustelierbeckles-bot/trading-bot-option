# CONTEXT.md — Estado actual del proyecto
## Última actualización: 24/03/2026

---

## Autenticación PocketOption WebSocket
- El mensaje `42["auth", {"session": SSID, "isDemo": 0|1}]` se envía tras el handshake.
- Solo requiere SSID válido — `PO_USER_ID` y `PO_SECRET` no son necesarios para el feed de precios.
- Variables en `.env.production`: `PO_SSID` (obligatorio), `PO_USER_ID` y `PO_SECRET` (opcionales).
- Si el SSID expira → reconexión en loop sin ticks → renovar `ci_session` desde DevTools PO.

---

## PROXY PO — DESPLEGADO (resuelto operativamente)
- **Causa raíz:** IP del VPS (datacenter) → PocketOption no enviaba ticks aunque el WebSocket conectaba y suscribía 20 pares.
- **Solución activa:** `PO_PROXY_URL=socks5://user:pass@host:port` (proxy residencial, p. ej. Webshare) + `python-socks[asyncio]` en la imagen Docker.
- **Código:** `backend/po_websocket.py` — `websockets.connect(..., proxy=...)`; `backend/requirements.txt` + `backend/Dockerfile` (pip explícito de `python-socks`).
- **Último push relevante:** `main` incluye deps Docker y chequeo SOCKS (p. ej. commit `aee618b` o posterior).
- **Verificado en VPS:** logs con `modo=REAL`, `Conectando vía proxy → …`, `POWebSocket conectado a events-po.com`, handshake Socket.IO, suscripción a 20 pares.

---

## Rate limit Twelve Data
- Plan gratuito: **800 req/día**, ~8 req/min (según Twelve Data).
- **`MAX_TD_FALLBACK_PER_CYCLE = 5`** en `backend/auto_exec.py` dentro de `_auto_scan_loop`.
- **Razón:** limitar peticiones cuando PO no envía ticks y el scan usa fallback TD en lugar del buffer en vivo.
- **Rotación round-robin** (`_td_fallback_queue`): los pares pendientes rotan cada ciclo; con 20 pares y tope 5, en **4 ciclos** como máximo se ha intentado cubrir los 20 (salvo que `pending` cambie y se reinicie la cola).
- **Cambiar** el tope solo si se sube de plan TD o se ajusta el presupuesto de req/día.

---

## PRÓXIMA VERIFICACIÓN (ventana operativa)
- Confirmar **ticks de precio** en logs cuando el bot esté **dentro de ventana** (mañana 09:30–12:00 o madrugada 00:00–02:00 hora local DST).
- Fuera de ventana: `auto_exec` puede mostrar *Fuera de ventana / Bot pausado* — el WS puede seguir conectado.

---

## DEPLOY VPS (referencia rápida)
```bash
cd /opt/trading-bot && git pull origin main
docker build --no-cache -t trading-bot-api-img:latest -f backend/Dockerfile backend/
docker stop trading-bot-api && docker rm trading-bot-api
docker-compose -f docker-compose.production.yml up -d api
docker logs trading-bot-api --tail=50
```
Tras cambiar solo `.env`: a veces basta recrear el contenedor; si cambian dependencias, **rebuild** como arriba.

---

## PENDIENTES
- 🟡 **Ticks en producción:** verificar en ventana 09:30 si aparece "tick binary" en logs (con LOG_LEVEL=DEBUG). Si aparecen "unknown event", revisar. Revertir a WARNING luego.
- 🟡 **Migración datos históricos:** ejecutar `scripts/migrate_signals_to_trades.js` en VPS UNA VEZ con `mongosh`. Mueve trades auto-exec almacenados erróneamente en `db.signals` hacia `db.trades`. Script idempotente.
- 🟡 **PRÓXIMA SESIÓN 1:** Alerta Telegram cuando PO lleva N ciclos sin enviar ticks.
- 🟡 **PRÓXIMA SESIÓN 2:** Corregir lógica invertida en MACDStoch.

---

## CÓMO RETOMAR
Arrastra este archivo al chat y escribe:
> Lee CONTEXT.md y continúa desde donde lo dejamos.
