/**
 * CriticalPerformancePanel — RADAR V2.4
 * Aparato Crítico de Rendimiento: traduce datos técnicos a lenguaje humano simplificado.
 * Panel lateral derecho con tarjetas informativas.
 */
import { useState, useEffect, useCallback } from "react";
import axios from "axios";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

// ── Tarjeta informativa ───────────────────────────────────────────────────────
function InfoCard({ label, value, humanText, status }) {
  const statusColor = status === "ok" ? "#00FF94" : status === "warn" ? "#FACC15" : status === "critical" ? "#FF0055" : "#E0E0E0";
  return (
    <div style={{
      background: "#0a0a0a",
      border: "1px solid rgba(224,224,224,0.08)",
      borderRadius: 4,
      padding: "6px 8px",
      marginBottom: 4,
    }}>
      <div style={{
        fontSize: "0.7rem",
        fontFamily: "monospace",
        letterSpacing: "0.12em",
        color: "rgba(224,224,224,0.5)",
        textTransform: "uppercase",
        marginBottom: 2,
      }}>
        {label}
      </div>
      <div style={{
        fontSize: "1.1rem",
        fontWeight: 500,
        fontFamily: "monospace",
        color: statusColor,
        marginBottom: 2,
      }}>
        {value}
      </div>
      <div style={{
        fontSize: "0.75rem",
        fontFamily: "monospace",
        color: "#E0E0E0",
        lineHeight: 1.4,
        opacity: 0.85,
      }}>
        {humanText}
      </div>
    </div>
  );
}

export default function CriticalPerformancePanel({
  sessionWinRate = null,
  latencyMs = null,
  latencyAlert = false,
}) {
  const [stats, setStats] = useState(null);
  const [execution, setExecution] = useState(null);

  const fetchStats = useCallback(async () => {
    try {
      const { data } = await axios.get(`${API}/trades/stats?days=30`);
      setStats(data);
    } catch { /* silencioso */ }
  }, []);

  const fetchExecution = useCallback(async () => {
    try {
      const { data } = await axios.get(`${API}/performance/execution?days=7`);
      setExecution(data);
    } catch { /* silencioso */ }
  }, []);

  useEffect(() => {
    fetchStats();
    fetchExecution();
    const id1 = setInterval(fetchStats, 60000);
    const id2 = setInterval(fetchExecution, 60000);
    return () => { clearInterval(id1); clearInterval(id2); };
  }, [fetchStats, fetchExecution]);

  // Win Rate
  const wr = sessionWinRate ?? stats?.win_rate ?? null;
  const wrStatus = wr === null ? null : wr >= 60 ? "ok" : wr >= 50 ? "warn" : "critical";
  const wrHuman = wr === null
    ? "Sin datos suficientes"
    : wr >= 60
      ? "Eficiencia actual de la estrategia (Objetivo >60%) ✓"
      : wr >= 50
        ? "Eficiencia actual de la estrategia (Objetivo >60%) — mejorar"
        : "Eficiencia actual de la estrategia (Objetivo >60%) — crítico";

  // MAE (Drawdown)
  const mae = execution?.mae_avg_pips ?? null;
  const maeLabel = execution?.mae_label ?? "Sin datos";
  const maeStatus = mae === null ? null : mae < 3 ? "ok" : mae < 6 ? "warn" : "critical";
  const maeHuman = mae === null
    ? "Sin datos suficientes"
    : mae < 3
      ? "Nivel de riesgo por operación: Bajo"
      : mae < 6
        ? "Nivel de riesgo por operación: Medio"
        : "Nivel de riesgo por operación: Crítico";

  // Latency: API latencyMs (ms) o execution latency_avg_ms (señal→usuario)
  const lat = latencyMs ?? execution?.latency_avg_ms ?? null;
  const latThreshold = latencyMs != null ? 3000 : 30000; // API: 3s, execution: 30s
  const latStatus = lat === null ? null : latencyAlert || (lat > latThreshold) ? "critical" : "ok";
  const latHuman = lat === null
    ? "Sin datos suficientes"
    : latencyAlert || (lat > latThreshold)
      ? "Velocidad de respuesta: Retraso Detectado"
      : "Velocidad de respuesta: Óptima";

  // Profit Factor
  const pf = stats?.profit_factor ?? null;
  const pfStatus = pf === null ? null : pf >= 1.3 ? "ok" : pf >= 1 ? "warn" : "critical";
  const pfHuman = pf === null
    ? "Sin datos suficientes"
    : pf >= 1.3
      ? "Relación de ganancia vs pérdida (Salud de la cuenta) ✓"
      : pf >= 1
        ? "Relación de ganancia vs pérdida (Salud de la cuenta) — neutro"
        : "Relación de ganancia vs pérdida (Salud de la cuenta) — en riesgo";

  return (
    <div style={{
      display: "flex",
      flexDirection: "column",
      gap: 4,
      minWidth: 0,
    }}>
      <div style={{
        fontSize: "0.65rem",
        letterSpacing: "0.18em",
        color: "rgba(224,224,224,0.35)",
        fontFamily: "monospace",
        textTransform: "uppercase",
        marginBottom: 2,
      }}>
        Aparato Crítico
      </div>
      <InfoCard
        label="Win Rate"
        value={wr !== null ? `${wr}%` : "—"}
        humanText={wrHuman}
        status={wrStatus}
      />
      <InfoCard
        label="MAE (Drawdown)"
        value={mae !== null ? `${mae} pips` : maeLabel}
        humanText={maeHuman}
        status={maeStatus}
      />
      <InfoCard
        label="Latencia"
        value={lat !== null ? `${lat}ms` : "—"}
        humanText={latHuman}
        status={latStatus}
      />
      <InfoCard
        label="Profit Factor"
        value={pf !== null ? pf.toFixed(2) : "—"}
        humanText={pfHuman}
        status={pfStatus}
      />
    </div>
  );
}
