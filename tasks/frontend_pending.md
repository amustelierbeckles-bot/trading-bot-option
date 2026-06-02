# Frontend — Pendientes (auditoría 2026-06-02)

Fuente: FRONTEND_AUDIT_2026-06-02.md. Estado al 2026-06-02.

## Resueltos
- F-1 drift bundle — bundle viejo reemplazado, build desde dfd5f47 servido por nginx (2026-06-02 14:28).
- F-5 ErrorBoundary — wrapper añadido en App.js (cubre toda la app).
- F-7 (páginas) — timeout en axios de Performance.js / Backtesting.js / ValidateMobile.js.
- F-9 timezone — Performance.js "Win Rate por hora": añadido equivalente local UTC-4 inline; sesiones forex siguen en UTC (correcto).

## Diferidos — DASHBOARD (no se usa por ahora, decisión del dueño 2026-06-02)
- **F-3** datos stale verdes — `hooks/useDashboard.js`: `fetchPre`/`fetchStats`/`fetchRisk` con `catch {}` silencioso y sin timestamp. RightPanel y CBBar siguen en verde con backend caído. Fix: marcar `last_fetch_ok` por recurso + atenuar/etiquetar "stale Xs".
- **F-4** feed sin frescura — `components/dashboard/PairCard.jsx`: pinta `data?.price` sin marca stale; la UI nunca consulta `/api/health` (`last_tick_age`). Fix: consumir `last_tick_age` por par y marcar pares stale en rojo/gris.
- **F-6** stale closure risk — `hooks/useDashboard.js`: `fetchRisk` depende de `[balance, sessStart]` pero el interval i4 (`setInterval(fetchRisk, 30000)`) se fija en mount con deps `[]` → captura el closure inicial y el polling de riesgo envía el balance viejo. Fix: ref para balance o recrear el interval.
- **F-7 (dashboard)** — los fetches de `useDashboard.js` (i1-i5) no tienen timeout ni AbortController; sin abort en unmount. Fix: AbortController + signal, abort en cleanup.

## Bloqueado — decisión arquitectónica del dueño
- **F-2** API key pública en bundle — `REACT_APP_API_KEY` se inyecta al JS en build-time. Usada en `utils/dashboardUtils.js`, `pages/Backtesting.js`, `pages/ValidateMobile.js` (+ muertos). Envía header `X-API-Key`. Anula el auth backend (C5/H2/H3). Opciones: (a) quitar key del cliente + proxy backend con sesión httpOnly, o (b) aceptar que un SPA estático no puede ocultarla. No tocar sin decisión.

## Aparte — limpieza dead-code (~3000 LOC, opcional)
- Archivos huérfanos (sin importers): `pages/Dashboard_legacy.jsx`, `components/AssetList.js`, `components/SignalCard.js`, `components/RiskPanel.js`, `components/TradeStats.js`, `components/PriceChart.js`, `components/BacktestChart.js`, `components/TradesTable.js`, `hooks/useRiskManager.js`, `hooks/useTradeHistory.js`, `hooks/useSignalCard.js`, `components/CriticalPerformancePanel.js`. Incluye F-8 (XSS `signalCardUtils.js:125` innerHTML, en código muerto) y F-12 (formatTimestampUTC5 hardcoded). Borrar + limpiar deps de package.json.
