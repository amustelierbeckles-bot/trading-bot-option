import { useState } from "react";
import axios from "axios";
import {
  TrendingUp, TrendingDown, Activity, BarChart3,
  Target, AlertTriangle, Clock, Zap, ChevronDown, ChevronUp
} from "lucide-react";
import { toast } from "sonner";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const API_KEY = process.env.REACT_APP_API_KEY;

const SYMBOLS = [
  { value: "OTC_EURUSD", label: "EUR/USD OTC" },
  { value: "OTC_GBPUSD", label: "GBP/USD OTC" },
  { value: "OTC_USDJPY", label: "USD/JPY OTC" },
  { value: "OTC_EURJPY", label: "EUR/JPY OTC" },
  { value: "OTC_AUDUSD", label: "AUD/USD OTC" },
  { value: "OTC_USDCHF", label: "USD/CHF OTC" },
  { value: "OTC_EURGBP", label: "EUR/GBP OTC" },
  { value: "OTC_GBPJPY", label: "GBP/JPY OTC" },
];

const INTERVALS = [
  { value: "1min",  label: "1 Minuto" },
  { value: "5min",  label: "5 Minutos" },
  { value: "15min", label: "15 Minutos" },
];

const CANDLE_OPTIONS = [
  { value: 100, label: "100 velas (~1.5h en 1min)" },
  { value: 200, label: "200 velas (~3h en 1min)"   },
  { value: 300, label: "300 velas (~5h en 1min)"   },
  { value: 500, label: "500 velas (~8h en 1min)"   },
];

export default function Backtesting() {
  const [form, setForm] = useState({
    symbol:         "OTC_EURUSD",
    interval:       "1min",
    candles:        200,
    expiry_candles: 2,
    min_quality:    0.55,
  });
  const [result, setResult]   = useState(null);
  const [loading, setLoading] = useState(false);
  const [showTrades, setShowTrades] = useState(false);

  const runBacktest = async () => {
    setLoading(true);
    setResult(null);
    try {
      const { data } = await axios.post(`${API}/backtest`, form, {
        headers: API_KEY ? { "X-API-Key": API_KEY } : {}
      });
      setResult(data);
      toast.success(`Backtest completado — ${data.summary}`);
    } catch (err) {
      const msg = err.response?.data?.detail || "Error al ejecutar backtesting";
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  };

  const update = (k, v) => setForm(f => ({ ...f, [k]: v }));

  // ── Equity curve mini-SVG ───────────────────────────────────────────────────
  const EquityCurve = ({ curve }) => {
    if (!curve || curve.length < 2) return null;
    const min  = Math.min(...curve);
    const max  = Math.max(...curve);
    const range = max - min || 1;
    const W = 600, H = 120;
    const pts = curve.map((v, i) => {
      const x = (i / (curve.length - 1)) * W;
      const y = H - ((v - min) / range) * H;
      return `${x},${y}`;
    }).join(" ");
    const last  = curve[curve.length - 1];
    const color = last >= 100 ? "#00ff88" : "#ff4466";
    return (
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-28" preserveAspectRatio="none">
        <defs>
          <linearGradient id="eq" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%"   stopColor={color} stopOpacity="0.3" />
            <stop offset="100%" stopColor={color} stopOpacity="0.0" />
          </linearGradient>
        </defs>
        {/* Línea de breakeven */}
        <line
          x1="0" y1={H - ((100 - min) / range) * H}
          x2={W} y2={H - ((100 - min) / range) * H}
          stroke="#ffffff20" strokeWidth="1" strokeDasharray="4,4"
        />
        <polyline points={pts} fill="none" stroke={color} strokeWidth="2" />
      </svg>
    );
  };

  // ── StatCard ────────────────────────────────────────────────────────────────
  const Stat = ({ label, value, sub, color, Icon }) => (
    <div className="bg-gray-900 border border-gray-700 rounded-xl p-4">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs text-gray-400 font-mono uppercase tracking-wider">{label}</span>
        {Icon && <Icon className="w-4 h-4 text-gray-500" />}
      </div>
      <div className={`text-2xl font-bold font-mono ${color || "text-white"}`}>{value}</div>
      {sub && <div className="text-xs text-gray-500 mt-1 font-mono">{sub}</div>}
    </div>
  );

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      {/* Header */}
      <header className="border-b border-gray-800 bg-black/60 backdrop-blur px-6 py-4">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <BarChart3 className="w-7 h-7 text-blue-400" />
            <h1 className="text-xl font-bold tracking-tight">BACKTESTING</h1>
            <span className="text-xs bg-blue-500/20 text-blue-400 border border-blue-500/30 px-2 py-0.5 rounded font-mono">
              DATOS REALES · TWELVE DATA
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

        {/* Config */}
        <div className="bg-gray-900 border border-gray-700 rounded-2xl p-6">
          <h2 className="text-sm font-mono text-gray-400 uppercase tracking-wider mb-4">Configuración</h2>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
            {/* Par */}
            <div className="col-span-2 md:col-span-1 space-y-1">
              <label className="text-xs text-gray-500 font-mono">Par de divisas</label>
              <select
                value={form.symbol}
                onChange={e => update("symbol", e.target.value)}
                className="w-full bg-gray-800 border border-gray-600 rounded-lg px-3 py-2 text-sm font-mono text-white focus:outline-none focus:border-blue-500"
              >
                {SYMBOLS.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
              </select>
            </div>

            {/* Intervalo */}
            <div className="space-y-1">
              <label className="text-xs text-gray-500 font-mono">Timeframe</label>
              <select
                value={form.interval}
                onChange={e => update("interval", e.target.value)}
                className="w-full bg-gray-800 border border-gray-600 rounded-lg px-3 py-2 text-sm font-mono text-white focus:outline-none focus:border-blue-500"
              >
                {INTERVALS.map(i => <option key={i.value} value={i.value}>{i.label}</option>)}
              </select>
            </div>

            {/* Velas */}
            <div className="space-y-1">
              <label className="text-xs text-gray-500 font-mono">Historial</label>
              <select
                value={form.candles}
                onChange={e => update("candles", Number(e.target.value))}
                className="w-full bg-gray-800 border border-gray-600 rounded-lg px-3 py-2 text-sm font-mono text-white focus:outline-none focus:border-blue-500"
              >
                {CANDLE_OPTIONS.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
              </select>
            </div>

            {/* Expiración */}
            <div className="space-y-1">
              <label className="text-xs text-gray-500 font-mono">Expiración (velas)</label>
              <select
                value={form.expiry_candles}
                onChange={e => update("expiry_candles", Number(e.target.value))}
                className="w-full bg-gray-800 border border-gray-600 rounded-lg px-3 py-2 text-sm font-mono text-white focus:outline-none focus:border-blue-500"
              >
                <option value={1}>1 vela (1min)</option>
                <option value={2}>2 velas (2min)</option>
                <option value={5}>5 velas (5min)</option>
              </select>
            </div>

            {/* Botón */}
            <div className="flex items-end">
              <button
                onClick={runBacktest}
                disabled={loading}
                className="w-full bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:cursor-not-allowed text-white font-bold py-2 px-4 rounded-lg transition-all flex items-center justify-center gap-2"
              >
                <Activity className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
                {loading ? "Analizando..." : "Ejecutar"}
              </button>
            </div>
          </div>

          {/* Info de coste */}
          <p className="text-xs text-gray-600 mt-3 font-mono">
            ⚡ Cada ejecución consume 1 petición de tu límite diario de 700 req/día en Twelve Data
          </p>
        </div>

        {/* Loading */}
        {loading && (
          <div className="bg-gray-900 border border-gray-700 rounded-2xl p-12 text-center">
            <Activity className="w-12 h-12 text-blue-400 animate-spin mx-auto mb-4" />
            <p className="text-gray-400 font-mono">Descargando datos históricos y aplicando estrategias...</p>
          </div>
        )}

        {/* Resultados */}
        {result && (
          <>
            {/* Resumen */}
            <div className="bg-gray-900 border border-gray-700 rounded-2xl p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs text-gray-500 font-mono">RESUMEN</p>
                  <p className="text-white font-mono font-bold">{result.summary}</p>
                </div>
                <div className="text-right text-xs text-gray-500 font-mono">
                  <p>{result.candles_total} velas analizadas</p>
                  <p>Expiración: {result.expiry_candles} vela(s)</p>
                </div>
              </div>
            </div>

            {/* KPIs */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <Stat
                label="Win Rate"
                value={`${result.win_rate}%`}
                sub={`${result.wins}W / ${result.losses}L`}
                color={result.win_rate >= 55 ? "text-green-400" : result.win_rate >= 45 ? "text-yellow-400" : "text-red-400"}
                Icon={Target}
              />
              <Stat
                label="Profit Factor"
                value={result.profit_factor}
                sub={result.profit_factor >= 1.2 ? "✅ Rentable" : result.profit_factor >= 1.0 ? "⚠️ En equilibrio" : "❌ Negativo"}
                color={result.profit_factor >= 1.2 ? "text-green-400" : result.profit_factor >= 1.0 ? "text-yellow-400" : "text-red-400"}
                Icon={TrendingUp}
              />
              <Stat
                label="Capital final"
                value={`${result.final_equity}%`}
                sub={`Inicio: 100% | ${result.final_equity >= 100 ? "+" : ""}${(result.final_equity - 100).toFixed(1)}%`}
                color={result.final_equity >= 100 ? "text-green-400" : "text-red-400"}
                Icon={Zap}
              />
              <Stat
                label="Señales totales"
                value={result.total_signals}
                sub={`Score ≥ ${result.min_quality}`}
                Icon={Clock}
              />
            </div>

            {/* Calidad del sistema */}
            <div className="bg-gray-900 border border-gray-700 rounded-2xl p-5">
              <h3 className="text-sm font-mono text-gray-400 uppercase tracking-wider mb-3">Evaluación del Sistema</h3>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-sm font-mono">
                <div className={`p-3 rounded-lg ${result.win_rate >= 55 ? "bg-green-900/30 border border-green-700" : "bg-red-900/30 border border-red-700"}`}>
                  <p className="text-gray-400 text-xs mb-1">Win Rate</p>
                  <p className={result.win_rate >= 55 ? "text-green-400" : "text-red-400"}>
                    {result.win_rate >= 60 ? "✅ Excelente (≥60%)" :
                     result.win_rate >= 55 ? "✅ Bueno (55-60%)" :
                     result.win_rate >= 50 ? "⚠️ Marginal (50-55%)" :
                     "❌ Insuficiente (<50%)"}
                  </p>
                </div>
                <div className={`p-3 rounded-lg ${result.profit_factor >= 1.3 ? "bg-green-900/30 border border-green-700" : "bg-yellow-900/30 border border-yellow-700"}`}>
                  <p className="text-gray-400 text-xs mb-1">Profit Factor</p>
                  <p className={result.profit_factor >= 1.3 ? "text-green-400" : "text-yellow-400"}>
                    {result.profit_factor >= 1.5 ? "✅ Excelente (≥1.5)" :
                     result.profit_factor >= 1.3 ? "✅ Bueno (1.3-1.5)" :
                     result.profit_factor >= 1.0 ? "⚠️ Aceptable (1.0-1.3)" :
                     "❌ Sistema perdedor (<1.0)"}
                  </p>
                </div>
                <div className={`p-3 rounded-lg ${result.total_signals >= 10 ? "bg-green-900/30 border border-green-700" : "bg-yellow-900/30 border border-yellow-700"}`}>
                  <p className="text-gray-400 text-xs mb-1">Muestra estadística</p>
                  <p className={result.total_signals >= 10 ? "text-green-400" : "text-yellow-400"}>
                    {result.total_signals >= 30 ? "✅ Muestra sólida (≥30)" :
                     result.total_signals >= 10 ? "⚠️ Muestra pequeña (10-30)" :
                     "❌ Muestra insuficiente (<10)"}
                  </p>
                </div>
              </div>
            </div>

            {/* Curva de equity */}
            <div className="bg-gray-900 border border-gray-700 rounded-2xl p-5">
              <h3 className="text-sm font-mono text-gray-400 uppercase tracking-wider mb-3">Curva de Capital</h3>
              <EquityCurve curve={result.equity_curve} />
              <div className="flex justify-between text-xs text-gray-600 font-mono mt-1">
                <span>Inicio: 100%</span>
                <span>Final: {result.final_equity}%</span>
              </div>
            </div>

            {/* Tabla de trades */}
            <div className="bg-gray-900 border border-gray-700 rounded-2xl p-5">
              <button
                onClick={() => setShowTrades(t => !t)}
                className="flex items-center justify-between w-full"
              >
                <h3 className="text-sm font-mono text-gray-400 uppercase tracking-wider">
                  Detalle de Operaciones ({result.trades?.length || 0})
                </h3>
                {showTrades ? <ChevronUp className="w-4 h-4 text-gray-500" /> : <ChevronDown className="w-4 h-4 text-gray-500" />}
              </button>

              {showTrades && (
                <div className="mt-4 overflow-x-auto">
                  <table className="w-full text-xs font-mono">
                    <thead>
                      <tr className="text-gray-500 border-b border-gray-800">
                        <th className="text-left py-2 pr-4">#</th>
                        <th className="text-left py-2 pr-4">Hora</th>
                        <th className="text-left py-2 pr-4">Tipo</th>
                        <th className="text-right py-2 pr-4">Entrada</th>
                        <th className="text-right py-2 pr-4">Salida</th>
                        <th className="text-right py-2 pr-4">Score</th>
                        <th className="text-right py-2 pr-4">CCI</th>
                        <th className="text-center py-2">Resultado</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.trades.map((t, i) => (
                        <tr key={i} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                          <td className="py-1.5 pr-4 text-gray-500">{i + 1}</td>
                          <td className="py-1.5 pr-4 text-gray-400">{t.timestamp?.slice(11, 16) || "—"}</td>
                          <td className={`py-1.5 pr-4 font-bold ${t.type === "CALL" ? "text-green-400" : "text-red-400"}`}>
                            {t.type}
                          </td>
                          <td className="py-1.5 pr-4 text-right text-gray-300">{t.entry_price?.toFixed(5)}</td>
                          <td className="py-1.5 pr-4 text-right text-gray-300">{t.exit_price?.toFixed(5)}</td>
                          <td className="py-1.5 pr-4 text-right text-blue-400">{(t.score * 100).toFixed(0)}%</td>
                          <td className={`py-1.5 pr-4 text-right ${Math.abs(t.cci) > 140 ? "text-orange-400" : "text-gray-400"}`}>
                            {t.cci?.toFixed(1)}
                          </td>
                          <td className="py-1.5 text-center">
                            <span className={`px-2 py-0.5 rounded text-xs font-bold ${t.result === "win" ? "bg-green-900/50 text-green-400" : "bg-red-900/50 text-red-400"}`}>
                              {t.result === "win" ? "WIN" : "LOSS"}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </>
        )}

        {/* Estado inicial */}
        {!result && !loading && (
          <div className="bg-gray-900 border border-gray-700 rounded-2xl p-16 text-center">
            <BarChart3 className="w-14 h-14 text-gray-700 mx-auto mb-4" />
            <h3 className="text-lg font-bold text-gray-400 mb-2">Listo para analizar</h3>
            <p className="text-sm text-gray-600 font-mono max-w-md mx-auto">
              Selecciona un par, timeframe e historial de velas. El bot aplicará las 5 estrategias
              sobre cada vela y calculará el Win Rate y Profit Factor reales.
            </p>
          </div>
        )}
      </main>
    </div>
  );
}
