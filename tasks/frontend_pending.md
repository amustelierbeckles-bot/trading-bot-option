# Frontend — Pendientes (auditoría 2026-06-02)

Fuente: FRONTEND_AUDIT_2026-06-02.md. Estado al 2026-06-02.

## Resueltos
- F-1 drift bundle — bundle viejo reemplazado, build desde dfd5f47 servido por nginx (2026-06-02 14:28).
- F-5 ErrorBoundary — wrapper añadido en App.js (cubre toda la app).
- F-7 (páginas) — timeout en axios de Performance.js / Backtesting.js / ValidateMobile.js.
- F-9 timezone — Performance.js "Win Rate por hora": añadido equivalente local UTC-4 inline; sesiones forex siguen en UTC (correcto).
- F-2 API key en bundle (Plan A) — DESPLEGADO y validado en vivo 2026-06-02. Backend: `auth_deps.verify_session_or_key` (sesión httpOnly firmada HMAC **O** X-API-Key server-side); `routes/auth.py` login/logout/me con cookie HttpOnly+Secure+SameSite=Strict; deps swapeadas en signals/trades/admin/risk. Frontend: removido `REACT_APP_API_KEY`; `LoginGate.jsx` envuelve App. Verificado: con cookie entra, sin cookie 401, bundle sin `X-API-Key`. APP_PASSWORD definido en VPS.
- F-8 XSS — RECLASIFICADO: NO era código muerto. `signalCardUtils._showPOReminder` (vía `openPocketOption` ← `ActiveSignalBanner` ← `Dashboard.jsx` vivo) usaba `innerHTML`. Severidad baja (datos internos: símbolos de pares fijos). Corregido: reemplazado por construcción DOM con `textContent`.
- F-12 timestamp UTC-5 — eliminado: `formatTimestampUTC5` quedó sin uso tras borrar `SignalCard`; export muerto removido junto al resto de helpers huérfanos.
- Dead-code — borrados 12 huérfanos: `Dashboard_legacy.jsx`, `AssetList/SignalCard/RiskPanel/TradeStats/PriceChart/BacktestChart/TradesTable.js`, `useRiskManager/useTradeHistory/useSignalCard.js`, `CriticalPerformancePanel.js` (+ su test). Podados exports muertos de `signalCardUtils.js`. **CONSERVADOS** (vivos): `signalCardUtils.js` + `ActiveSignalBanner.js`.

## Diferidos — DASHBOARD (no se usa por ahora, decisión del dueño 2026-06-02)
- **F-3** datos stale verdes — `hooks/useDashboard.js`: `fetchPre`/`fetchStats`/`fetchRisk` con `catch {}` silencioso y sin timestamp. RightPanel y CBBar siguen en verde con backend caído. Fix: marcar `last_fetch_ok` por recurso + atenuar/etiquetar "stale Xs".
- **F-4** feed sin frescura — `components/dashboard/PairCard.jsx`: pinta `data?.price` sin marca stale; la UI nunca consulta `/api/health` (`last_tick_age`). Fix: consumir `last_tick_age` por par y marcar pares stale en rojo/gris.
- **F-6** stale closure risk — `hooks/useDashboard.js`: `fetchRisk` depende de `[balance, sessStart]` pero el interval i4 (`setInterval(fetchRisk, 30000)`) se fija en mount con deps `[]` → captura el closure inicial y el polling de riesgo envía el balance viejo. Fix: ref para balance o recrear el interval.
- **F-7 (dashboard)** — los fetches de `useDashboard.js` (i1-i5) no tienen timeout ni AbortController; sin abort en unmount. Fix: AbortController + signal, abort en cleanup.

## Aparte — pendiente
- (vacío)

## Resueltos — sesión 2026-06-02 (cont.)
- Dead-code + F-8 + F-12 — DESPLEGADO 2026-06-02. Push 940edee → VPS git pull → frontend rebuild node:20 (`main.6a5a306a.js`, 130.09 kB) → nginx reload. Verificado en bundle live: `el.innerHTML` = 0 matches (patrón XSS removido), `po-reminder` presente (DOM-building vivo). El `grep -c innerHTML=1` fue falso positivo (bundle minificado = 1 línea física; token residual de React DOM internals).
- Deps huérfanas package.json — DESPLEGADO 2026-06-02 (commit 026209f). Borradas 4: recharts, lightweight-charts, @hookform/resolvers, zod (cero imports en src/, leftovers de chart/form components borrados). Conservadas: radix (usadas por ui/), ajv (fix build CRA), date-fns (peer react-day-picker). Verificado: rebuild VPS `Compiled successfully`, bundle hash idéntico (main.6a5a306a.js — tree-shaking ya las excluía).
- Token Telegram rotado — RESUELTO 2026-06-02 (validado por dueño). @BotFather revoke → nuevo token en `.env.production` VPS. **Lección:** `docker restart` NO recarga `.env` (env se inyecta solo al CREAR container) → ver `lessons.md` L1. Verificado: token viejo `getMe ok=False Unauthorized` (muerto), token nuevo `getUpdates 200 OK` (polling activo).
