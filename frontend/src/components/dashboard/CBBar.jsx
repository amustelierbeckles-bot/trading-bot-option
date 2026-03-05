/**
 * CBBar.jsx — Barra de Circuit Breaker, Racha y Apuesta Sugerida
 */
import { memo, useState, useEffect } from "react";
import { T } from "../../utils/dashboardUtils";

export const CBBar = memo(({ risk, onNewSession }) => {
  const cb      = risk?.circuit_breaker;
  const streak  = risk?.streak;
  const sizing  = risk?.sizing;
  const sWR     = risk?.session_win_rate;
  const blocked = cb?.triggered;

  const [countdown, setCountdown] = useState("");

  useEffect(() => {
    if (!blocked || !cb?.cooldown_minutes) return;
    const tick = () => {
      const mins = cb.cooldown_minutes;
      const m = Math.floor(mins);
      const s = Math.round((mins - m) * 60);
      setCountdown(`${String(m).padStart(2,"0")}:${String(s).padStart(2,"0")}`);
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [blocked, cb]);

  if (!risk) return null;

  const last3      = streak?.last_3 || [];
  const streakType = streak?.type === "W" ? "W" : streak?.type === "L" ? "L" : null;
  const streakCount= streak?.count || 0;

  return (
    <div style={{
      display: "flex", alignItems: "center", gap: "10px",
      padding: "0 12px", height: "34px", flexShrink: 0,
      background: blocked ? "#1a0505" : T.surface,
      borderBottom: `1px solid ${blocked ? T.put : T.border}`,
      fontSize: "11px", fontFamily: "monospace",
    }}>

      {/* Estado */}
      {blocked ? (
        <>
          <span style={{ color: T.put, fontSize: "10px" }}>🛑</span>
          <span style={{ fontWeight: 900, color: T.put, letterSpacing: ".05em" }}>BLOQUEADO</span>
          <div style={{ background: T.put, color: "#000", fontWeight: 900, padding: "1px 8px", fontSize: "10px" }}>
            Reanuda en {countdown}
          </div>
        </>
      ) : (
        <span style={{ color: T.call, fontWeight: 700 }}>✅ OK</span>
      )}

      <span style={{ color: T.dim }}>|</span>

      {/* Racha */}
      <span style={{ color: T.sub }}>Racha:</span>
      <span style={{ fontWeight: 900, color: streakType === "W" ? T.call : streakType === "L" ? T.put : T.muted }}>
        {streakType ? `${streakCount}${streakType}` : "—"}
      </span>
      {last3.map((r, i) => (
        <span key={i} style={{
          fontWeight: 900, fontSize: "10px", padding: "0 4px",
          background: r === "W" ? `${T.call}18` : `${T.put}18`,
          color: r === "W" ? T.call : T.put,
          border: `1px solid ${r === "W" ? T.call : T.put}44`,
        }}>
          {r}
        </span>
      ))}

      <span style={{ color: T.dim }}>|</span>

      {/* Apuesta */}
      {sizing && <>
        <span style={{ color: T.sub }}>Apuesta:</span>
        <span style={{ fontWeight: 900, color: T.violet }}>${sizing.suggested_amount}</span>
        <span style={{ color: T.muted, fontSize: "10px" }}>({sizing.risk_pct_effective}%)</span>
        <span style={{ color: T.dim }}>|</span>
      </>}

      {/* Session WR */}
      {sWR != null && <>
        <span style={{ color: T.sub }}>Sesión WR:</span>
        <span style={{ fontWeight: 900, color: sWR >= 55 ? T.call : sWR >= 45 ? T.pre : T.put }}>
          {sWR}%
        </span>
      </>}

      <div style={{ flex: 1 }} />

      <button
        onClick={onNewSession}
        style={{
          background: "transparent", border: `1px solid ${T.dim}`,
          color: T.muted, padding: "1px 8px", fontSize: "10px",
          cursor: "pointer", fontFamily: "monospace", transition: "all .15s",
        }}
        onMouseEnter={e => { e.target.style.borderColor = T.call; e.target.style.color = T.call; }}
        onMouseLeave={e => { e.target.style.borderColor = T.dim;  e.target.style.color = T.muted; }}
      >
        🔄 Nueva Sesión
      </button>
    </div>
  );
});
