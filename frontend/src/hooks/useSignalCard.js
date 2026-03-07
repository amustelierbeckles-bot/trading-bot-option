/**
 * useSignalCard.js — Estado y handlers de SignalCard
 */
import { useState, useEffect } from "react";
import { differenceInSeconds } from "date-fns";
import { toast } from "sonner";
import {
  SIGNAL_DURATION_SECONDS, EXPIRY_MINUTES, BACKEND_URL,
  getAssetSearchName, openPocketOption,
} from "../utils/signalCardUtils";
import { appendWLResult } from "../utils/wlHistory";

export default function useSignalCard(signal, onOperate) {
  const [timeRemaining, setTimeRemaining] = useState(null);
  const [hovered,       setHovered]       = useState(false);
  const [tradeResult,   setTradeResult]   = useState(null); // "win" | "loss" | "saving"

  // ── Countdown ────────────────────────────────────────────────────────────
  useEffect(() => {
    const calc = () => {
      const raw        = signal.timestamp;
      const utcStr     = raw.endsWith("Z") || raw.includes("+") ? raw : raw + "Z";
      const signalTime = new Date(utcStr);
      const elapsed    = differenceInSeconds(new Date(), signalTime);
      const left       = Math.max(0, SIGNAL_DURATION_SECONDS - elapsed);
      setTimeRemaining({
        total:      left,
        minutes:    Math.floor(left / 60),
        seconds:    left % 60,
        percentage: (left / SIGNAL_DURATION_SECONDS) * 100,
      });
    };
    calc();
    const id = setInterval(calc, 1000);
    return () => clearInterval(id);
  }, [signal.timestamp]);

  // ── Copiar nombre del activo ──────────────────────────────────────────────
  const copyAssetName = async (e) => {
    e.stopPropagation();
    try { await navigator.clipboard.writeText(getAssetSearchName(signal.symbol)); }
    catch (err) { console.error("Clipboard error:", err); }
  };

  // ── Registrar resultado ───────────────────────────────────────────────────
  const registerResult = async (result) => {
    if (tradeResult) return;
    setTradeResult("saving");
    try {
      await fetch(`${BACKEND_URL}/api/trades`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          signal_id:        signal.id || signal.timestamp,
          symbol:           signal.symbol,
          asset_name:       signal.asset_name,
          signal_type:      signal.type,
          result,
          entry_price:      signal.entry_price || signal.price || 0,
          payout:           signal.payout || 85,
          quality_score:    signal.quality_score || 0,
          cci:              signal.cci || 0,
          signal_timestamp: signal.timestamp,
        }),
      });
      setTradeResult(result);
      // Persiste en localStorage → dispara wl-update → PairCard se actualiza
      appendWLResult(signal.symbol, result, {
        quality_score: signal.quality_score || 0,
        signal_type:   signal.type || signal.signal_type || "",
      });
      toast.success(
        result === "win" ? "✅ ¡Operación ganadora registrada!" : "📊 Operación registrada",
        { duration: 3000 }
      );
    } catch {
      setTradeResult(null);
      toast.error("Error al registrar operación");
    }
  };

  // ── Trigger de operación ─────────────────────────────────────────────────
  const triggerOperation = async () => {
    onOperate?.(signal);
    await openPocketOption(signal.asset_name, signal.symbol);
    toast.success(
      `"${signal.asset_name}" copiado — Pega en PO y pon expiración: ${EXPIRY_MINUTES} min`,
      { duration: 9000, icon: (signal.type === "CALL" || signal.type === "BUY") ? "📈" : "📉" }
    );
  };

  const isExpiring     = timeRemaining && timeRemaining.total < 20;
  const handleCardClick  = (e) => { if (e.target.closest("[data-no-redirect]")) return; if (!isExpiring) triggerOperation(); };
  const handleOperateNow = (e) => { e.stopPropagation(); triggerOperation(); };

  return {
    timeRemaining, hovered, tradeResult,
    setHovered, setTradeResult,
    copyAssetName, registerResult,
    handleCardClick, handleOperateNow,
    isExpiring,
  };
}
