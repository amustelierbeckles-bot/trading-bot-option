import { useState } from "react";
import { Shield, ShieldOff, TrendingUp, TrendingDown, DollarSign, ChevronDown, ChevronUp, RefreshCw } from "lucide-react";

export default function RiskPanel({
  config,
  updateConfig,
  riskStatus,
  isBlocked,
  cooldownFormatted,
  startNewSession,
  refresh,
}) {
  const [expanded, setExpanded] = useState(false);

  const streak       = riskStatus?.streak;
  const sizing       = riskStatus?.sizing;
  const cb           = riskStatus?.circuit_breaker;
  const sessionWR    = riskStatus?.session_win_rate;

  // ── Colores de racha ────────────────────────────────────────────────────────
  const streakColor = () => {
    if (!streak || streak.type === "none") return "text-gray-400";
    if (streak.type === "W") return streak.count >= 3 ? "text-green-400" : "text-green-300";
    return streak.count >= 3 ? "text-red-400" : "text-red-300";
  };

  const streakIcon = () => {
    if (!streak || streak.type === "none") return "—";
    const icon = streak.type === "W" ? "▲" : "▼";
    return `${icon}${streak.count} ${streak.type}`;
  };

  return (
    <div className={`rounded-lg border transition-all ${
      isBlocked
        ? "bg-red-950/40 border-red-700"
        : "bg-black/90 border-[rgba(224,224,224,0.12)]"
    }`}>
      {/* Barra compacta siempre visible — alta densidad */}
      <div
        className="flex items-center justify-between px-3 py-1.5 cursor-pointer"
        onClick={() => setExpanded(e => !e)}
      >
        <div className="flex items-center gap-3">
          {isBlocked
            ? <ShieldOff className="w-4 h-4 text-red-400 flex-shrink-0" />
            : <Shield    className="w-4 h-4 text-green-400 flex-shrink-0" />
          }

          {/* Estado */}
          <span className={`text-xs font-mono font-bold ${isBlocked ? "text-red-400" : "text-green-400"}`}>
            {isBlocked ? "🛑 BLOQUEADO" : "✅ OK"}
          </span>

          {/* Cooldown */}
          {cooldownFormatted && (
            <span className="text-xs font-mono text-red-300 bg-red-900/40 px-2 py-0.5 rounded border border-red-700">
              Reanuda en {cooldownFormatted}
            </span>
          )}

          {/* Divider */}
          <span className="text-gray-700 text-xs">|</span>

          {/* Racha */}
          <span className={`text-xs font-mono font-bold ${streakColor()}`}>
            Racha: {streakIcon()}
          </span>

          {streak?.last_3?.length > 0 && (
            <div className="flex gap-0.5">
              {streak.last_3.map((r, i) => (
                <span key={i} className={`text-xs font-mono font-bold px-1 rounded ${
                  r === "W" ? "text-green-400 bg-green-900/30" : "text-red-400 bg-red-900/30"
                }`}>{r}</span>
              ))}
            </div>
          )}

          {/* Divider */}
          <span className="text-gray-700 text-xs">|</span>

          {/* Apuesta sugerida */}
          {sizing && (
            <span className="text-xs font-mono text-blue-300">
              Apuesta: <span className="font-bold">${sizing.suggested_amount}</span>
              <span className="text-gray-500 ml-1">({sizing.risk_pct_effective}%)</span>
            </span>
          )}

          {/* WR sesión */}
          {sessionWR !== null && sessionWR !== undefined && (
            <>
              <span className="text-gray-700 text-xs">|</span>
              <span className={`text-xs font-mono ${sessionWR >= 55 ? "text-green-400" : sessionWR >= 45 ? "text-yellow-400" : "text-red-400"}`}>
                Sesión WR: {sessionWR}%
              </span>
            </>
          )}
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={e => { e.stopPropagation(); refresh(); }}
            className="text-gray-600 hover:text-gray-400 transition-colors"
          >
            <RefreshCw className="w-3 h-3" />
          </button>
          {expanded ? <ChevronUp className="w-3 h-3 text-gray-600" /> : <ChevronDown className="w-3 h-3 text-gray-600" />}
        </div>
      </div>

      {/* Panel expandido */}
      {expanded && (
        <div className="border-t border-[rgba(224,224,224,0.08)] px-3 py-3 space-y-3">

          {/* Circuit Breaker activo */}
          {isBlocked && cb?.reason && (
            <div className="bg-red-900/30 border border-red-700 rounded-lg p-3">
              <p className="text-red-300 text-sm font-mono">{cb.reason}</p>
              {cooldownFormatted && (
                <p className="text-red-400 text-xs mt-1 font-mono">
                  Reanuda en: <span className="font-bold text-lg">{cooldownFormatted}</span>
                </p>
              )}
              <p className="text-gray-500 text-xs mt-2 font-mono">
                El Revenge Trading destruye cuentas. Usa este tiempo para analizar qué salió mal.
              </p>
            </div>
          )}

          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {/* Balance */}
            <div className="space-y-1">
              <label className="text-xs text-gray-500 font-mono">Balance ($)</label>
              <input
                type="number"
                value={config.balance}
                onChange={e => updateConfig({ balance: parseFloat(e.target.value) || 0 })}
                className="w-full bg-gray-800 border border-gray-600 rounded px-2 py-1.5 text-sm font-mono text-white focus:outline-none focus:border-blue-500"
                min="1"
                step="10"
              />
            </div>

            {/* Riesgo % */}
            <div className="space-y-1">
              <label className="text-xs text-gray-500 font-mono">Riesgo por op (%)</label>
              <input
                type="number"
                value={config.risk_pct}
                onChange={e => updateConfig({ risk_pct: parseFloat(e.target.value) || 1 })}
                className="w-full bg-gray-800 border border-gray-600 rounded px-2 py-1.5 text-sm font-mono text-white focus:outline-none focus:border-blue-500"
                min="0.5"
                max="10"
                step="0.5"
              />
            </div>

            {/* Apuesta sugerida */}
            {sizing && (
              <div className="space-y-1">
                <label className="text-xs text-gray-500 font-mono">Apuesta sugerida</label>
                <div className="bg-gray-800 border border-gray-600 rounded px-2 py-1.5">
                  <span className={`text-sm font-mono font-bold ${
                    sizing.multiplier > 1 ? "text-green-400" : sizing.multiplier < 1 ? "text-red-400" : "text-white"
                  }`}>
                    ${sizing.suggested_amount}
                  </span>
                  <span className="text-xs text-gray-500 ml-1">({sizing.risk_pct_effective}%)</span>
                </div>
                <p className="text-xs text-gray-600 font-mono">{sizing.multiplier_reason}</p>
              </div>
            )}

            {/* Nueva sesión */}
            <div className="space-y-1">
              <label className="text-xs text-gray-500 font-mono">Sesión</label>
              <button
                onClick={startNewSession}
                className="w-full bg-gray-800 border border-gray-600 hover:border-blue-500 rounded px-2 py-1.5 text-xs font-mono text-gray-300 hover:text-white transition-all"
              >
                🔄 Nueva Sesión
              </button>
              <p className="text-xs text-gray-600 font-mono">
                {riskStatus?.session_trades || 0} ops en sesión
              </p>
            </div>
          </div>

          {/* Stats rápidas de sesión */}
          {riskStatus && (
            <div className="flex gap-4 text-xs font-mono text-gray-500">
              <span>Sesión: <span className="text-white">{riskStatus.session_trades} ops</span></span>
              <span className="text-green-400">✅ {riskStatus.session_wins}W</span>
              <span className="text-red-400">❌ {riskStatus.session_losses}L</span>
              {sessionWR !== null && sessionWR !== undefined &&
                <span className={sessionWR >= 55 ? "text-green-400" : "text-red-400"}>WR: {sessionWR}%</span>
              }
              {cb && !cb.triggered && (
                <span className="text-gray-600">Pérdidas consec.: {cb.consecutive_losses}</span>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
