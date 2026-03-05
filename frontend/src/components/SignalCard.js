/**
 * SignalCard.js — Tarjeta de señal de trading
 * Solo JSX. Lógica en useSignalCard.js · Constantes en signalCardUtils.js
 */
import {
  TrendingUp, TrendingDown, Clock, Timer, Percent, Sparkles,
  ExternalLink, TimerReset, Copy, MousePointerClick,
  CheckCircle2, XCircle, RotateCcw,
} from "lucide-react";
import { Badge }   from "@/components/ui/badge";
import { Button }  from "@/components/ui/button";
import useSignalCard from "../hooks/useSignalCard";
import {
  EXPIRY_MINUTES,
  getPayoutColor, getQualityBadge, getTimeColor,
  getAssetSearchName, formatTimestampUTC5,
} from "../utils/signalCardUtils";

export default function SignalCard({ signal, onOperate }) {
  const isCall     = signal.type === "CALL" || signal.type === "BUY";
  const Icon       = isCall ? TrendingUp : TrendingDown;
  const colorClass = isCall ? "buy" : "sell";

  const {
    timeRemaining, hovered, tradeResult,
    setHovered, setTradeResult,
    copyAssetName, registerResult,
    handleCardClick, handleOperateNow,
    isExpiring,
  } = useSignalCard(signal, onOperate);

  const qualityBadge = getQualityBadge(signal.market_quality || 75);

  if (timeRemaining && timeRemaining.total === 0) return null;

  return (
    <div
      data-testid={`signal-card-${signal.type.toLowerCase()}`}
      onClick={handleCardClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      className={`
        signal-card ${colorClass} relative overflow-hidden
        bg-card/50 backdrop-blur-sm border rounded-lg p-4
        transition-all duration-200 select-none
        ${!isExpiring ? "cursor-pointer" : "cursor-not-allowed opacity-70"}
        ${hovered && !isExpiring
          ? isCall
            ? "border-buy/60 bg-buy/5 shadow-[0_0_20px_rgba(0,255,148,0.12)] scale-[1.01]"
            : "border-sell/60 bg-sell/5 shadow-[0_0_20px_rgba(255,0,85,0.12)] scale-[1.01]"
          : "hover:bg-card"
        }
      `}
    >
      {/* Indicador hover */}
      {hovered && !isExpiring && (
        <div className={`absolute top-2 right-2 flex items-center gap-1 text-[10px] font-mono px-1.5 py-0.5 rounded-full
          ${isCall ? "bg-buy/20 text-buy" : "bg-sell/20 text-sell"}`}>
          <MousePointerClick className="w-3 h-3" />
          Clic para operar
        </div>
      )}

      {/* Glow dot */}
      {!hovered && (
        <div className="absolute top-4 right-4">
          <div className={`glow-dot ${colorClass}`} />
        </div>
      )}

      {/* ── Encabezado ─────────────────────────────────────────────────────── */}
      <div className={`-mx-4 -mt-4 mb-3 px-4 py-2 rounded-t-lg flex items-center justify-between
        ${isCall ? "bg-buy/10 border-b border-buy/20" : "bg-sell/10 border-b border-sell/20"}`}>
        <div className="flex items-center gap-2">
          <Icon className={`w-4 h-4 ${isCall ? "text-buy" : "text-sell"}`} />
          <span className={`font-heading font-black text-base tracking-tight ${isCall ? "text-buy" : "text-sell"}`}>
            {signal.asset_name || signal.symbol}
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <Badge variant="outline"
            className={`text-xs font-mono font-bold px-2
              ${isCall ? "bg-buy/20 text-buy border-buy/40" : "bg-sell/20 text-sell border-sell/40"}`}
            data-testid="signal-type-badge">
            {signal.type}
          </Badge>
          <Badge variant="outline"
            className="text-xs font-mono bg-pink-500/10 text-pink-400 border-pink-500/30"
            data-testid="signal-timeframe-badge"
            title="Expiración recomendada en Pocket Option">
            <Timer className="w-3 h-3 mr-1" />
            Exp: {EXPIRY_MINUTES}min
          </Badge>
        </div>
      </div>

      {/* ── Métricas ───────────────────────────────────────────────────────── */}
      <div className="flex-1 space-y-1">
        {[
          { label: "Precio:", value: <span className="text-sm font-mono font-bold text-foreground" data-testid="signal-price">${(signal.entry_price || signal.price || 0).toFixed(5)}</span> },
          { label: "CCI:",    value: <span className="text-sm font-mono font-bold text-primary" data-testid="signal-cci">{(signal.cci || 0).toFixed(1)}</span> },
          { label: "Payout:", value: <span className={`text-sm font-mono ${getPayoutColor(signal.payout || 85)}`} data-testid="signal-payout"><Percent className="w-3 h-3 inline mr-1" />{(signal.payout || 85).toFixed(1)}%</span> },
          { label: "Calidad:", value: <Badge variant="outline" className={`text-xs font-mono ${qualityBadge.color}`} data-testid="signal-quality-badge"><Sparkles className="w-3 h-3 mr-1" />{qualityBadge.text}</Badge> },
        ].map(({ label, value }) => (
          <div key={label} className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground font-mono">{label}</span>
            {value}
          </div>
        ))}

        {/* Tiempo restante */}
        {timeRemaining && (
          <div className="flex items-center justify-between mt-2 pt-2 border-t border-border/50">
            <span className="text-xs text-muted-foreground font-mono flex items-center gap-1">
              <TimerReset className="w-3 h-3" />
              Señal válida por:
            </span>
            <span className={`text-sm font-mono font-bold ${getTimeColor(timeRemaining)}`} data-testid="signal-time-remaining">
              {timeRemaining.minutes > 0
                ? `${timeRemaining.minutes}m ${timeRemaining.seconds.toString().padStart(2, "0")}s`
                : `${timeRemaining.seconds}s`}
            </span>
          </div>
        )}

        {/* ── Razón + Acciones ───────────────────────────────────────────── */}
        <div className="mt-3 pt-3 border-t border-border">
          <p className="text-xs text-muted-foreground font-mono leading-relaxed mb-3">{signal.reason}</p>

          {/* Buscar en PO */}
          <div data-no-redirect className="bg-background/50 border border-border rounded-lg p-2 mb-3">
            <div className="flex items-center justify-between">
              <span className="text-xs text-muted-foreground font-mono">Buscar en Pocket Option:</span>
              <button onClick={copyAssetName} data-no-redirect
                className="text-xs text-primary hover:text-primary/80 font-mono flex items-center gap-1"
                title="Copiar nombre del activo">
                <Copy className="w-3 h-3" /> Copiar
              </button>
            </div>
            <p className="text-lg font-bold font-mono text-center mt-1"
              style={{ color: isCall ? "#00FF94" : "#FF0055" }}>
              {getAssetSearchName(signal.symbol)}
            </p>
          </div>

          {/* Botón principal */}
          <Button onClick={handleOperateNow} data-no-redirect disabled={isExpiring}
            className={`w-full font-mono font-bold shadow-lg transition-all hover:scale-[1.02]
              ${isCall ? "bg-buy hover:bg-buy/90 text-black" : "bg-sell hover:bg-sell/90 text-white"}`}
            data-testid="operate-now-button">
            <ExternalLink className="w-4 h-4 mr-2" />
            {isExpiring ? "Señal Expirada" : `Abrir Pocket Option → ${EXPIRY_MINUTES}min`}
          </Button>

          {isExpiring && (
            <p className="text-xs text-sell font-mono mt-1 text-center">
              Señal por expirar — espera nuevo escaneo
            </p>
          )}

          {/* ── Registro de resultado ─────────────────────────────────────── */}
          <div data-no-redirect className="mt-3 pt-3 border-t border-border/50">
            {!tradeResult || tradeResult === "saving" ? (
              <>
                <p className="text-[10px] text-muted-foreground font-mono text-center mb-2 uppercase tracking-wider">
                  ¿Cuál fue el resultado?
                </p>
                <div className="grid grid-cols-2 gap-2">
                  {[
                    { result: "win",  label: "Gané ✅",   cls: "buy" },
                    { result: "loss", label: "Perdí ❌",  cls: "sell" },
                  ].map(({ result, label, cls }) => (
                    <button key={result} data-no-redirect
                      onClick={() => registerResult(result)}
                      disabled={tradeResult === "saving"}
                      className={`flex items-center justify-center gap-1.5 py-2 rounded-lg text-xs font-mono font-bold
                        bg-${cls}/10 text-${cls} border border-${cls}/30
                        hover:bg-${cls}/20 hover:border-${cls}/60
                        disabled:opacity-50 transition-all`}>
                      {result === "win" ? <CheckCircle2 className="w-3.5 h-3.5" /> : <XCircle className="w-3.5 h-3.5" />}
                      {label}
                    </button>
                  ))}
                </div>
              </>
            ) : (
              <div className={`flex items-center justify-between rounded-lg px-3 py-2
                ${tradeResult === "win" ? "bg-buy/10 border border-buy/30" : "bg-sell/10 border border-sell/30"}`}>
                <span className={`text-xs font-mono font-bold ${tradeResult === "win" ? "text-buy" : "text-sell"}`}>
                  {tradeResult === "win" ? "✅ Ganaste" : "❌ Perdiste"} — registrado
                </span>
                <button data-no-redirect onClick={() => setTradeResult(null)}
                  className="text-muted-foreground hover:text-foreground transition-colors" title="Cambiar resultado">
                  <RotateCcw className="w-3 h-3" />
                </button>
              </div>
            )}
          </div>
        </div>

        {/* Timestamp UTC-5 */}
        <div className="flex items-center gap-1 mt-2 text-xs text-muted-foreground font-mono">
          <Clock className="w-3 h-3" />
          <span data-testid="signal-timestamp">{formatTimestampUTC5(signal.timestamp)}</span>
        </div>
      </div>
    </div>
  );
}
