/**
 * dashboardUtils.js — Tokens de diseño, constantes y helpers
 * Extraído de Dashboard.jsx (RADAR v2.9)
 */

// ── API ───────────────────────────────────────────────────────────────────────
export const API     = process.env.REACT_APP_BACKEND_URL || "http://localhost:8000";
export const API_KEY = process.env.REACT_APP_API_KEY;

// ── Design tokens ─────────────────────────────────────────────────────────────
export const T = {
  bg:      "#000",
  surface: "#090909",
  card:    "#0F0F0F",
  border:  "#333333",
  text:    "#E0E0E0",
  sub:     "#888",
  muted:   "#555",
  dim:     "#2a2a2a",
  call:    "#00FF41",
  put:     "#FF3131",
  fire:    "#FFAC1C",
  pre:     "#00FFFF",
  violet:  "#9D6FFF",
  idle:    "#2a2a2a",
  warn:    "#FF3131",
};

// ── Helpers de color por tipo de señal ───────────────────────────────────────
export const sc  = t => t==="CALL"?T.call:t==="PUT"?T.put:t==="FIRE"?T.fire:T.pre;
export const fmt = (v, d=5) => v != null ? Number(v).toFixed(d) : "—";

// ── Clave localStorage para panes ────────────────────────────────────────────
export const PANE_KEY = "radar_v27_panes";

// ── Todos los pares OTC ───────────────────────────────────────────────────────
export const ALL_PAIRS = [
  "OTC_EURUSD","OTC_GBPUSD","OTC_USDJPY","OTC_USDCHF",
  "OTC_AUDUSD","OTC_NZDUSD","OTC_USDCAD","OTC_EURJPY",
  "OTC_EURGBP","OTC_EURAUD","OTC_EURCAD","OTC_EURCHF",
  "OTC_GBPJPY","OTC_GBPAUD","OTC_GBPCAD","OTC_GBPCHF",
  "OTC_AUDJPY","OTC_AUDCAD","OTC_CADJPY","OTC_CHFJPY",
];

// ── Inicializar tamaños de paneles ────────────────────────────────────────────
export function initPanes() {
  try { return JSON.parse(localStorage.getItem(PANE_KEY)) || { L: 220, R: 235 }; }
  catch { return { L: 220, R: 235 }; }
}

// ── Health semáforo ───────────────────────────────────────────────────────────
export const HEALTH_COLORS = {
  success: "#00FF41",
  warning: "#FFAC1C",
  danger:  "#FF3131",
  unknown: "#555555",
};

export const HEALTH_ICONS = {
  success: <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="#00FF41" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"/></svg>,
  warning: <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="#FFAC1C" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>,
  danger:  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="#FF3131" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>,
  unknown: null,
};

export function getHealthColor(value, type) {
  if (value == null) return { color: HEALTH_COLORS.unknown, status: "unknown", icon: null };
  const v = Number(value);
  let status;
  switch (type) {
    case "win_rate":      status = v > 60  ? "success" : v >= 50   ? "warning" : "danger"; break;
    case "profit_factor": status = v > 1.20? "success" : v >= 1.05 ? "warning" : "danger"; break;
    case "mae":           status = v < 10  ? "success" : v <= 20   ? "warning" : "danger"; break;
    case "latency":       status = v < 100 ? "success" : v <= 300  ? "warning" : "danger"; break;
    default:              status = "unknown";
  }
  return { color: HEALTH_COLORS[status], status, icon: HEALTH_ICONS[status] };
}

// ── Normalizers de datos del backend ─────────────────────────────────────────
export function normalizeStats(raw) {
  if (!raw) return null;
  const ca = raw.critical_apparatus;
  if (ca) {
    return {
      win_rate:       ca.win_rate?.value      ?? null,
      profit_factor:  ca.profit_factor?.value ?? null,
      mae_avg_pips:   ca.mae?.value           ?? null,
      latency_avg_ms: ca.latency?.value       ?? null,
      total_trades:   raw.total_trades        ?? 0,
      total_wins:     raw.total_wins          ?? 0,
      total_losses:   raw.total_losses        ?? 0,
    };
  }
  return raw;
}

export function normalizeSignals(raw) {
  if (!raw?.signals) return [];
  return raw.signals;
}

export function normalizeMarketAsset(asset) {
  if (!asset) return null;
  return {
    price:      asset.price,
    change_pct: asset.change_pct,
    prices:     asset.sparkline_data || asset.prices || [],
    trend:      asset.trend,
    is_real:    asset.is_real ?? true,
  };
}

// ── Glosario de indicadores ───────────────────────────────────────────────────
export const GLOSS = {
  RSI:  { full:"Relative Strength Index",    def:"Oscilador 0–100. >70 sobrecompra, <30 sobreventa.",
          rows:[{l:">70 Sobrecompra",c:"#FF3131"},{l:"30–70 Neutral",c:"#555"},{l:"<30 Sobreventa",c:"#00FF41"}]},
  BB:   { full:"Bollinger Bands %B",         def:"Posición del precio dentro del canal ±2σ.",
          rows:[{l:">80% Banda sup.",c:"#FF3131"},{l:"20–80% Centro",c:"#555"},{l:"<20% Banda inf.",c:"#00FF41"}]},
  CCI:  { full:"Commodity Channel Index",    def:"Desvío estadístico del precio vs su media.",
          rows:[{l:">100 → CALL",c:"#00FF41"},{l:"±100 Rango",c:"#555"},{l:"<-100 → PUT",c:"#FF3131"}]},
  ATR:  { full:"Average True Range %",       def:"Volatilidad real del mercado en las últimas velas.",
          rows:[{l:">1.8% Alta",c:"#FFAC1C"},{l:"1–1.8% Normal",c:"#555"},{l:"<1% Plano",c:"#2a2a2a"}]},
  MAE:  { full:"Max Adverse Excursion",      def:"Cuánto retrocede el precio antes de tocar el objetivo.",
          rows:[{l:"<3px Limpio",c:"#00FF41"},{l:"3–10px Moderado",c:"#00FFFF"},{l:">10px Riesgoso",c:"#FF3131"}]},
  EMA:  { full:"Exponential Moving Average", def:"Tendencia suavizada. Precio encima = alcista.",
          rows:[{l:"Precio > EMA → CALL",c:"#00FF41"},{l:"Precio < EMA → PUT",c:"#FF3131"}]},
  MACD: { full:"MACD Convergence Divergence",def:"EMA12 − EMA26 + señal. Momentum del mercado.",
          rows:[{l:"MACD > Señal → CALL",c:"#00FF41"},{l:"MACD < Señal → PUT",c:"#FF3131"}]},
};
