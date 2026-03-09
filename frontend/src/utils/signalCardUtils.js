/**
 * signalCardUtils.js — Constantes, mapas y helpers de SignalCard
 */

export const SIGNAL_DURATION_SECONDS = 120;
export const EXPIRY_MINUTES          = 2;
export const BACKEND_URL             = process.env.REACT_APP_BACKEND_URL;

// ── Mapa de activos → ID exacto de Pocket Option (formato: XXXYYY_otc) ───────
// PocketOption usa guión bajo + minúscula "otc" en el hash de la URL.
export const ASSET_MAP = {
  OTC_EURUSD: "EURUSD_otc", OTC_GBPUSD: "GBPUSD_otc",
  OTC_USDJPY: "USDJPY_otc", OTC_USDCHF: "USDCHF_otc",
  OTC_AUDUSD: "AUDUSD_otc", OTC_USDCAD: "USDCAD_otc",
  OTC_NZDUSD: "NZDUSD_otc", OTC_EURJPY: "EURJPY_otc",
  OTC_EURGBP: "EURGBP_otc", OTC_EURAUD: "EURAUD_otc",
  OTC_EURCAD: "EURCAD_otc", OTC_EURCHF: "EURCHF_otc",
  OTC_GBPJPY: "GBPJPY_otc", OTC_GBPAUD: "GBPAUD_otc",
  OTC_GBPCAD: "GBPCAD_otc", OTC_GBPCHF: "GBPCHF_otc",
  OTC_AUDJPY: "AUDJPY_otc", OTC_AUDCAD: "AUDCAD_otc",
  OTC_CADJPY: "CADJPY_otc", OTC_CHFJPY: "CHFJPY_otc",
};

// ── Preferencia demo/real (persiste en localStorage) ─────────────────────────
export const PO_MODE_KEY = "po_trading_mode"; // "demo" | "real"

export function getPOMode() {
  return localStorage.getItem(PO_MODE_KEY) || "real";
}

export function setPOMode(mode) {
  localStorage.setItem(PO_MODE_KEY, mode === "demo" ? "demo" : "real");
}

export function getPOBaseUrl() {
  return getPOMode() === "demo"
    ? "https://pocketoption.com/en/cabinet/demo-quick-high-low/"
    : "https://pocketoption.com/en/cabinet/quick-high-low/";
}

export const EXPIRY_MAP = { "1m": 60, "2m": 120, "3m": 180, "5m": 300 };

// ── Helpers de color y badge ──────────────────────────────────────────────────
export const getPayoutColor = (p) =>
  p >= 92 ? "text-buy font-bold" : p >= 90 ? "text-buy" : "text-yellow-400";

export const getQualityBadge = (q) =>
  q >= 75 ? { text: "Limpio",    color: "bg-buy/10 text-buy border-buy/30" }
: q >= 60 ? { text: "Aceptable", color: "bg-yellow-500/10 text-yellow-400 border-yellow-500/30" }
:           { text: "Sucio",     color: "bg-sell/10 text-sell border-sell/30" };

export const getTimeColor = (timeRemaining) =>
  !timeRemaining                        ? "text-muted-foreground"
: timeRemaining.percentage > 66         ? "text-buy"
: timeRemaining.percentage > 33         ? "text-yellow-400"
:                                         "text-sell";

// ── Nombre formateado para búsqueda en PO ────────────────────────────────────
export const getAssetSearchName = (symbol) => {
  const pair = symbol.replace("OTC_", "").replace(/[^A-Z]/gi, "");
  return `${pair.slice(0, 3)}/${pair.slice(3)} OTC`;
};

// ── Formatea timestamp a UTC-5 ────────────────────────────────────────────────
export const formatTimestampUTC5 = (raw) => {
  const utcStr  = raw.endsWith("Z") || raw.includes("+") ? raw : raw + "Z";
  const utcDate = new Date(utcStr);
  const utc5    = new Date(utcDate.getTime() - 5 * 60 * 60 * 1000);
  return `Generada: ${utc5.toISOString().slice(11, 19)} (UTC-5)`;
};

// ── Abre Pocket Option en nueva pestaña con el par pre-seleccionado ──────────
export async function openPocketOption(assetName, symbol) {
  const assetId = ASSET_MAP[symbol] ?? (symbol.replace("OTC_", "").toLowerCase() + "_otc");
  const baseUrl = getPOBaseUrl();
  const url     = `${baseUrl}#${assetId}`;
  const mode    = getPOMode();
  try { await navigator.clipboard.writeText(assetName); } catch (_) {}
  const newTab = window.open(url, "_blank", "noopener,noreferrer");
  if (newTab) newTab.opener = null;
  return { url, mode, assetId };
}
