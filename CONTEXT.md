# CONTEXT.md — Estado actual del proyecto

## Origen del proyecto
- **Inicio real:** 5 de febrero de 2026 (primer commit en workspace de Emergent)  
  - Hash: `c925674a6734d407d3c48a4828f5a3eb4b521330`  
  - Mensaje: `Initial commit` — Autor: `emergent-agent-e1`
- **Migración a GitHub:** 5 de marzo de 2026 (primer commit en `trading-bot-option`)
- Los dos repositorios son **árboles Git independientes** — el historial de Emergent **no** está en el remoto de GitHub
- **Desarrollo activo documentado desde:** 9 de febrero de 2026

## Última actualización: 31/03/2026 — gentle-ai instalado + diagnóstico ticks PO completo

---

## Sesión 31/03/2026 — completado / pendiente

### Implementado
- **gentle-ai v1.15.7** instalado en VPS. Claude Code configurado: preset `ecosystem-only` (context7, engram, gga, sdd, skills, Strict TDD).
- **GGA (Gentleman Guardian Angel):** hook `pre-commit` activo en repo. Revisa `.py/.js/.jsx` con Claude antes de cada commit usando reglas de `AGENTS.md`.
- **Engram:** 12 memorias del proyecto cargadas. Sincronizadas al repo en `.engram/`. Contexto completo disponible para futuras sesiones.
- **Fix H3 (race condition auth/suscripción):** `self._auth_event = asyncio.Event()` movido ANTES de enviar auth. Corrige la ventana donde PO enviaba `successauth` y el evento no existía aún.
- **Fix H1 (SSID URL-encoded):** `urllib.parse.unquote(ssid)` en `configure()`. Decodifica `%3A`, `%7B` etc. antes de enviar en `["auth", {...}]`.
- **Log diagnóstico:** eventos `40` y eventos desconocidos loguean a INFO temporalmente para diagnóstico.
- **Bug deploy descubierto:** `docker compose up -d --build` NO recrea contenedor si ya está `Running`. Patrón correcto: `docker stop → docker rm → docker compose up -d --build api`.

### Diagnóstico WebSocket — resultado
- PO responde al handshake con `40{"sid":"..."}` (namespace connect), no con `successauth`.
- El fallback de 5s dispara, intenta suscribir, pero PO cierra con `ConnectionClosedOK`.
- **Causa raíz confirmada:** `ci_session` obtenido desde IP local (`35.145.217.225`) pero bot conecta vía proxy (`194.113.80.23`). PO rechaza porque IP del session ≠ IP de conexión.

### PENDIENTE — crítico
- 🔴 **Obtener `ci_session` válido desde IP del proxy:**
  1. Instalar **FoxyProxy** en Chrome
  2. Configurar SOCKS5: `194.113.80.23:6306` / user: `nskpjqbk` / pass: `541oyok0gzpn`
  3. Login en pocketoption.com con proxy activo
  4. Copiar `ci_session` de DevTools → Application → Cookies
  5. Actualizar `PO_SSID` en VPS: `nano /opt/trading-bot/.env.production`
  6. Reiniciar: `docker stop trading-bot-api && docker rm trading-bot-api && docker compose -f docker-compose.production.yml up -d --build api`
  7. Verificar logs: buscar `✅ Auth PO confirmado` o ticks binarios

---

## Sesión 30/03/2026 — completado
- **AUTO-EXEC operativo:** pipeline señal → score → auditoría → MongoDB funcionando. Dos trades en ventana de madrugada: **AUD/JPY [W]** y **GBP/AUD [W]**. Causa raíz de 8 días sin ejecución: una sola línea faltante en `.env.production` (`AUTO_EXECUTE=true`).
- **CB reseteado:** `DEL cb:state` en Redis antes del deploy.
- **Fix H3 escrito (NO pusheado):** condición de carrera auth/suscripción en `backend/po_websocket.py`. El sleep ciego de 0.5–1.2s fue reemplazado por `asyncio.Event` + `_subscribe_after_auth` con timeout de 5s como fallback. Push pendiente + rebuild.
- **Estado operativo real:** bot ejecutando trades con TwelveData como fuente de datos (0/20 pares con ticks de PO). Las señales son reales (is_real=True vía TD), no simuladas.
- **Próxima hipótesis (H1):** Si tras el push del fix H3 los logs muestran el camino "fallback" (no llega `successauth`), investigar SSID URL-encoded sin decodificar (`urllib.parse.unquote`) antes de enviarlo en el payload `["auth", {...}]`.

---

## Sesión 29/03/2026 — completado
- **Proxy PO (VPS):** `PO_PROXY_URL` → SOCKS5 `194.113.80.23:6306` (Webshare). Evitar duplicar `PO_PROXY_URL` en `docker-compose.production.yml` → `environment:` (pisa `env_file`).
- **Telegram:** token rotado y actualizado en `.env.production` (el anterior quedó expuesto en logs).
- **LOG_LEVEL:** `WARNING` (sin ruido de `httpx`/Telegram en producción).
- **`.env.production`:** una sola línea `PO_SSID=…` (sin cortes); valores largos: `nano` o `grep -v` + `export` + `echo`, no `sed` multilínea.
- **AUTO-EXEC Fix:** Añadido `AUTO_EXECUTE=true` y `AUTO_EXECUTE_MODE=real` a `.env.production` en el VPS. El bot llevaba 8 días en 0% porque faltaba la variable.
- **Circuit Breaker:** Reseteado en Redis (`DEL cb:state`). Se disparaba por señales manuales/teóricas, bloqueando el bot.
- **Deploy:** `docker compose … up -d --force-recreate api` — logs OK: `modo=REAL`, proxy correcto, `POWebSocket conectado`, auth `isDemo=0`, suscripción 20 pares, a la espera de ventana operativa.

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
- **VPS (29/03/2026):** ejemplo activo `194.113.80.23:6306` — no duplicar en `docker-compose` `environment:` o el contenedor ignora `.env.production`.
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
- **Pendiente (🟡):** confirmar **ticks reales de PO** en la próxima ventana (madrugada **~00:00** o **09:30–12:00** hora local según `auto_exec`).
- Método: `LOG_LEVEL=DEBUG` temporal y buscar `"tick binary"` en logs, o `GET /api/health` → `po_websocket` (pares listos, edad último tick); luego volver a `WARNING`.
- Fuera de ventana: `auto_exec` puede mostrar *Fuera de ventana / Bot pausado* — el WS puede seguir conectado.

---

## DEPLOY VPS (referencia rápida)

**Docker Compose V2+ (VPS Ubuntu Jammy — resuelto 24/03/2026):** en Jammy a veces **`docker-compose-plugin` no está en los repos**; en ese caso el instalador oficial actualiza Engine + plugin Compose:

```bash
curl -fsSL https://get.docker.com | sh
sudo systemctl start docker   # si aplica
docker compose version        # ej. v5.x con Docker Engine 29.x
```

El binario obsoleto `docker-compose` (V1, guion) puede dar `KeyError: 'ContainerConfig'` al recrear solo `api`. **Usar siempre `docker compose`** (sin guion) tras el plugin.

**Comando de despliegue:**
```bash
cd /opt/trading-bot && git pull origin main
docker build --no-cache -t trading-bot-api-img:latest -f backend/Dockerfile backend/
docker stop trading-bot-api && docker rm trading-bot-api
docker compose -f docker-compose.production.yml up -d api
docker logs trading-bot-api --tail=50
```

**Si el contenedor existe con nombre conflictivo:** `docker rm -f <id_o_nombre>` antes del `up`.

**Workaround legado V1:** `docker stop` + `docker rm` antes de `docker-compose … up -d api`.

Tras cambiar solo `.env`: a veces basta recrear el contenedor; si cambian dependencias, **rebuild** como arriba.

**Post-deploy:** `GET /api/health` — objeto `po_websocket` (conexión, pares listos, edad último tick, kill-switch).

**Migración Mongo (idempotente):** `docker cp scripts/migrate_signals_to_trades.js trading-bot-mongo:/tmp/migrate.js && docker exec trading-bot-mongo mongosh trading-bot /tmp/migrate.js` (0 migrados si `signals` no tenía docs con `po_order_id`).

**Git en VPS:** remote con PAT permite `git push` sin contraseña; **no commitear el token**; preferible a medio plazo **SSH deploy key** o credential helper y rotar PAT si hubo exposición.

**Repo (24/03/2026):** `backend/utils.py` con `_parse_naive_utc` centralizada; imports en `routes/*`, `main.py`, `api/routes/*` — commit `07a53ea` en `main`.

---

## PENDIENTES
- 🔴 **PO ticks (la hidra):** Bot opera con 0/20 pares de ticks reales. Dos hipótesis por resolver en orden:
  1. **H3 (fix escrito, pendiente push+rebuild):** Race condition auth/suscripción. Ver logs post-deploy: `"Auth PO confirmado por servidor"` = fix funcionó; `"Auth PO sin confirmación en 5.0s"` = fallback activo → investigar H1.
  2. **H1 (si H3 fallback):** SSID URL-encoded (`%3A`, `%7B`) se envía sin decodificar en `["auth", {"session": ...}]`. Fix: `urllib.parse.unquote(self._ssid)` antes de construir `auth_msg`.
- 🟡 **Push fix H3:** `git push origin main` + rebuild en VPS + verificar logs buscando `"Auth PO"` y `"tick binary"`.
- 🟢 **30/03** — AUTO-EXEC operativo, 2 trades reales (AUDJPY W, GBPAUD W), fix H3 escrito, bot estable con TD fallback.
- 🟢 **29/03** — proxy `194.113.80.23:6306`, Telegram rotado, `LOG_LEVEL=WARNING`, `.env.production` limpio, `PO_SSID` renovado, AUTO-EXEC activado, CB reseteado, deploy sin errores.
- 🟢 Hecho en VPS 24/03: Compose v5.x + Engine 29.x, 3 contenedores (api, redis, mongo), PO REAL + proxy, migración ejecutada (0 docs), refactor `utils.py`, deploy estable.

---

## CÓMO RETOMAR
Arrastra este archivo al chat y escribe:
> Lee CONTEXT.md y continúa desde donde lo dejamos.
