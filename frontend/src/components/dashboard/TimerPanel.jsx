/**
 * TimerPanel.jsx — Panel izquierdo: countdown activo + apuesta + logs
 */
import { memo, useState, useEffect } from "react";
import { T, sc } from "../../utils/dashboardUtils";
import { getSecondsLeft, formatTime } from "../../utils/signalTime";
import { RText } from "./Primitives";
import { LogFeed } from "./Widgets";

export const TimerPanel = memo(({ signals, risk, logs }) => {
  const topSig = signals.reduce((b, s) => !b || s.quality_score > b.quality_score ? s : b, null);
  const [secs, setSecs] = useState(0);

  useEffect(() => {
    if (!topSig) return;
    const tick = () => setSecs(getSecondsLeft(topSig.signal_timestamp || topSig.created_at));
    tick();
    const id = setInterval(tick, 500);
    return () => clearInterval(id);
  }, [topSig]);

  const cb      = risk?.circuit_breaker;
  const blocked = cb?.triggered;
  const sizing  = risk?.sizing;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", background: T.surface }}>

      {/* Timer de señal activa */}
      {topSig ? (
        <div style={{
          padding: "12px 10px", borderBottom: `1px solid ${T.border}`,
          background: `${sc(topSig.signal_type)}07`,
        }}>
          <div style={{ fontSize: "9px", color: T.muted, fontFamily: "monospace", letterSpacing: ".12em", marginBottom: "4px" }}>
            {topSig.signal_type} ACTIVO
          </div>

          {/* Countdown */}
          <div style={{
            fontSize: "44px", fontWeight: 900, fontFamily: "'IBM Plex Mono',monospace",
            color: secs <= 5 ? T.put : secs <= 15 ? T.pre : sc(topSig.signal_type),
            lineHeight: 1, letterSpacing: "-0.04em", textAlign: "center",
            animation: secs <= 5 ? "blink .5s step-end infinite" : "none",
          }}>
            {formatTime(secs)}
          </div>

          {/* Nombre del activo */}
          <div style={{ marginTop: "4px", textAlign: "center" }}>
            <RText
              text={(topSig.asset_name || topSig.symbol || "")
                .replace("OTC_", "").replace(/_/g, "/") +
                (topSig.symbol?.includes("OTC") ? " OTC" : "")}
              max={16} min={9} w={900}
              color={sc(topSig.signal_type)}
            />
          </div>

          {/* Detalles */}
          <div style={{ display: "flex", justifyContent: "space-around", marginTop: "6px" }}>
            {[
              ["Conf", `${((topSig.quality_score || 0) * 100).toFixed(0)}%`],
              ["Exp",  "2 MIN"],
              ["CCI",  topSig.cci?.toFixed(0) || "—"],
            ].map(([k, v]) => (
              <div key={k} style={{ textAlign: "center" }}>
                <div style={{ fontSize: "8px", color: T.muted, fontFamily: "monospace" }}>{k}</div>
                <div style={{ fontSize: "11px", fontWeight: 700, fontFamily: "monospace", color: T.text }}>{v}</div>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div style={{ padding: "14px 10px", borderBottom: `1px solid ${T.border}`, textAlign: "center" }}>
          <div style={{ fontSize: "9px", color: T.dim, fontFamily: "monospace", letterSpacing: ".12em" }}>
            SIN SEÑAL ACTIVA
          </div>
          <div style={{ fontSize: "28px", fontWeight: 900, fontFamily: "'IBM Plex Mono',monospace", color: T.dim, marginTop: "4px" }}>
            —:——
          </div>
        </div>
      )}

      {/* Apuesta sugerida */}
      {sizing && (
        <div style={{ padding: "8px 10px", borderBottom: `1px solid ${T.border}` }}>
          <div style={{ fontSize: "9px", color: T.muted, fontFamily: "monospace", letterSpacing: ".1em", marginBottom: "3px" }}>
            APUESTA SUGERIDA
          </div>
          <div style={{ fontSize: "20px", fontWeight: 900, fontFamily: "'IBM Plex Mono',monospace", color: T.violet }}>
            ${sizing.suggested_amount}
          </div>
          <div style={{ fontSize: "9px", color: T.sub, fontFamily: "monospace" }}>
            {sizing.risk_pct_effective}% · {sizing.multiplier_reason}
          </div>
        </div>
      )}

      {/* Bloqueo CB */}
      {blocked && (
        <div style={{ padding: "8px 10px", background: "#1a0505", borderBottom: `1px solid ${T.put}` }}>
          <div style={{ fontSize: "10px", fontWeight: 900, color: T.put, fontFamily: "monospace" }}>
            🛑 OPERACIÓN BLOQUEADA
          </div>
          <div style={{ fontSize: "9px", color: "#cc4444", fontFamily: "monospace", marginTop: "2px", lineHeight: 1.4 }}>
            {cb.reason?.replace("🛑 ", "")}
          </div>
        </div>
      )}

      {/* Logs */}
      <div style={{ flex: 1, overflow: "hidden" }}>
        <LogFeed logs={logs || []} />
      </div>
    </div>
  );
});
