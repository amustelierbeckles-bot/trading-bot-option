# CONTEXT.md — Estado actual del proyecto

## Última actualización: 02/04/2026

> Los datos estables (protocolo WS, infra VPS, credenciales) están en la memoria
> persistente del agente. Este archivo cubre solo el estado reciente y pendientes.

---

## Estado operativo (02/04/2026 ~07:00 UTC)

- Bot corriendo en VPS, `ACCOUNT_MODE=real`, `AUTO_EXECUTE=true`
- Proxy residencial activo: `31.98.14.221:5898` (nskpjqbk)
- Auth PO: `user_init + id + secret` → confirmado con `updateAssets`
- Suscripción: `subscribeSymbol + #symbol_otc` → 20 pares sin 1005
- `connected=true`, `ready_pairs=0` (fuera de ventana hasta 09:30 UTC-4)
- Circuit Breaker: desbloqueado

## Pendiente inmediato

- 🟡 **09:30 UTC-4** — verificar `ready_pairs > 0`:
  ```bash
  curl -s http://67.205.165.201:8000/api/health | python3 -m json.tool
  ```
  Si sube → ticks reales activos por primera vez. Si no → investigar frames binarios.

---

## Sesiones recientes — resuelto

### 02/04/2026
- Diagnóstico A/B: `changeSymbol` causa 1005, `subscribeSymbol+#` funciona ✅
- Proxy residencial `31.98.14.221` reemplazó datacenter `82.29.227.121` ✅
- Guard anti-duplicados en `signals` (pre-check MongoDB) ✅

### 01/04/2026
- Auth PO resuelto: `user_init + id + secret` después de msg-40 ✅
- WS URL bug corregido: `self._ws_url` en lugar de global ✅
- `updateAssets` reconocido como confirmación de auth ✅

### 31/03/2026
- gentle-ai, GGA hook pre-commit instalados
- Fix H3 race condition auth/suscripción
- Fix H1 SSID URL-decode
- Diagnóstico: ci_session IP-bound era el bloqueante original

### 30/03/2026
- AUTO_EXECUTE operativo: 2 trades reales (AUDJPY W, GBPAUD W)
- CB reseteado en Redis

---

## CÓMO RETOMAR
Arrastra este archivo al chat. Los detalles técnicos estables están en memoria persistente.
