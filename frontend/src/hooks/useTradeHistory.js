/**
 * useTradeHistory — Historial de operaciones por par en localStorage
 *
 * - Persiste entre recargas (misma sesión del día)
 * - Clave por par: "po_history_EURUSD"
 * - Máximo 30 resultados por par
 * - Win Rate calculado automáticamente
 */
import { useState, useEffect, useCallback } from "react";

const PREFIX   = "po_history_";
const DAY_KEY  = "po_session_day";
const MAX_HIST = 30;

function todayStr() {
  return new Date().toISOString().slice(0, 10); // "2026-02-20"
}

function storageKey(symbol) {
  return PREFIX + symbol.replace("OTC_", "");
}

function readAll() {
  const out = {};
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (!k || !k.startsWith(PREFIX)) continue;
      const raw = localStorage.getItem(k);
      if (raw) out["OTC_" + k.slice(PREFIX.length)] = JSON.parse(raw);
    }
  } catch (_) {}
  return out;
}

export default function useTradeHistory() {
  const [histories, setHistories] = useState({});

  // Carga inicial desde localStorage
  useEffect(() => {
    // Detecta nueva sesión (nuevo día) → limpia historial visual
    const saved = localStorage.getItem(DAY_KEY);
    const today = todayStr();
    if (saved !== today) {
      // Nuevo día: borra historiales anteriores
      const keys = [];
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        if (k?.startsWith(PREFIX)) keys.push(k);
      }
      keys.forEach(k => localStorage.removeItem(k));
      localStorage.setItem(DAY_KEY, today);
      setHistories({});
    } else {
      setHistories(readAll());
    }
  }, []);

  /**
   * Añade resultado a un par.
   * @param {string} symbol  p.ej. "OTC_EURUSD"
   * @param {"W"|"L"} result
   * @param {object}  meta   {entryPrice, closePrice, signalType, qualityScore}
   */
  const addResult = useCallback((symbol, result, meta = {}) => {
    const k    = storageKey(symbol);
    const prev = (() => {
      try { return JSON.parse(localStorage.getItem(k) || "{}"); } catch { return {}; }
    })();

    const entries = [
      ...(prev.entries || []),
      { r: result, ts: Date.now(), ...meta },
    ].slice(-MAX_HIST);

    const wins     = entries.filter(e => e.r === "W").length;
    const winRate  = Math.round((wins / entries.length) * 100);
    const data     = { entries, winRate, updatedAt: Date.now() };

    localStorage.setItem(k, JSON.stringify(data));
    setHistories(prev2 => ({ ...prev2, [symbol]: data }));
    return data;
  }, []);

  const getHistory = useCallback((symbol) => {
    return histories[symbol] ?? { entries: [], winRate: 0 };
  }, [histories]);

  const clearSymbol = useCallback((symbol) => {
    localStorage.removeItem(storageKey(symbol));
    setHistories(prev => {
      const next = { ...prev };
      delete next[symbol];
      return next;
    });
  }, []);

  const clearAll = useCallback(() => {
    const keys = [];
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k?.startsWith(PREFIX)) keys.push(k);
    }
    keys.forEach(k => localStorage.removeItem(k));
    setHistories({});
  }, []);

  return { histories, addResult, getHistory, clearSymbol, clearAll };
}

