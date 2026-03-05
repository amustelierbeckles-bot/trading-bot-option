/**
 * signalCardUtils.js — Constantes, mapas y helpers de SignalCard
 */

export const SIGNAL_DURATION_SECONDS = 120;
export const EXPIRY_MINUTES          = 2;
export const BACKEND_URL             = process.env.REACT_APP_BACKEND_URL;

// ── Mapa de activos → ID de Pocket Option ────────────────────────────────────
export const ASSET_MAP = {
  OTC_EURUSD: "EURUSD-OTC", OTC_GBPUSD: "GBPUSD-OTC",
  OTC_USDJPY: "USDJPY-OTC", OTC_USDCHF: "USDCHF-OTC",
  OTC_AUDUSD: "AUDUSD-OTC", OTC_USDCAD: "USDCAD-OTC",
  OTC_NZDUSD: "NZDUSD-OTC", OTC_EURJPY: "EURJPY-OTC",
  OTC_EURGBP: "EURGBP-OTC", OTC_EURAUD: "EURAUD-OTC",
  OTC_EURCAD: "EURCAD-OTC", OTC_EURCHF: "EURCHF-OTC",
  OTC_GBPJPY: "GBPJPY-OTC", OTC_GBPAUD: "GBPAUD-OTC",
  OTC_GBPCAD: "GBPCAD-OTC", OTC_GBPCHF: "GBPCHF-OTC",
  OTC_AUDJPY: "AUDJPY-OTC", OTC_AUDCAD: "AUDCAD-OTC",
  OTC_CADJPY: "CADJPY-OTC", OTC_CHFJPY: "CHFJPY-OTC",
};

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

// ── Abre Pocket Option en nueva pestaña ──────────────────────────────────────
export async function openPocketOption(assetName, symbol) {
  const rawAsset  = ASSET_MAP[symbol] ?? symbol.replace("OTC_", "") + "-OTC";
  const safeAsset = rawAsset.replace(/[^A-Z0-9\-]/gi, "").toUpperCase();
  const url       = `https://pocketoption.com/en/cabinet/demo-quick-high-low/#${safeAsset}`;
  try { await navigator.clipboard.writeText(assetName); } catch (_) {}
  const newTab = window.open(url, "_blank", "noopener,noreferrer");
  if (newTab) newTab.opener = null;
}
