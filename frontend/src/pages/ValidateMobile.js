/**
 * ValidateMobile — Página optimizada para móvil
 *
 * Acceso desde el enlace WhatsApp: /validate?id=SIGNAL_ID
 * Permite registrar W/L de una señal remotamente para estadísticas.
 * NO ejecuta operaciones — solo registro de datos.
 */
import { useState, useEffect } from "react";
import axios from "axios";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const API_KEY = process.env.REACT_APP_API_KEY;

export default function ValidateMobile() {
  const params   = new URLSearchParams(window.location.search);
  const signalId = params.get("id") || "";

  const [signal,    setSignal]    = useState(null);
  const [loading,   setLoading]   = useState(true);
  const [saving,    setSaving]    = useState(false);
  const [saved,     setSaved]     = useState(false);
  const [result,    setResult]    = useState(null); // "win" | "loss"
  const [error,     setError]     = useState("");

  useEffect(() => {
    if (!signalId) { setLoading(false); setError("Sin ID de señal"); return; }
    fetchSignal();
  }, [signalId]);

  const fetchSignal = async () => {
    try {
      const { data } = await axios.get(`${API}/signals/active`);
      const found = data.signals?.find(s => s.id === signalId)
                 || data.find?.(s => s.id === signalId);
      if (found) {
        setSignal(found);
      } else {
        // Señal expirada — mostrar formulario manual igualmente
        setSignal({ id: signalId, asset_name: "Señal", type: "—", expired: true });
      }
    } catch {
      setSignal({ id: signalId, asset_name: "Señal", type: "—", expired: true });
    } finally {
      setLoading(false);
    }
  };

  const handleResult = async (res) => {
    setResult(res);
    setSaving(true);
    try {
      await axios.post(`${API}/trades`, {
        signal_id:        signalId,
        symbol:           signal?.symbol || "UNKNOWN",
        asset_name:       signal?.asset_name || "Desconocido",
        signal_type:      signal?.type || "CALL",
        result:           res,
        entry_price:      signal?.entry_price || 0,
        payout:           signal?.payout || 85,
        quality_score:    signal?.quality_score || 0,
        cci:              signal?.cci || 0,
        signal_timestamp: signal?.timestamp || new Date().toISOString(),
      }, {
        headers: API_KEY ? { "X-API-Key": API_KEY } : {}
      });
      setSaved(true);
    } catch (e) {
      setError("Error al guardar. Inténtalo de nuevo.");
      setResult(null);
    } finally {
      setSaving(false);
    }
  };

  // ── Loading ─────────────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="min-h-screen bg-gray-950 flex items-center justify-center">
        <div className="text-center">
          <div className="w-10 h-10 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
          <p className="text-gray-400 font-mono text-sm">Cargando señal...</p>
        </div>
      </div>
    );
  }

  // ── Guardado exitoso ────────────────────────────────────────────────────────
  if (saved) {
    const isWin = result === "win";
    return (
      <div className="min-h-screen bg-gray-950 flex items-center justify-center p-4">
        <div className="text-center max-w-xs w-full">
          <div className={`w-20 h-20 rounded-full flex items-center justify-center mx-auto mb-5 ${
            isWin ? "bg-green-900/50 border-2 border-green-500" : "bg-red-900/50 border-2 border-red-500"
          }`}>
            <span className="text-4xl">{isWin ? "✅" : "❌"}</span>
          </div>
          <h1 className={`text-3xl font-bold font-mono mb-2 ${isWin ? "text-green-400" : "text-red-400"}`}>
            {isWin ? "WIN" : "LOSS"}
          </h1>
          <p className="text-gray-400 font-mono text-sm mb-1">
            {signal?.asset_name} registrado
          </p>
          <p className="text-gray-600 font-mono text-xs">
            Dato guardado en MongoDB para estadísticas
          </p>
          <button
            onClick={() => { setSaved(false); setResult(null); }}
            className="mt-6 text-xs text-gray-600 border border-gray-700 px-4 py-2 rounded-lg hover:border-gray-500 transition-all"
          >
            Registrar otro resultado
          </button>
        </div>
      </div>
    );
  }

  const isCall = signal?.type === "CALL" || signal?.type === "BUY";
  const scorePct = Math.round((signal?.quality_score || 0) * 100);

  return (
    <div className="min-h-screen bg-gray-950 flex flex-col" style={{ fontFamily: "monospace" }}>

      {/* Header */}
      <div className="bg-black/60 border-b border-gray-800 px-4 py-3 text-center">
        <p className="text-gray-500 text-xs">POCKET OPTION BOT</p>
        <p className="text-white text-sm font-bold">Registrar Resultado</p>
        <p className="text-gray-600 text-xs mt-0.5">Solo estadístico — no ejecuta operaciones</p>
      </div>

      {/* Señal */}
      <div className="flex-1 flex flex-col items-center justify-center p-6">

        {error && (
          <div className="bg-red-900/30 border border-red-700 rounded-xl p-4 mb-4 w-full max-w-xs text-center">
            <p className="text-red-400 text-sm">{error}</p>
          </div>
        )}

        {signal?.expired && (
          <div className="bg-yellow-900/20 border border-yellow-700/50 rounded-xl p-3 mb-4 w-full max-w-xs text-center">
            <p className="text-yellow-400 text-xs">Señal expirada — puedes registrar igual</p>
          </div>
        )}

        {/* Card de señal */}
        <div className={`w-full max-w-xs rounded-2xl border-2 p-5 mb-6 ${
          isCall ? "border-green-600 bg-green-900/10" : "border-red-600 bg-red-900/10"
        }`}>
          <div className="text-center mb-4">
            <span className={`text-xs font-bold px-3 py-1 rounded-full ${
              isCall ? "bg-green-900/50 text-green-400" : "bg-red-900/50 text-red-400"
            }`}>
              {isCall ? "▲ CALL" : "▼ PUT"}
            </span>
          </div>

          <h2 className="text-2xl font-bold text-white text-center mb-4">
            {signal?.asset_name || "—"}
          </h2>

          <div className="grid grid-cols-3 gap-2 text-center">
            <div className="bg-white/5 rounded-lg py-2">
              <p className="text-gray-500 text-xs">Score</p>
              <p className="text-white font-bold">{scorePct}%</p>
            </div>
            <div className="bg-white/5 rounded-lg py-2">
              <p className="text-gray-500 text-xs">CCI</p>
              <p className={`font-bold ${Math.abs(signal?.cci || 0) > 140 ? "text-orange-400" : "text-white"}`}>
                {(signal?.cci || 0).toFixed(0)}
              </p>
            </div>
            <div className="bg-white/5 rounded-lg py-2">
              <p className="text-gray-500 text-xs">Payout</p>
              <p className="text-white font-bold">{(signal?.payout || 85).toFixed(0)}%</p>
            </div>
          </div>
        </div>

        {/* Pregunta */}
        <p className="text-gray-300 text-base font-bold text-center mb-6">
          ¿Cuál fue el resultado?
        </p>

        {/* Botones W/L */}
        <div className="flex gap-4 w-full max-w-xs">
          <button
            onClick={() => handleResult("win")}
            disabled={saving}
            className={`flex-1 py-5 rounded-2xl font-bold text-lg transition-all active:scale-95 ${
              saving && result === "win"
                ? "bg-green-600 text-white opacity-70"
                : "bg-green-600 hover:bg-green-500 text-white"
            }`}
            style={{ boxShadow: "0 0 20px rgba(34,197,94,0.3)" }}
          >
            {saving && result === "win" ? "..." : "✅ WIN"}
          </button>

          <button
            onClick={() => handleResult("loss")}
            disabled={saving}
            className={`flex-1 py-5 rounded-2xl font-bold text-lg transition-all active:scale-95 ${
              saving && result === "loss"
                ? "bg-red-600 text-white opacity-70"
                : "bg-red-600 hover:bg-red-500 text-white"
            }`}
            style={{ boxShadow: "0 0 20px rgba(239,68,68,0.3)" }}
          >
            {saving && result === "loss" ? "..." : "❌ LOSS"}
          </button>
        </div>

        <p className="text-gray-700 text-xs text-center mt-4 max-w-xs">
          Este registro alimenta el sistema de calibración y backtesting del bot.
          No ejecuta ninguna operación real.
        </p>
      </div>

      {/* Footer */}
      <div className="border-t border-gray-900 px-4 py-3 text-center">
        <a href="/" className="text-gray-700 text-xs hover:text-gray-500">
          Abrir Dashboard completo →
        </a>
      </div>
    </div>
  );
}
