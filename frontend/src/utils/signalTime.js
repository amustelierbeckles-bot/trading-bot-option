/**
 * signalTime.js — Referencia maestra de tiempo para señales
 *
 * AMBOS componentes (ActiveSignalBanner y TradingClockOverlay) usan
 * estas funciones para garantizar sincronización perfecta.
 * Sin date-fns para evitar desfases de rounding internos.
 */

export const SIGNAL_DURATION = 120; // segundos de vida por señal
export const BLINK_THRESHOLD  = 5;  // segundos para alertas visuales

/**
 * Parsea cualquier timestamp del servidor a Date UTC.
 * Maneja strings con y sin "Z", y objetos Date directamente.
 */
export function parseServerTs(ts) {
  if (!ts) return new Date();
  if (ts instanceof Date) return ts;
  const utc = ts.endsWith("Z") || ts.includes("+") ? ts : ts + "Z";
  return new Date(utc);
}

/**
 * Calcula segundos restantes de una señal usando ms puros (sin rounding de date-fns).
 * @param {string} signalTimestamp - timestamp ISO del servidor
 * @returns {number} segundos enteros restantes, mínimo 0
 */
export function getSecondsLeft(signalTimestamp) {
  const origin  = parseServerTs(signalTimestamp);
  const elapsed = Math.floor((Date.now() - origin.getTime()) / 1000);
  return Math.max(0, SIGNAL_DURATION - elapsed);
}

/**
 * Calcula el porcentaje de tiempo restante (0-100).
 */
export function getTimePct(signalTimestamp) {
  return (getSecondsLeft(signalTimestamp) / SIGNAL_DURATION) * 100;
}

/**
 * Formatea segundos como "M:SS" si hay minutos, o "SS" si no.
 */
export function formatTime(totalSeconds) {
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return m > 0 ? `${m}:${String(s).padStart(2, "0")}` : String(s).padStart(2, "0");
}

/**
 * Determina si una señal está activa (dentro de su ventana de 2 min).
 * Acepta objeto señal con timestamp/created_at/active, o string ISO directo.
 */
export function isSignalLive(signal) {
  if (!signal) return false;
  const ts = typeof signal === "string"
    ? signal
    : (signal.timestamp || signal.signal_timestamp || signal.created_at);
  if (!ts) return false;
  if (signal?.active === false) return false;
  return getSecondsLeft(ts) > 0;
}



