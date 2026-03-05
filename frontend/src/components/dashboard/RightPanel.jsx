/**
 * RightPanel.jsx — Panel derecho: Glosario · Señal activa · Aparato Crítico
 */
import { memo, useEffect } from "react";
import { T, sc, getHealthColor, GLOSS } from "../../utils/dashboardUtils";
import { RText } from "./Primitives";

// ── Fila del Aparato Crítico ──────────────────────────────────────────────────
const Dx = ({ label, val, color, note, sub, icon, status }) => (
  <div style={{
    padding: "6px 10px", borderBottom: `1px solid ${T.border}`,
    background: status === "danger" ? "#1a0505" : status === "warning" ? "#1a1500" : "transparent",
    transition: "background .3s",
  }}>
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: "4px", marginBottom: "1px" }}>
          {icon && <span style={{ display: "flex", alignItems: "center", flexShrink: 0 }}>{icon}</span>}
          <div style={{ fontSize: "9px", color: T.muted, fontFamily: "monospace", letterSpacing: ".08em" }}>{label}</div>
        </div>
        {sub && <div style={{ fontSize: "9px", color, fontFamily: "monospace" }}>{sub}</div>}
      </div>
      <span style={{
        fontSize: "20px", fontWeight: 900, fontFamily: "'IBM Plex Mono',monospace",
        color, lineHeight: 1,
        textShadow: (status === "danger" || status === "success") ? `0 0 10px ${color}66` : "none",
      }}>
        {val ?? "—"}
      </span>
    </div>
    <div style={{ fontSize: "9px", color: "#444", fontFamily: "monospace", lineHeight: 1.35, marginTop: "2px" }}>{note}</div>
  </div>
);

// ── RightPanel ────────────────────────────────────────────────────────────────
export const RightPanel = memo(({ hovTerm, topSig, selectedSig, stats, session, risk, onMaeAlert }) => {
  const dispSig = selectedSig || topSig;

  const wr  = stats?.win_rate       ?? null;
  const pf  = stats?.profit_factor  ?? null;
  const mae = stats?.mae_avg_pips   ?? null;
  const lat = stats?.latency_avg_ms ?? null;
  const ops = stats?.total_trades   ?? 0;
  const w   = stats?.total_wins     ?? 0;
  const l   = stats?.total_losses   ?? 0;

  const cb      = risk?.circuit_breaker;
  const blocked = cb?.triggered;

  const wrH  = getHealthColor(wr,  "win_rate");
  const pfH  = getHealthColor(pf,  "profit_factor");
  const maeH = getHealthColor(mae, "mae");
  const latH = getHealthColor(lat, "latency");

  const maeAlert = maeH.status === "danger";
  useEffect(() => { if (onMaeAlert) onMaeAlert(maeAlert); }, [maeAlert]); // eslint-disable-line

  const g = hovTerm ? GLOSS[hovTerm] : null;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>

      {/* Glosario */}
      <div style={{
        padding: "7px 10px", borderBottom: `1px solid ${T.border}`,
        minHeight: "100px", background: g ? "#040c06" : T.surface,
        flexShrink: 0, transition: "background .2s",
      }}>
        <div style={{ fontSize: "9px", color: T.muted, fontFamily: "monospace", letterSpacing: ".14em", marginBottom: "4px" }}>
          ◈ GLOSARIO{g ? ` · ${hovTerm}` : " · hover etiqueta"}
        </div>
        {g ? (
          <>
            <div style={{ fontSize: "11px", fontWeight: 700, fontFamily: "monospace", color: T.violet, marginBottom: "3px" }}>{g.full}</div>
            <div style={{ fontSize: "9.5px", color: "#555", fontFamily: "monospace", lineHeight: 1.4, marginBottom: "4px" }}>{g.def}</div>
            {g.rows.map((r, i) => (
              <div key={i} style={{ fontSize: "9px", color: r.c, fontFamily: "monospace", display: "flex", alignItems: "center", gap: "4px", lineHeight: "15px" }}>
                <span style={{ fontSize: "4px" }}>◆</span>{r.l}
              </div>
            ))}
          </>
        ) : (
          <div style={{ fontSize: "9px", color: T.dim, fontFamily: "monospace", lineHeight: 2 }}>
            RSI · BB · CCI · ATR · MAE · EMA · MACD
          </div>
        )}
      </div>

      {/* Señal activa */}
      {dispSig && (
        <div style={{
          padding: "8px 10px", borderBottom: `1px solid ${T.border}`,
          background: `${sc(dispSig.signal_type)}07`, flexShrink: 0,
        }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "3px" }}>
            <span style={{ fontSize: "9px", color: T.muted, fontFamily: "monospace" }}>
              {selectedSig ? "SEÑAL SELECCIONADA" : "SEÑAL TOP"}
            </span>
            <span style={{
              fontSize: "12px", fontWeight: 900, fontFamily: "monospace",
              color: sc(dispSig.signal_type), letterSpacing: ".06em",
              background: `${sc(dispSig.signal_type)}22`, padding: "0 6px",
              border: `1px solid ${sc(dispSig.signal_type)}`,
            }}>
              {dispSig.signal_type}
            </span>
          </div>

          <RText
            text={(dispSig.asset_name || dispSig.symbol || "")
              .replace("OTC_", "").replace(/_/g, "/") +
              (dispSig.symbol?.includes("OTC") ? " OTC" : "")}
            max={16} min={9} w={900}
          />

          <div style={{ display: "flex", gap: "8px", marginTop: "4px", flexWrap: "wrap" }}>
            {[
              ["Payout", dispSig.payout_pct ? `${dispSig.payout_pct}%` : null],
              ["CCI",    dispSig.cci?.toFixed(0)],
              ["Score",  `${((dispSig.quality_score || 0) * 100).toFixed(0)}%`],
              ["Exp",    "2 MIN"],
            ].map(([k, v]) => v ? (
              <span key={k} style={{ fontSize: "9px", fontFamily: "monospace" }}>
                <span style={{ color: T.muted }}>{k} </span>
                <span style={{ color: T.text, fontWeight: 700 }}>{v}</span>
              </span>
            ) : null)}
          </div>

          {dispSig.reasons_text && (
            <div style={{ fontSize: "9px", color: T.sub, fontFamily: "monospace", marginTop: "4px", lineHeight: 1.4 }}>
              {dispSig.reasons_text}
            </div>
          )}

          {blocked && (
            <div style={{ marginTop: "5px", background: "#1a0505", border: `1px solid ${T.put}`, padding: "4px 6px" }}>
              <div style={{ fontSize: "9px", fontWeight: 900, color: T.put, fontFamily: "monospace" }}>🛑 OPERACIÓN BLOQUEADA</div>
              <div style={{ fontSize: "8.5px", color: "#cc4444", fontFamily: "monospace", marginTop: "1px" }}>
                {cb.reason?.replace("🛑 ", "")}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Aparato Crítico */}
      <div style={{
        fontSize: "9px", color: T.muted, fontFamily: "monospace", letterSpacing: ".14em",
        padding: "3px 8px", borderBottom: `1px solid ${T.border}`, flexShrink: 0, background: T.surface,
      }}>
        ◈ APARATO CRÍTICO
      </div>

      <div style={{ flex: 1, overflowY: "auto", scrollbarWidth: "none" }}>
        <Dx label="EFECTIVIDAD DE SEÑALES"   val={wr  != null ? `${wr}%`       : null} color={wrH.color}  icon={wrH.icon}  status={wrH.status}
            note="Win Rate. Umbral profesional: >60% verde · 50–60% precaución · <50% peligro."
            sub={wr  != null ? (wrH.status  === "success" ? "✓ Operando sobre umbral"    : wrH.status  === "warning" ? "⚡ En zona de precaución"  : "✗ Por debajo del umbral mínimo") : null}/>
        <Dx label="SALUD DE CUENTA"          val={pf  != null ? pf.toFixed(2)  : null} color={pfH.color}  icon={pfH.icon}  status={pfH.status}
            note="Profit Factor. >1.20 verde · 1.05–1.20 precaución · <1.05 peligro."
            sub={pf  != null ? (pfH.status  === "success" ? "✓ Sistema rentable"         : pfH.status  === "warning" ? "⚡ Margen estrecho"         : "✗ Sistema en pérdida")        : null}/>
        <Dx label="RIESGO DE RETROCESO (MAE)"val={mae != null ? `${mae} pips`  : null} color={maeH.color} icon={maeH.icon} status={maeH.status}
            note="Max Adverse Excursion. <10 pips verde · 10–20 precaución · >20 peligro."
            sub={mae != null ? (maeH.status === "success" ? "✓ Retroceso controlado"     : maeH.status === "warning" ? "⚡ Retroceso moderado"      : "✗ Alto retroceso — revisar SL"): null}/>
        <Dx label="CALIDAD DE CONEXIÓN"      val={lat != null ? `${lat} ms`    : null} color={latH.color} icon={latH.icon} status={latH.status}
            note="Latencia de señal. <100ms verde · 100–300ms precaución · >300ms peligro."
            sub={lat != null ? (latH.status === "success" ? "✓ Conexión óptima"          : latH.status === "warning" ? "⚡ Latencia aceptable"      : "✗ Alta latencia — no operar") : null}/>

        {/* Sesión */}
        <div style={{ padding: "7px 10px", borderBottom: `1px solid ${T.border}` }}>
          <div style={{ fontSize: "9px", color: T.muted, fontFamily: "monospace", letterSpacing: ".08em", marginBottom: "5px" }}>SESIÓN</div>
          <div style={{ display: "flex", justifyContent: "space-between" }}>
            {[
              { label: "Ops",  val: ops, c: T.text },
              { label: "Wins", val: w,   c: T.call },
              { label: "Loss", val: l,   c: T.put  },
              { label: "WR",   val: wr != null ? `${wr}%` : "—", c: wrH.color },
            ].map(({ label, val, c }) => (
              <div key={label} style={{ textAlign: "center" }}>
                <div style={{ fontSize: "16px", fontWeight: 900, fontFamily: "'IBM Plex Mono',monospace", color: c, lineHeight: 1 }}>{val}</div>
                <div style={{ fontSize: "8px", color: T.muted, fontFamily: "monospace", marginTop: "2px" }}>{label}</div>
              </div>
            ))}
          </div>
        </div>

        {session && (
          <div style={{ padding: "5px 10px", fontSize: "9px", color: T.dim, fontFamily: "monospace", lineHeight: 1.4 }}>
            {session}
          </div>
        )}
      </div>
    </div>
  );
});
