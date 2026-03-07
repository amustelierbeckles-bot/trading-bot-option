/**
 * wlHistory.js — Persistencia W/L por par en localStorage
 *
 * Cada par guarda hasta MAX_ENTRIES resultados recientes.
 * Clave: "wr_history_{SYMBOL}"  →  [{r:"W"|"L", ts:ms, score:float}]
 *
 * Cuando se escribe un resultado se dispara el evento customizado
 * "wl-update" en window para que useDashboard incremente wlVersion
 * y fuerce el re-render de todos los PairCards.
 */

export const WL_PREFIX    = "wr_history_";
export const MAX_ENTRIES  = 20;   // máximo resultados por par
const        WL_EVENT     = "wl-update";


/** Lee el historial de un par desde localStorage. */
export function readWLHistory(symbol) {
  try {
    return JSON.parse(localStorage.getItem(WL_PREFIX + symbol) || "[]");
  } catch {
    return [];
  }
}


/**
 * Registra un resultado W/L para un par.
 * Despacha "wl-update" para notificar al dashboard.
 */
export function appendWLResult(symbol, result, meta = {}) {
  const entry = {
    r:     result === "win" ? "W" : "L",
    ts:    Date.now(),
    score: meta.quality_score || 0,
    type:  meta.signal_type   || "",
  };

  const prev = readWLHistory(symbol);
  const next = [...prev, entry].slice(-MAX_ENTRIES);

  try {
    localStorage.setItem(WL_PREFIX + symbol, JSON.stringify(next));
    // Notifica al dashboard en la misma pestaña
    window.dispatchEvent(new CustomEvent(WL_EVENT, { detail: { symbol } }));
  } catch {
    // localStorage lleno o bloqueado
  }
}


/**
 * Calcula el Win Rate del par.
 * Retorna null si no hay suficientes datos (< minTrades).
 */
export function getWinRate(symbol, minTrades = 1) {
  const history = readWLHistory(symbol);
  if (history.length < minTrades) return null;
  const wins = history.filter(e => e.r === "W").length;
  return Math.round((wins / history.length) * 100);
}


/** Retorna resumen de todos los pares que tienen historial. */
export function getAllSummary() {
  const summary = {};
  try {
    for (const key of Object.keys(localStorage)) {
      if (!key.startsWith(WL_PREFIX)) continue;
      const symbol  = key.replace(WL_PREFIX, "");
      const history = readWLHistory(symbol);
      if (!history.length) continue;
      const wins = history.filter(e => e.r === "W").length;
      summary[symbol] = {
        total:    history.length,
        wins,
        losses:   history.length - wins,
        win_rate: Math.round((wins / history.length) * 100),
        history,
      };
    }
  } catch {}
  return summary;
}


/** Borra el historial de un par (útil para "nueva sesión"). */
export function clearWLHistory(symbol) {
  try {
    localStorage.removeItem(WL_PREFIX + symbol);
    window.dispatchEvent(new CustomEvent(WL_EVENT, { detail: { symbol } }));
  } catch {}
}


/** Escucha el evento wl-update y llama callback. Retorna función de limpieza. */
export function onWLUpdate(callback) {
  window.addEventListener(WL_EVENT, callback);
  return () => window.removeEventListener(WL_EVENT, callback);
}
