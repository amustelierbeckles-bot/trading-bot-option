/**
 * ActiveSignalBanner — Panel flotante bottom-right
 *
 * Sincronizado con TradingClockOverlay mediante signalTime.js
 * Muestra badge 🔥 para señales FIRE (quality_score > 0.90 o 3+ estrategias)
 */
import { useState, useEffect } from "react";
import { TrendingUp, TrendingDown, ExternalLink, X, Copy } from "lucide-react";
import { toast } from "sonner";
import {
  getSecondsLeft,
  formatTime,
  SIGNAL_DURATION,
  isSignalLive,
} from "../utils/signalTime";
import { getSignalPriority } from "../hooks/useSignalNotifier";
import {
  openPocketOption as openPO,
  getPOMode,
  setPOMode,
} from "../utils/signalCardUtils";

const EXPIRY_MINUTES = 2;

async function openPocketOption(signal) {
  const { mode } = await openPO(signal.asset_name, signal.symbol);
  toast.success(
    `✅ ${signal.asset_name} abierto en PO (${mode === "real" ? "REAL" : "DEMO"}) · ${EXPIRY_MINUTES} min`,
    { duration: 6000 }
  );
}

export default function ActiveSignalBanner({
  signals = [],
  onOperate,
  isBlocked = false,
  cooldownFormatted = null,
  pairWinRates = {},
  suggestedAmount = null,
}) {
  // Señal activa más reciente que aún tenga tiempo
  const activeSignal = signals.find(s => isSignalLive(s)) ?? null;

  const [secsLeft,  setSecsLeft]  = useState(activeSignal ? getSecondsLeft(activeSignal.timestamp) : 0);
  const [dismissed, setDismissed] = useState(false);
  const [prevId,    setPrevId]    = useState(null);
  const [poMode,    setPoMode]    = useState(() => getPOMode());

  // Reset dismissed cuando llega señal nueva
  useEffect(() => {
    const id = activeSignal?.id ?? null;
    if (id && id !== prevId) {
      setDismissed(false);
      setPrevId(id);
    }
  }, [activeSignal, prevId]);

  // Tick — usa la misma función que TradingClockOverlay
  useEffect(() => {
    if (!activeSignal) return;
    const tick = () => setSecsLeft(getSecondsLeft(activeSignal.timestamp));
    tick();
    const id = setInterval(tick, 250);
    return () => clearInterval(id);
  }, [activeSignal]);

  if (!activeSignal || dismissed || secsLeft <= 0) return null;

  const isCall   = activeSignal.type === "CALL" || activeSignal.type === "BUY";
  const Icon     = isCall ? TrendingUp : TrendingDown;
  const priority = getSignalPriority(activeSignal);

  // Degradación de señal: si el par tiene WR < 50% en 30min → baja prioridad
  const pairWR       = pairWinRates[activeSignal.symbol];
  const isDegraded   = pairWR?.degraded === true && pairWR?.trades >= 3;
  const isFire       = priority === "fire" && !isDegraded;

  const pct          = (secsLeft / SIGNAL_DURATION) * 100;

  const ringColor = secsLeft > 60
    ? (isFire ? "#FF6B00" : isCall ? "#00FF94" : "#FF0055")
    : secsLeft > 20 ? "#FACC15" : "#EF4444";

  const borderColor = isFire
    ? "rgba(255,107,0,0.55)"
    : isCall ? "rgba(0,255,148,0.4)" : "rgba(255,0,85,0.4)";

  const glowShadow = isFire
    ? "0 0 30px rgba(255,107,0,0.35)"
    : isCall ? "0 0 30px rgba(0,255,148,0.2)" : "0 0 30px rgba(255,0,85,0.2)";

  return (
    <div
      className="fixed bottom-6 right-6 z-50 w-72 rounded-xl shadow-2xl border overflow-hidden"
      style={{
        background:     "rgba(10,10,10,0.95)",
        backdropFilter: "blur(20px)",
        borderColor,
        boxShadow:      glowShadow,
      }}
    >
      {/* Barra de progreso superior */}
      <div className="h-1 w-full bg-white/10">
        <div
          className="h-1 transition-all duration-300"
          style={{ width: `${pct}%`, background: ringColor, boxShadow: `0 0 8px ${ringColor}` }}
        />
      </div>

      {/* Encabezado */}
      <div
        className="flex items-center justify-between px-4 py-2"
        style={{ background: isFire ? "rgba(255,107,0,0.08)" : isCall ? "rgba(0,255,148,0.08)" : "rgba(255,0,85,0.08)" }}
      >
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full animate-pulse" style={{ background: ringColor }} />
          <span className="text-[10px] font-mono uppercase tracking-widest text-white/60">
            {isFire ? "🔥 Señal Élite" : "Señal activa"}
          </span>
        </div>
        <button onClick={() => setDismissed(true)} className="text-white/30 hover:text-white/70 transition-colors">
          <X className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Cuerpo */}
      <div className="px-4 py-3 space-y-3">
        {/* Par + dirección */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Icon className="w-5 h-5" style={{ color: ringColor }} />
            <span className="font-black font-heading text-lg tracking-tight text-white">
              {activeSignal.asset_name}
            </span>
            {isFire && <span className="text-base" title="Señal de alta confluencia">🔥</span>}
          </div>
          <span
            className="text-sm font-mono font-bold px-2 py-0.5 rounded"
            style={{ background: `${ringColor}20`, color: ringColor }}
          >
            {activeSignal.type}
          </span>
        </div>

        {/* Métricas */}
        <div className="grid grid-cols-4 gap-1.5 text-center">
          {[
            { label: "Payout",      value: `${(activeSignal.payout || 85).toFixed(0)}%` },
            { label: "CCI",         value: (activeSignal.cci || 0).toFixed(0) },
            { label: "Score",       value: `${((activeSignal.quality_score ?? 0) * 100).toFixed(0)}%` },
            { label: "Exp.",        value: `${EXPIRY_MINUTES}m` },
          ].map(({ label, value }) => (
            <div key={label} className="bg-white/5 rounded-lg py-1">
              <p className="text-[9px] text-white/40 font-mono">{label}</p>
              <p className="text-xs font-bold font-mono text-white">{value}</p>
            </div>
          ))}
        </div>

        {/* Countdown sincronizado */}
        <div className="flex items-center justify-between">
          <span className="text-xs text-white/40 font-mono">Señal válida:</span>
          <span className="text-xl font-black font-mono tabular-nums" style={{ color: ringColor }}>
            {formatTime(secsLeft)}
          </span>
        </div>

        {/* Razón */}
        <p className="text-[11px] text-white/50 font-mono leading-tight line-clamp-2">
          {activeSignal.reason}
        </p>

        {/* Degradación de señal por WR bajo del par */}
        {isDegraded && (
          <div className="bg-yellow-900/30 border border-yellow-700/50 rounded-lg px-3 py-1.5">
            <p className="text-yellow-400 text-[10px] font-mono">
              ⚠️ Par degradado — WR {pairWR.win_rate}% en últimos 30min ({pairWR.trades} ops)
            </p>
          </div>
        )}

        {/* Monto sugerido */}
        {suggestedAmount && (
          <div className="text-center">
            <span className="text-[10px] text-white/40 font-mono">Apuesta sugerida: </span>
            <span className="text-[11px] text-blue-300 font-mono font-bold">${suggestedAmount}</span>
          </div>
        )}

        {/* Toggle Demo / Real */}
        <div className="flex items-center justify-between mb-1">
          <span className="text-[10px] text-white/40 font-mono">Cuenta:</span>
          <div className="flex rounded-md overflow-hidden border border-white/10 text-[10px] font-mono font-bold">
            <button
              onClick={() => { setPOMode("demo"); setPoMode("demo"); }}
              className="px-2 py-0.5 transition-colors"
              style={{
                background: poMode === "demo" ? "#FACC15" : "transparent",
                color:      poMode === "demo" ? "#000"    : "#888",
              }}
            >DEMO</button>
            <button
              onClick={() => { setPOMode("real"); setPoMode("real"); }}
              className="px-2 py-0.5 transition-colors"
              style={{
                background: poMode === "real" ? "#00FF94" : "transparent",
                color:      poMode === "real" ? "#000"    : "#888",
              }}
            >REAL</button>
          </div>
        </div>

        {/* Botón "Abrir PO" — bloqueado si circuit breaker activo */}
        {isBlocked ? (
          <div className="w-full py-2.5 rounded-lg bg-red-950/80 border border-red-700 text-center">
            <p className="text-red-400 font-mono font-bold text-sm">🛑 OPERACIÓN BLOQUEADA</p>
            {cooldownFormatted && (
              <p className="text-red-300 text-xs font-mono mt-0.5">
                Circuit Breaker — Reanuda en {cooldownFormatted}
              </p>
            )}
          </div>
        ) : (
          <button
            onClick={async () => {
              onOperate?.(activeSignal);
              await openPocketOption(activeSignal);
            }}
            className="w-full py-2.5 rounded-lg font-mono font-bold text-sm flex items-center justify-center gap-2 transition-all hover:scale-[1.02] active:scale-[0.98]"
            style={{
              background: isFire ? "#FF6B00" : isCall ? "#00FF94" : "#FF0055",
              color:      isFire ? "#fff"    : isCall ? "#000"    : "#fff",
              boxShadow:  isFire ? "0 0 20px rgba(255,107,0,0.5)" : undefined,
            }}
          >
            <ExternalLink className="w-4 h-4" />
            {isFire ? "🔥 " : isDegraded ? "⚠️ " : ""}
            Abrir {poMode === "real" ? "🟢 REAL" : "🟡 DEMO"} — {activeSignal.asset_name}
          </button>
        )}

        <p className="text-[10px] text-white/30 font-mono text-center">
          Un clic → PO abre con el par preseleccionado
        </p>
      </div>
    </div>
  );
}


