 # CONTEXT.md — Estado actual del proyecto
## Última actualización: 19/03/2026 — 03:54 UTC-4

---

## PROTOCOLO CURSOR
- .cursorrules v2 integrado ✅
- Inicio de sesión obligatorio: usuario declara modelo
- Estados de tarea: EN_CURSO → PUSHEADO → PENDIENTE_VERIFICACION → RESUELTO
- mem_stats eliminado de las reglas
- Doble confirmación activa para módulos críticos

---

## BOT — Estado en producción
- WebSocket PO: conectado a events-po.com ✅
- Sesión activa: Madrugada (00:00-02:00) | 20/20 pares
- Última señal: CALL OTC_EURCAD | score=0.62 | conf=0.68
- Telegram: operativo ✅
- Auditoría autónoma: operativa ✅
- Auto-exec: bloqueado — WR 50.0% < umbral 55.0% (base: 20 ops)

---

## PENDIENTES ACTIVOS
✅ Fix auditoría — RESUELTO
✅ Deploy VPS — RESUELTO
✅ .cursorrules v2 — RESUELTO
✅ CONTEXT.md — RESUELTO
✅ Release Please desactivado — RESUELTO
✅ Alerta PO_SSID expiración — RESUELTO
✅ Sincronizar master→main — RESUELTO (ya estaba OK)
✅ Alerta kill-switch >30 min — RESUELTO
🟢 AUTO_EXECUTE — acumulando ops (WR 50.0%, umbral 55%)

---

## COMMITS DE ESTA SESIÓN
- a79bf30: fix audit_service.py
- 56f464f: protocolo v2 + CONTEXT.md
- c2ff582: alerta PO_SSID
- 662970d: alerta kill-switch >30 min

---

## COMANDOS VPS DE REFERENCIA
cd /opt/trading-bot && git pull origin main
docker-compose -f docker-compose.production.yml up -d api
docker logs trading-bot-api --tail 50

---

## CÓMO RETOMAR
Arrastra este archivo al chat y escribe:
Lee CONTEXT.md y continúa desde donde lo dejamos.