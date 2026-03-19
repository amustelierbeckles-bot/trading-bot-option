# CONTEXT.md — Estado actual del proyecto
## Última actualización: 19/03/2026 — 03:00 UTC-4

---

## protocolo cursor
- .cursorrules v2 integrado ✅
- Inicio de sesión obligatorio: usuario declara modelo
- Estados de tarea: EN_CURSO → PUSHEADO → PENDIENTE_VERIFICACION → RESUELTO
- mem_stats eliminado de las reglas
- Doble confirmación activa para módulos críticos
- Autoevaluación del agente integrada como referencia

---

## Deploy en curso
- Fix: audit_service.py — is_connected → not _kill_switch_active
- Commit: a79bf30 pusheado a GitHub ✅
- Rebuild en VPS ejecutado ✅
- Verificación en logs confirmada ✅ — audit_id registrándose correctamente
- Estado: RESUELTO

---

## Bot — Estado en producción
- WebSocket PO: conectado a events-po.com ✅
- Sesión activa: Madrugada (00:00-02:00) | 20/20 pares
- Última señal: CALL OTC_EURCAD | score=0.62 | conf=0.68
- Telegram: operativo ✅
- Auditoría autónoma: operativa ✅
- Auto-exec: bloqueado — WR 50.0% < umbral 55.0% (base: 20 ops)

---

## Pendientes activos
✅ Fix auditoría — RESUELTO (confirmado en logs)
✅ Deploy VPS — RESUELTO
✅ .cursorrules v2 — RESUELTO
🔴 Alerta PO_SSID por expiración — sin implementar
🟡 Sincronizar master→main en VPS
🟡 Alerta Telegram kill-switch >30 min
🟢 AUTO_EXECUTE — acumulando ops (WR actual 50.0%, umbral 55%)

---

## Comandos VPS de referencia
cd /opt/trading-bot && git pull origin main
docker build -t trading-bot-api-img:latest -f backend/Dockerfile backend/
docker stop trading-bot-api && docker rm trading-bot-api
docker-compose -f docker-compose.production.yml up -d api
docker logs trading-bot-api --tail 50

---

## Cómo retomar
Arrastra este archivo al chat y escribe:
Lee CONTEXT.md y continúa desde donde lo dejamos.