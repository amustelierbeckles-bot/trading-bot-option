# AGENT.md — Trading Bot PocketOption

> Archivo de contexto para agentes de IA (Cursor, Claude, etc.).
> Leer completo antes de tocar cualquier archivo del proyecto.

---

## 🤖 ¿Qué es este proyecto?

Bot de trading algorítmico para opciones binarias OTC en PocketOption que genera señales usando un ensemble de 5 estrategias técnicas (CCI+Alligator, RSI+Bollinger, MACD+Stochastic, EMA Crossover, Range Breakout). Evalúa confluencia multi-estrategia con un quality score dinámico, envía alertas a Telegram con auditoría automática de resultados, y registra estadísticas completas en MongoDB. Opera con datos en tiempo real de Twelve Data y PocketOption WebSocket, con circuit breaker, filtros de sesión de mercado y verificación autónoma de Win Rate.

---

## 🏗️ Stack Tecnológico

### Backend
- **Python 3.11** — FastAPI + Uvicorn
- **MongoDB** — historial de señales y trades (`signals`, `trades`, `calibration`)
- **Redis** — caché de precios y rate limiting
- **WebSocket** — conexión directa a PocketOption (`events-po.com`) para precios en tiempo real
- **Twelve Data API** — precios históricos y técnicos (modo fallback)
- **Telegram Bot API** — alertas y auditoría de resultados

### Frontend
- **React 18** — dashboard de señales y estadísticas
- **localStorage** — persistencia visual W/L entre sesiones
- **Nginx** — servidor de producción con proxy a `/api/`

### Infraestructura
- **Docker + Docker Compose v2** — contenedores en VPS
- **Ubuntu 22.04** — VPS en DigitalOcean (`67.205.165.201`)
- **Cloudflare** — proxy DNS y SSL
- **GitHub** — repositorio remoto (`amustelierbeckles-bot/trading-bot-option`)

---

## 📁 Estructura del Proyecto

```
Pocket-option-bot/
├── backend/
│   ├── server.py              # Punto de entrada principal (FastAPI app)
│   ├── main.py                # Inicialización de módulos y startup
│   ├── strategies/            # 5 estrategias técnicas
│   │   ├── cci_alligator.py   # CCI + Williams Alligator
│   │   ├── rsi_bollinger.py   # RSI + Bollinger Bands
│   │   ├── macd_stochastic.py # MACD + Stochastic
│   │   ├── ema_crossover.py   # EMA rápida/lenta crossover
│   │   └── range_breakout.py  # Ruptura de rango OTC
│   ├── po_websocket.py        # Conexión WebSocket PocketOption
│   ├── data_provider.py       # TwelveData + caché Redis
│   ├── calibration.py         # Auto-calibración de umbral quality_score
│   ├── circuit_breaker.py     # Circuit breaker de pérdidas consecutivas
│   ├── audit.py               # Verificación autónoma de resultados W/L
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── dashboard/     # PairCard, RightPanel, SignalCard
│   │   │   ├── ActiveSignalBanner.js
│   │   │   └── useDashboard.js
│   │   ├── utils/
│   │   │   └── wlHistory.js   # Persistencia W/L en localStorage
│   │   └── App.js
│   └── package.json
├── nginx/
│   └── cloudflare.conf        # Headers CORS + proxy /api/
├── docker-compose.production.yml
├── docker-compose.yml         # Solo para desarrollo local
├── .env                       # Variables locales (nunca commitear)
├── .env.example               # Plantilla sin credenciales reales
└── .gitignore
```

---

## 🧩 Arquitectura de Módulos

| Módulo | Responsabilidad |
|--------|----------------|
| `server.py` | Endpoints FastAPI, auto-scan loop, healthcheck `/api/health` |
| `strategies/` | Cada archivo implementa una clase con método `evaluate()` |
| `po_websocket.py` | Suscripción a 20 pares OTC, precios en tiempo real, autenticación con `ci_session` |
| `data_provider.py` | TwelveData API + caché Redis 300s + límite 5000/día |
| `calibration.py` | Ajusta `score_base` según WR histórico — solo usa `audit_confidence='high'` |
| `circuit_breaker.py` | Bloquea señales tras N pérdidas consecutivas |
| `audit.py` | Verifica resultados usando precio de cierre de PO WebSocket (sin gastar créditos API) |
| `wlHistory.js` | localStorage `wr_history_OTC_{SYMBOL}` — máx 20 entradas rolling por par |

---

## 🔄 Flujo de Trabajo (Deploy)

```
1. Editar código en local (VS Code / Cursor)
2. git add + git commit (ver convenciones)
3. git push origin main
4. En VPS:
   ssh root@67.205.165.201
   cd /opt/trading-bot && git pull origin main
   docker build -t trading-bot-api-img:latest -f backend/Dockerfile backend/
   docker stop trading-bot-api && docker rm trading-bot-api
   docker-compose -f docker-compose.production.yml up -d api
5. Verificar:
   docker ps | grep trading-bot-api   # debe mostrar (healthy)
   docker logs trading-bot-api --tail 40
```

---

## 🖥️ Comandos de Operación

```bash
# Ver estado del contenedor
docker ps | grep trading-bot-api

# Ver logs en tiempo real
docker logs trading-bot-api --tail 50 -f

# Reiniciar solo el API
docker restart trading-bot-api

# Healthcheck manual
curl -s http://localhost:8000/api/health

# Conectarse al VPS
ssh root@67.205.165.201

# Ver tamaño del repo
git count-objects -vH
```

---

## ⚙️ Variables de Entorno Críticas

| Variable | Descripción | ⚠️ Riesgo |
|----------|-------------|-----------|
| `AUTO_EXECUTE` | Habilita ejecución automática de trades | 🔴 No activar sin WR ≥ 55% |
| `AUTO_EXECUTE_MIN_WR` | WR mínimo para auto-ejecución (default: 0) | 🔴 Subir a 55 antes de activar |
| `ACCOUNT_MODE` | `demo` o `real` | 🔴 Nunca cambiar a `real` sin autorización |
| `PO_CI_SESSION` | Cookie de sesión PocketOption (vinculada a IP del VPS) | 🟡 Expira — renovar si WebSocket falla |
| `TWELVE_DATA_API_KEY` | Key para precios históricos | 🟡 Límite 5000/día |
| `TELEGRAM_BOT_TOKEN` | Token del bot de Telegram | 🔴 Nunca commitear |
| `MONGO_URI` | Conexión a MongoDB | 🔴 Nunca commitear |
| `LOG_LEVEL` | `INFO` en producción | 🟢 Seguro cambiar |

---

## 🚫 Prohibiciones Absolutas

```
❌ Nunca modificar .env.production ni commitear credenciales, tokens o cookies
❌ Nunca hacer git push --force sin avisar (puede romper el historial del VPS)
❌ Nunca cambiar AUTO_EXECUTE=true sin confirmar WR real ≥ 55% con 20+ operaciones
❌ Nunca eliminar la colección 'signals' de MongoDB (historial estadístico irreemplazable)
❌ Nunca usar docker-compose --force-recreate (causa KeyError: ContainerConfig en este VPS)
❌ Nunca cambiar ACCOUNT_MODE=demo a real sin autorización explícita
❌ Nunca subir archivos .zip, node_modules/, o frontend/build/ al repositorio
❌ Nunca instalar curl en el Dockerfile para healthcheck — usar Python urllib
```

---

## 📐 Convenciones de Código

### Idioma
- **Comentarios y logs**: español
- **Código** (variables, funciones, clases): inglés

### Python
```python
# Variables: snake_case
entry_price, quality_score, signal_type, audit_confidence

# Constantes: UPPER_SNAKE_CASE
MIN_QUALITY, MAX_PER_CYCLE, AUTO_EXECUTE_MIN_WR

# Clases de estrategia: sufijo Strategy
class CCIAlligatorStrategy:
class RSIBollingerStrategy:

# Logs con emoji + contexto
logger.info("✅ MongoDB conectado")
logger.warning("⚠️ Error WebSocket — reintentando")
logger.info("🔌 PO WebSocket iniciado")
logger.info("🚀 Auto-scan PARALELO v2.3 iniciado")
```

### JavaScript / React
```javascript
// Variables: camelCase
fetchAnalytics, tradeAct, selSig, wlVersion

// Logs con símbolo
console.log("✓ CALL EURUSD · 78%")
console.error("✗ Error cargando señales")
```

---

## 📝 Estilo de Commits

```
tipo: descripción en inglés, imperativo, conciso
```

| Tipo | Uso |
|------|-----|
| `feat:` | Nueva funcionalidad |
| `fix:` | Corrección de bug |
| `refactor:` | Reestructuración sin cambio de comportamiento |
| `chore:` | Mantenimiento (deps, config, Docker) |

### Ejemplos reales del proyecto
```
fix: use PO WebSocket price for audit verification (saves Twelve Data credits)
fix: remove duplicate WS protocol headers causing HTTP 400
feat: add Dockerfile to backend/ dir (compose context) + python healthcheck
refactor: split server.py into 9 modules (v3.0)
chore: remove deploy.zip.zip from git history (102MB → 243KB)
```

---

## 🧪 Testing y CI/CD

- **No hay CI/CD automatizado** — el deploy es manual vía SSH
- **Tests**: directorio `backend/tests/` — ejecutar con `pytest` antes de cada push importante
- **Verificación post-deploy**: siempre confirmar `(healthy)` en `docker ps` después de rebuild
- **Rollback**: `git revert` + nuevo push + rebuild en VPS

---

## 🔒 Reglas de Seguridad

- El archivo `.env` nunca va al repositorio — está en `.gitignore`
- Usar `.env.example` como plantilla para nuevos entornos
- La `ci_session` de PocketOption está vinculada a la IP del VPS — no funciona desde local
- MongoDB no tiene usuario/password en red interna Docker — no exponer puerto 27017 al exterior
- El circuit breaker es sagrado — nunca desactivarlo en producción

---

## 📊 Estado Actual del Sistema (Marzo 2026)

| Componente | Estado |
|------------|--------|
| Bot activo | ✅ Ventana 09:30 UTC-5 |
| PO WebSocket | ✅ 20 pares suscritos |
| Verificación W/L | ✅ Precio directo PO (sin API) |
| MongoDB | ✅ Conectado |
| Redis | ✅ Conectado |
| Telegram | ✅ Polling activo |
| Auto-ejecución | ⏳ Pendiente WR ≥ 55% con 20+ ops |
| Win Rate actual | ~58% (12 operaciones — aún no estadísticamente significativo) |

---

## 🗺️ Hoja de Ruta

```
AHORA       → Acumular señales verificadas con WR real
CON 20 OPS  → Subir AUTO_EXECUTE_MIN_WR de 0 a 55
WR ≥ 55%    → Activar AUTO_EXECUTE=true con ci_session válida del VPS
FASE 2      → Registro universal de señales + panel comparativo en dashboard
```

---

## 🧠 Skills del Agente

> NO cargues todas las skills en cada turno.
> Usa el router para cargar SOLO la relevante según la tarea.

**Router de skills:** `.agents/skills-router.md`

| Skill | Cuándo activar |
|---|---|
| `api-design-principles` | Nuevos endpoints, contratos REST |
| `architecture-patterns` | Refactors grandes, nuevos módulos |
| `code-review` | Revisión de código antes de push |
| `data-analysis` | Win rate, métricas, reportes |
| `database-schema-design` | Colecciones MongoDB, índices |
| `monitoring-observability` | Logs, alertas, infraestructura |
| `python-performance-optimization` | Lentitud, async, caché |
| `security-best-practices` | CORS, auth, vulnerabilidades |

**Memoria persistente:** Engram MCP activo — recuperar contexto con `mem_context pocket-option-bot` al iniciar sesión.

---

## 🤝 Agent Teams Lite

> Orquestación multi-agente para tareas complejas.
> El orquestador coordina — los subagentes ejecutan.

**Orquestador:** `.agents/teams/orchestrator.md`

| Subagente | Rol |
|---|---|
| `explorer.md` | Análisis de impacto antes de actuar |
| `backend-dev.md` | Implementación FastAPI / Python |
| `frontend-dev.md` | Implementación React / dashboard |
| `tester.md` | Tests pytest / React Testing Library |
| `deploy-agent.md` | Docker + VPS + GitHub Actions |
| `analyst.md` | Métricas de señales y win rate |

**Activación:** `/team-new <descripción de tarea>` para flujo completo.
**SDD (features grandes):** `/sdd-new <feature>` para pipeline Explorer→Spec→Design→Tasks→Apply→Verify.
