# CONTEXT.md — Estado actual del proyecto

## Última actualización: 02/04/2026 (sesión tarde)

> Los datos estables (protocolo WS, infra VPS, credenciales) están en la memoria
> persistente del agente. Este archivo cubre solo el estado reciente y pendientes.

---

## Estado operativo (02/04/2026)

- Bot corriendo en VPS, `ACCOUNT_MODE=real`, `AUTO_EXECUTE=true`
- Proxy residencial activo: `31.98.14.221:5898` (nskpjqbk)
- Auth PO: `user_init + id + secret` → confirmado con `updateAssets`
- Suscripción: `subscribeSymbol + #symbol_otc` → 20 pares sin 1005
- `connected=true`, `ready_pairs=0` (pendiente verificar en ventana 09:30 UTC-4)
- Circuit Breaker: desbloqueado

---

## Trabajo realizado en esta sesión

### Slash commands creados (`.claude/commands/`)
- `/deploy` → redeploy completo VPS con confirmación previa
- `/health` → health check + interpretación de ready_pairs / CB
- `/ci` → diagnóstico CI failures (patrones conocidos, reproducción local)

### Análisis profundo iniciado — EN CURSO
Se leyó la mayor parte del codebase. Sesión cortada al 98% de contexto.
**Retomar el análisis en la próxima sesión.**

Archivos leídos: `server.py`, `auto_exec.py`, `circuit_breaker.py`, `scoring.py`,
`strategies.py`, `audit_service.py`, `calibration.py`, `antifragile.py`,
`market_session.py`, `po_websocket.py` (parcial), `conftest.py`,
`test_po_websocket_pipeline.py`, `test_circuit_breaker.py`, `ci.yml`

### Hallazgo crítico — CI failure (pendiente confirmar)
`server.py:76` usa `MONGO_URL` como variable de entorno pero el CI inyecta `MONGO_URI`.
Posible causa raíz del CI roto desde hace semanas. Verificar en próxima sesión:
```bash
grep -n "MONGO_URL\|MONGO_URI" backend/server.py backend/.env.example
```

---

## Pendiente inmediato

- 🟡 **Verificar ticks** a las 09:30 UTC-4:
  ```bash
  curl -s http://67.205.165.201:8000/api/health | python3 -m json.tool
  ```
- 🔴 **Completar análisis profundo** — continuar desde `data_provider.py`,
  `routes/`, `win_rate_cache.py`, tests restantes
- 🔴 **Diagnosticar y corregir CI** — usa `/ci` al retomar

---

## Sesiones recientes — resuelto

### 02/04/2026
- Slash commands `/deploy`, `/health`, `/ci` creados en `.claude/commands/` ✅
- Sistema de memoria persistente (`memory/`) creado ✅
- Análisis profundo iniciado (retomar)

### 02/04/2026 (mañana)
- Diagnóstico A/B: `changeSymbol` causa 1005, `subscribeSymbol+#` funciona ✅
- Proxy residencial `31.98.14.221` reemplazó datacenter ✅
- Guard anti-duplicados en `signals` (pre-check MongoDB) ✅

### 01/04/2026
- Auth PO resuelto: `user_init + id + secret` después de msg-40 ✅
- WS URL bug corregido: `self._ws_url` en lugar de global ✅

---

## CÓMO RETOMAR
Arrastra este archivo al chat. Los detalles técnicos estables están en memoria persistente.
