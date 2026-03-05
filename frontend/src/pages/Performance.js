import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { TrendingUp, TrendingDown, Target, Zap, BarChart3, RefreshCw, AlertTriangle, CheckCircle, Activity, Clock } from "lucide-react";
import { toast } from "sonner";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

export default function Performance() {
  const [stats,        setStats]        = useState(null);
  const [calibration,  setCalibration]  = useState(null);
  const [execution,    setExecution]    = useState(null);
  const [loadingStats, setLoadingStats] = useState(false);
  const [loadingCal,   setLoadingCal]   = useState(false);
  const [loadingExec,  setLoadingExec]  = useState(false);
  const [period,       setPeriod]       = useState(30);

  const fetchStats = useCallback(async () => {
    setLoadingStats(true);
    try {
      const { data } = await axios.get(`${API}/trades/stats?days=${period}`);
      setStats(data);
    } catch {
      toast.error("Error cargando estadísticas");
    } finally {
      setLoadingStats(false);
    }
  }, [period]);

  const fetchCalibration = useCallback(async () => {
    setLoadingCal(true);
    try {
      const { data } = await axios.get(`${API}/calibration`);
      setCalibration(data);
      if (data.calibrated) {
        toast.success(`Calibración aplicada — umbral: ${data.optimal_threshold.toFixed(2)}`);
      }
    } catch {
      toast.error("Error en calibración");
    } finally {
      setLoadingCal(false);
    }
  }, []);

  const fetchExecution = useCallback(async () => {
    setLoadingExec(true);
    try {
      const { data } = await axios.get(`${API}/performance/execution?days=${period}`);
      setExecution(data);
    } catch {
      // silencioso — sección aparece cuando haya datos
    } finally {
      setLoadingExec(false);
    }
  }, [period]);

  useEffect(() => { fetchStats(); fetchExecution(); }, [fetchStats, fetchExecution]);
  useEffect(() => { fetchCalibration(); }, [fetchCalibration]);

  // ── Helpers ─────────────────────────────────────────────────────────────────
  const wrColor = (wr) => {
    if (wr === null || wr === undefined) return "text-gray-500";
    if (wr >= 60) return "text-green-400";
    if (wr >= 55) return "text-yellow-400";
    return "text-red-400";
  };

  const wrBg = (wr) => {
    if (wr === null || wr === undefined) return "bg-gray-800/40 border-gray-700";
    if (wr >= 55) return "bg-green-900/20 border-green-700/50";
    return "bg-red-900/20 border-red-700/50";
  };

  const pfColor = (pf) => {
    if (pf >= 1.3) return "text-green-400";
    if (pf >= 1.0) return "text-yellow-400";
    return "text-red-400";
  };

  // ── Mini bar ────────────────────────────────────────────────────────────────
  const WRBar = ({ wr }) => {
    if (wr === null || wr === undefined) return <span className="text-gray-600 text-xs">Sin datos</span>;
    const pct = Math.min(wr, 100);
    const color = wr >= 55 ? "bg-green-500" : "bg-red-500";
    return (
      <div className="flex items-center gap-2">
        <div className="flex-1 bg-gray-800 rounded-full h-1.5">
          <div className={`${color} h-1.5 rounded-full transition-all`} style={{ width: `${pct}%` }} />
        </div>
        <span className={`text-xs font-mono font-bold ${wrColor(wr)}`}>{wr}%</span>
      </div>
    );
  };

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      {/* Header */}
      <header className="border-b border-gray-800 bg-black/60 backdrop-blur px-6 py-4">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Target className="w-7 h-7 text-purple-400" />
            <h1 className="text-xl font-bold tracking-tight">RENDIMIENTO & CALIBRACIÓN</h1>
            <span className="text-xs bg-purple-500/20 text-purple-400 border border-purple-500/30 px-2 py-0.5 rounded font-mono">
              WIN RATE REAL
            </span>
          </div>
          <button
            onClick={() => window.location.href = '/'}
            className="text-sm text-gray-400 hover:text-white border border-gray-700 hover:border-gray-500 px-3 py-1.5 rounded-lg transition-all"
          >
            ← Dashboard
          </button>
        </div>
      </header>

      <main className="max-w-6xl mx-auto p-6 space-y-6">

        {/* Filtro de período */}
        <div className="flex items-center gap-3">
          <span className="text-xs text-gray-500 font-mono">Período:</span>
          {[7, 30, 90].map(d => (
            <button
              key={d}
              onClick={() => setPeriod(d)}
              className={`text-xs font-mono px-3 py-1 rounded-lg border transition-all ${
                period === d
                  ? "bg-purple-600 border-purple-500 text-white"
                  : "border-gray-700 text-gray-400 hover:border-gray-500"
              }`}
            >
              {d}d
            </button>
          ))}
          <button
            onClick={fetchStats}
            disabled={loadingStats}
            className="ml-auto text-xs text-gray-500 hover:text-white border border-gray-700 px-3 py-1 rounded-lg flex items-center gap-1 transition-all"
          >
            <RefreshCw className={`w-3 h-3 ${loadingStats ? "animate-spin" : ""}`} />
            Actualizar
          </button>
        </div>

        {/* KPIs globales */}
        {stats && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {[
              {
                label: "Win Rate Global",
                value: `${stats.win_rate}%`,
                sub: `${stats.total_wins}W / ${stats.total_losses}L`,
                color: wrColor(stats.win_rate),
                Icon: Target,
              },
              {
                label: "Profit Factor",
                value: stats.profit_factor,
                sub: stats.profit_factor >= 1.3 ? "✅ Rentable" : stats.profit_factor >= 1 ? "⚠️ Equilibrio" : "❌ Negativo",
                color: pfColor(stats.profit_factor),
                Icon: TrendingUp,
              },
              {
                label: "Total Operaciones",
                value: stats.total_trades,
                sub: `Últimos ${period} días`,
                color: "text-white",
                Icon: BarChart3,
              },
              {
                label: "Umbral activo",
                value: calibration ? calibration.current_threshold.toFixed(2) : "—",
                sub: calibration?.calibrated ? "🎯 Calibrado" : "⚙️ Por defecto",
                color: calibration?.calibrated ? "text-purple-400" : "text-gray-400",
                Icon: Zap,
              },
            ].map(({ label, value, sub, color, Icon }) => (
              <div key={label} className="bg-gray-900 border border-gray-700 rounded-xl p-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs text-gray-500 font-mono uppercase tracking-wider">{label}</span>
                  <Icon className="w-4 h-4 text-gray-600" />
                </div>
                <div className={`text-2xl font-bold font-mono ${color}`}>{value}</div>
                <div className="text-xs text-gray-500 mt-1 font-mono">{sub}</div>
              </div>
            ))}
          </div>
        )}

        {/* Sin trades */}
        {stats && stats.total_trades === 0 && (
          <div className="bg-gray-900 border border-gray-700 rounded-2xl p-10 text-center">
            <AlertTriangle className="w-10 h-10 text-yellow-500 mx-auto mb-3" />
            <p className="text-gray-400 font-mono text-sm">
              No hay operaciones registradas en los últimos {period} días.
              <br />Registra wins/losses desde el Dashboard para ver estadísticas reales.
            </p>
          </div>
        )}

        {/* Panel de Calibración */}
        {calibration && (
          <div className="bg-gray-900 border border-gray-700 rounded-2xl p-6">
            <div className="flex items-center justify-between mb-5">
              <div>
                <h2 className="text-sm font-mono text-gray-400 uppercase tracking-wider">
                  Calibración del Quality Score
                </h2>
                <p className="text-xs text-gray-600 mt-1 font-mono">
                  {calibration.total_trades} operaciones analizadas
                  {calibration.total_trades < calibration.min_trades_required &&
                    ` — necesitas ${calibration.min_trades_required - calibration.total_trades} más para calibrar`}
                </p>
              </div>
              <button
                onClick={fetchCalibration}
                disabled={loadingCal}
                className="flex items-center gap-2 text-xs border border-purple-700 text-purple-400 hover:bg-purple-900/30 px-3 py-1.5 rounded-lg transition-all"
              >
                <RefreshCw className={`w-3 h-3 ${loadingCal ? "animate-spin" : ""}`} />
                Recalibrar
              </button>
            </div>

            {/* Recomendación */}
            <div className={`p-4 rounded-xl mb-5 border ${
              calibration.calibrated
                ? "bg-purple-900/20 border-purple-700/50"
                : "bg-gray-800/50 border-gray-700"
            }`}>
              <div className="flex items-start gap-3">
                {calibration.calibrated
                  ? <CheckCircle className="w-5 h-5 text-purple-400 mt-0.5 flex-shrink-0" />
                  : <AlertTriangle className="w-5 h-5 text-yellow-500 mt-0.5 flex-shrink-0" />
                }
                <div>
                  <p className={`text-sm font-mono ${calibration.calibrated ? "text-purple-300" : "text-yellow-400"}`}>
                    {calibration.recommendation}
                  </p>
                  {calibration.calibrated && (
                    <p className="text-xs text-gray-500 mt-1 font-mono">
                      Umbral anterior: {calibration.current_threshold.toFixed(2)} →
                      Nuevo: <span className="text-purple-400 font-bold">{calibration.optimal_threshold.toFixed(2)}</span>
                      {" "}(aplicado automáticamente)
                    </p>
                  )}
                </div>
              </div>
            </div>

            {/* Tabla de buckets */}
            {calibration.buckets && calibration.buckets.length > 0 && (
              <div className="space-y-2">
                <p className="text-xs text-gray-500 font-mono uppercase tracking-wider mb-3">
                  Win Rate por rango de Quality Score
                </p>
                {calibration.buckets.map((b) => (
                  <div
                    key={b.range}
                    className={`p-3 rounded-lg border ${wrBg(b.win_rate)} ${
                      Math.abs(b.threshold_lo - calibration.optimal_threshold) < 0.01
                        ? "ring-1 ring-purple-500"
                        : ""
                    }`}
                  >
                    <div className="flex items-center justify-between mb-1.5">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-mono font-bold text-gray-300">{b.range}</span>
                        {Math.abs(b.threshold_lo - calibration.optimal_threshold) < 0.01 && (
                          <span className="text-xs bg-purple-600/50 text-purple-300 px-1.5 py-0.5 rounded font-mono">
                            UMBRAL ÓPTIMO
                          </span>
                        )}
                      </div>
                      <span className="text-xs text-gray-500 font-mono">
                        {b.total} ops ({b.wins}W / {b.total - b.wins}L)
                      </span>
                    </div>
                    <WRBar wr={b.win_rate} />
                    {!b.valid && b.total > 0 && (
                      <p className="text-xs text-gray-600 mt-1 font-mono">
                        Muestra pequeña — necesitas al menos 5 ops por rango
                      </p>
                    )}
                    {b.total === 0 && (
                      <p className="text-xs text-gray-600 mt-1 font-mono">Sin operaciones en este rango</p>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Win Rate por par */}
        {stats && stats.by_pair && Object.keys(stats.by_pair).length > 0 && (
          <div className="bg-gray-900 border border-gray-700 rounded-2xl p-6">
            <h2 className="text-sm font-mono text-gray-400 uppercase tracking-wider mb-4">
              Win Rate por Par de Divisas
            </h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {Object.entries(stats.by_pair)
                .sort(([, a], [, b]) => b.win_rate - a.win_rate)
                .map(([sym, data]) => (
                  <div key={sym} className={`p-3 rounded-lg border ${wrBg(data.win_rate)}`}>
                    <div className="flex items-center justify-between mb-1.5">
                      <span className="text-sm font-mono font-bold text-white">{data.asset_name || sym}</span>
                      <span className="text-xs text-gray-500 font-mono">{data.total} ops</span>
                    </div>
                    <WRBar wr={data.win_rate} />
                  </div>
                ))}
            </div>
          </div>
        )}

        {/* Win Rate por hora */}
        {stats && stats.by_hour && Object.keys(stats.by_hour).length > 0 && (
          <div className="bg-gray-900 border border-gray-700 rounded-2xl p-6">
            <h2 className="text-sm font-mono text-gray-400 uppercase tracking-wider mb-4">
              Win Rate por Hora (UTC)
            </h2>
            <div className="grid grid-cols-4 md:grid-cols-8 gap-2">
              {Object.entries(stats.by_hour)
                .sort(([a], [b]) => Number(a) - Number(b))
                .map(([hour, data]) => {
                  const isLondon = Number(hour) >= 8 && Number(hour) < 13;
                  const isOverlap = Number(hour) >= 13 && Number(hour) < 17;
                  const isNY = Number(hour) >= 17 && Number(hour) < 22;
                  return (
                    <div
                      key={hour}
                      className={`p-2 rounded-lg border text-center ${wrBg(data.win_rate)} ${
                        isOverlap ? "ring-1 ring-yellow-600/50" : ""
                      }`}
                    >
                      <div className="text-xs text-gray-500 font-mono">{hour}:00</div>
                      <div className={`text-sm font-bold font-mono ${wrColor(data.win_rate)}`}>
                        {data.win_rate}%
                      </div>
                      <div className="text-xs text-gray-600 font-mono">{data.total}op</div>
                      {isLondon   && <div className="text-xs text-blue-500 mt-0.5">LON</div>}
                      {isOverlap  && <div className="text-xs text-yellow-500 mt-0.5">L+NY</div>}
                      {isNY       && <div className="text-xs text-green-500 mt-0.5">NY</div>}
                    </div>
                  );
                })}
            </div>
            <p className="text-xs text-gray-600 mt-3 font-mono">
              Las horas con mejor rendimiento son las del solapamiento Londres+NY (13-17 UTC)
            </p>
          </div>
        )}

        {/* Últimas operaciones */}
        {stats && stats.last_trades && stats.last_trades.length > 0 && (
          <div className="bg-gray-900 border border-gray-700 rounded-2xl p-6">
            <h2 className="text-sm font-mono text-gray-400 uppercase tracking-wider mb-4">
              Últimas Operaciones Registradas
            </h2>
            <div className="space-y-2">
              {stats.last_trades.map((t, i) => (
                <div key={i} className="flex items-center justify-between py-2 border-b border-gray-800/50 last:border-0">
                  <div className="flex items-center gap-3">
                    <span className={`text-xs font-bold font-mono px-2 py-0.5 rounded ${
                      t.signal_type === "CALL"
                        ? "bg-green-900/50 text-green-400"
                        : "bg-red-900/50 text-red-400"
                    }`}>
                      {t.signal_type}
                    </span>
                    <span className="text-sm font-mono text-white">{t.asset_name || t.symbol}</span>
                  </div>
                  <div className="flex items-center gap-4">
                    <span className="text-xs text-gray-500 font-mono">
                      Score: {(t.quality_score * 100).toFixed(0)}%
                    </span>
                    <span className={`text-sm font-bold font-mono ${
                      t.result === "win" ? "text-green-400" : "text-red-400"
                    }`}>
                      {t.result === "win" ? "✅ WIN" : "❌ LOSS"}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
        {/* ── CALIDAD DE EJECUCIÓN ── */}
        {execution && execution.total_trades > 0 && (
          <div className="bg-gray-900 border border-gray-700 rounded-2xl p-6">
            <div className="flex items-center justify-between mb-5">
              <div className="flex items-center gap-3">
                <Activity className="w-5 h-5 text-cyan-400" />
                <h2 className="text-sm font-mono text-gray-400 uppercase tracking-wider">
                  Calidad de Ejecución
                </h2>
                <span className="text-xs bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 px-2 py-0.5 rounded font-mono">
                  MAE + LATENCIA
                </span>
              </div>
              <button
                onClick={fetchExecution}
                disabled={loadingExec}
                className="text-xs text-gray-500 hover:text-white border border-gray-700 px-3 py-1 rounded-lg flex items-center gap-1 transition-all"
              >
                <RefreshCw className={`w-3 h-3 ${loadingExec ? "animate-spin" : ""}`} />
                Actualizar
              </button>
            </div>

            {/* KPIs MAE + Latencia */}
            <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mb-6">
              <div className="bg-gray-800/60 border border-gray-700 rounded-xl p-4">
                <div className="text-xs text-gray-500 font-mono uppercase mb-2">MAE Promedio</div>
                <div className={`text-2xl font-bold font-mono ${
                  execution.mae_avg_pips === null ? "text-gray-500"
                  : execution.mae_avg_pips < 3   ? "text-green-400"
                  : execution.mae_avg_pips < 6   ? "text-yellow-400"
                  : "text-red-400"
                }`}>
                  {execution.mae_avg_pips !== null ? `${execution.mae_avg_pips} pips` : "—"}
                </div>
                <div className="text-xs text-gray-500 font-mono mt-1">{execution.mae_label}</div>
              </div>

              <div className="bg-gray-800/60 border border-gray-700 rounded-xl p-4">
                <div className="flex items-center gap-1 text-xs text-gray-500 font-mono uppercase mb-2">
                  <Clock className="w-3 h-3" /> Latencia Promedio
                </div>
                <div className={`text-2xl font-bold font-mono ${
                  execution.latency_avg_ms === null ? "text-gray-500"
                  : execution.latency_avg_ms < 30000 ? "text-green-400"
                  : execution.latency_avg_ms < 120000 ? "text-yellow-400"
                  : "text-red-400"
                }`}>
                  {execution.latency_avg_ms !== null
                    ? execution.latency_avg_ms < 60000
                      ? `${(execution.latency_avg_ms / 1000).toFixed(0)}s`
                      : `${(execution.latency_avg_ms / 60000).toFixed(1)}min`
                    : "—"}
                </div>
                <div className="text-xs text-gray-500 font-mono mt-1">{execution.latency_label}</div>
              </div>

              <div className="bg-gray-800/60 border border-gray-700 rounded-xl p-4">
                <div className="text-xs text-gray-500 font-mono uppercase mb-2">Trades con MAE</div>
                <div className="text-2xl font-bold font-mono text-white">
                  {execution.trades_with_mae}
                  <span className="text-sm text-gray-500"> / {execution.total_trades}</span>
                </div>
                <div className="text-xs text-gray-500 font-mono mt-1">
                  {execution.total_trades > 0
                    ? `${Math.round(execution.trades_with_mae / execution.total_trades * 100)}% con datos completos`
                    : "—"}
                </div>
              </div>
            </div>

            {/* Latencia por sesión — gráfico de barras */}
            {Object.keys(execution.by_session).length > 0 && (
              <div className="mb-6">
                <p className="text-xs text-gray-500 font-mono uppercase tracking-wider mb-3">
                  MAE y Latencia por Sesión
                </p>
                <div className="space-y-3">
                  {Object.entries(execution.by_session).map(([sess, data]) => {
                    const maxLat = Math.max(...Object.values(execution.by_session)
                      .map(s => s.latency_avg_ms || 0), 1);
                    const latPct = data.latency_avg_ms ? Math.min(data.latency_avg_ms / maxLat * 100, 100) : 0;
                    const latColor = !data.latency_avg_ms ? "bg-gray-700"
                      : data.latency_avg_ms < 30000 ? "bg-green-500"
                      : data.latency_avg_ms < 120000 ? "bg-yellow-500"
                      : "bg-red-500";
                    return (
                      <div key={sess} className="bg-gray-800/40 border border-gray-700/50 rounded-lg p-3">
                        <div className="flex items-center justify-between mb-2">
                          <span className="text-xs font-mono font-bold text-gray-300">{sess}</span>
                          <div className="flex items-center gap-4 text-xs font-mono text-gray-400">
                            <span>MAE: <span className={
                              !data.mae_avg_pips ? "text-gray-500"
                              : data.mae_avg_pips < 3 ? "text-green-400"
                              : data.mae_avg_pips < 6 ? "text-yellow-400"
                              : "text-red-400"
                            }>{data.mae_avg_pips !== null ? `${data.mae_avg_pips}p` : "—"}</span></span>
                            <span>WR: <span className={data.win_rate >= 55 ? "text-green-400" : "text-red-400"}>
                              {data.win_rate}%
                            </span></span>
                            <span className="text-gray-600">{data.total} ops</span>
                          </div>
                        </div>
                        {/* Barra de latencia */}
                        <div className="flex items-center gap-2">
                          <span className="text-xs text-gray-600 font-mono w-16">Latencia</span>
                          <div className="flex-1 bg-gray-700 rounded-full h-1.5">
                            <div
                              className={`${latColor} h-1.5 rounded-full transition-all`}
                              style={{ width: `${latPct}%` }}
                            />
                          </div>
                          <span className="text-xs font-mono text-gray-400 w-16 text-right">
                            {data.latency_avg_ms
                              ? data.latency_avg_ms < 60000
                                ? `${(data.latency_avg_ms/1000).toFixed(0)}s`
                                : `${(data.latency_avg_ms/60000).toFixed(1)}min`
                              : "—"}
                          </span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* MAE vs Resultado */}
            {Object.keys(execution.mae_vs_result).length > 0 && (
              <div>
                <p className="text-xs text-gray-500 font-mono uppercase tracking-wider mb-3">
                  ¿El MAE Alto Predice Pérdidas?
                </p>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                  {Object.entries(execution.mae_vs_result).map(([label, data]) => (
                    <div key={label} className={`p-3 rounded-lg border text-center ${
                      data.win_rate >= 55
                        ? "bg-green-900/20 border-green-700/40"
                        : "bg-red-900/20 border-red-700/40"
                    }`}>
                      <div className="text-xs text-gray-500 font-mono mb-1">{label}</div>
                      <div className={`text-lg font-bold font-mono ${
                        data.win_rate >= 55 ? "text-green-400" : "text-red-400"
                      }`}>{data.win_rate}%</div>
                      <div className="text-xs text-gray-600 font-mono">{data.total} ops</div>
                    </div>
                  ))}
                </div>
                <p className="text-xs text-gray-600 font-mono mt-2">
                  Si el WR cae con MAE alto, las señales con drawdown fuerte tienden a perder.
                </p>
              </div>
            )}
          </div>
        )}

      </main>
    </div>
  );
}
