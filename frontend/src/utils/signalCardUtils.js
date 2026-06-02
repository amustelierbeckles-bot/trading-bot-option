/**
 * signalCardUtils.js — Mapa de activos PO + apertura de PocketOption.
 */

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

// ── Abre Pocket Option en nueva pestaña con el par copiado al portapapeles ───
// NOTA: PocketOption ignora el hash de URL para selección de activos.
// La estrategia es: abrir PO + copiar el nombre exacto del par al portapapeles
// + mostrar un recordatorio flotante que el usuario cierra cuando ya seleccionó.
export async function openPocketOption(assetName, symbol, signalType) {
  const assetId   = ASSET_MAP[symbol] ?? (symbol.replace("OTC_", "").toLowerCase() + "_otc");
  const baseUrl   = getPOBaseUrl();
  const url       = `${baseUrl}#${assetId}`;
  const mode      = getPOMode();
  const pairLabel = assetName || symbol.replace("OTC_", "").replace(/([A-Z]{3})([A-Z]{3})/, "$1/$2") + " OTC";

  // Copia en formato de búsqueda de PO: euraud_otc (minúsculas + guión bajo)
  const searchTerm = assetId.toLowerCase();   // ej: "euraud_otc"
  try { await navigator.clipboard.writeText(searchTerm); } catch (_) {}

  // Muestra recordatorio flotante con el par y la dirección
  _showPOReminder(assetId, signalType);

  const newTab = window.open(url, "_blank", "noopener,noreferrer");
  if (newTab) newTab.opener = null;
  return { url, mode, assetId };
}

// ── Recordatorio flotante: par + dirección + instrucción ─────────────────────
function _showPOReminder(assetId, signalType) {
  // Elimina el anterior si existe
  const prev = document.getElementById("po-reminder");
  if (prev) prev.remove();

  const isCall  = signalType === "CALL" || signalType === "BUY";
  const color   = isCall ? "#00FF94" : "#FF0055";
  const dir     = isCall ? "BUY ↑" : "SELL ↓";

  const el = document.createElement("div");
  el.id = "po-reminder";
  Object.assign(el.style, {
    position:     "fixed",
    bottom:       "24px",
    left:         "50%",
    transform:    "translateX(-50%)",
    zIndex:       "99999",
    background:   "#0a0a0f",
    border:       `2px solid ${color}`,
    borderRadius: "12px",
    padding:      "16px 24px",
    textAlign:    "center",
    fontFamily:   "monospace",
    boxShadow:    `0 0 30px ${color}40`,
    minWidth:     "280px",
    cursor:       "pointer",
  });

  const searchTerm = assetId.toLowerCase();
  const line = (text, css) => {
    const d = document.createElement("div");
    d.style.cssText = css;
    d.textContent = text;
    return d;
  };
  el.appendChild(line("Pega esto en el buscador de PO:", "font-size:11px;color:#888;margin-bottom:4px;"));
  el.appendChild(line(searchTerm, `font-size:22px;font-weight:bold;color:${color};letter-spacing:2px;`));
  el.appendChild(line(dir, `font-size:16px;font-weight:bold;color:${color};margin-top:4px;`));
  el.appendChild(line("✓ Copiado al portapapeles (Ctrl+V)", "font-size:10px;color:#00FF94;margin-top:8px;"));
  el.appendChild(line("Clic aquí para cerrar", "font-size:10px;color:#555;margin-top:2px;"));

  el.addEventListener("click", () => el.remove());
  // Auto-cierre en 30 segundos
  setTimeout(() => el && el.remove(), 30000);
  document.body.appendChild(el);
}
