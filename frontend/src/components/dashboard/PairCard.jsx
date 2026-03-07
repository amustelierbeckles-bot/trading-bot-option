/**
 * PairCard.jsx — Tarjeta de par OTC con precio, sparkline, indicadores
 * y historial W/L persistido en localStorage.
 *
 * v4.0: Se añade la sección de historial W/L:
 *   - Cuadros coloreados (verde=W, rojo=L) con los últimos resultados
 *   - Badge con Win Rate % calculado sobre todos los resultados del par
 *   - Tooltip al hover sobre el badge mostrando distribución W/L
 */
import { memo, useState } from "react";
import { T, sc, fmt } from "../../utils/dashboardUtils";
import { RText } from "./Primitives";
import { Spark } from "./Widgets";
import { readWLHistory, getWinRate } from "../../utils/wlHistory";

export const PairCard = memo(({ sym, data, sig, pre, hovTerm, setHovTerm, onSelect, selected, maeAlert, wlVersion }) => {
  const hasSig = !!sig;
  const hasPre = !!pre && !hasSig;
  const chg    = data?.change_pct;
  const chgDir = chg != null ? (chg >= 0 ? T.call : T.put) : null;
  const ac     = hasSig ? sc(sig.signal_type) : hasPre ? T.pre : chgDir || T.muted;

  const name   = sym.replace("OTC_", "").replace(/_/g, "/") + " OTC";
  const ind    = data?.indicators || {};
  const prices = data?.prices     || [];

  // ── Historial W/L ─────────────────────────────────────────────────────────
  // wlVersion como dependencia implícita: cuando cambia, memo() re-evalúa
  // porque la prop cambia → readWLHistory devuelve los datos frescos.
  const history  = readWLHistory(sym);           // leyendo localStorage
  const winRate  = getWinRate(sym);              // null si no hay datos
  const recentWL = history.slice(-10);           // últimos 10 para mostrar
  const [wrHov, setWrHov] = useState(false);

  const tags = [
    { k: "RSI", v: ind.rsi     != null ? ind.rsi.toFixed(0)               : null },
    { k: "BB",  v: ind.bb_pct  != null ? `${(ind.bb_pct*100).toFixed(0)}%`: null },
    { k: "CCI", v: ind.cci     != null ? ind.cci.toFixed(0)                : null },
    { k: "ATR", v: ind.atr_pct != null ? (ind.atr_pct*100).toFixed(3)     : null },
    { k: "MAE", v: ind.mae     != null ? ind.mae.toFixed(1)                : null },
  ];

  // Color del Win Rate badge
  const wrColor = winRate == null ? T.dim
    : winRate >= 65 ? T.call
    : winRate >= 50 ? T.fire
    : T.put;

  return (
    <div
      onClick={() => onSelect(sig || null)}
      style={{
        background:  hasSig ? `${ac}0e` : selected ? `${T.violet}0e` : "#0F0F0F",
        border:      `1px solid ${hasSig ? ac : selected ? T.violet : chgDir ? `${chgDir}44` : "#333333"}`,
        borderTop:   `2px solid ${hasSig ? ac : hasPre ? T.pre : chgDir ? `${chgDir}cc` : "#333333"}`,
        padding: "6px 7px 5px", display: "flex", flexDirection: "column", gap: "2px",
        minWidth: 0, cursor: "pointer",
        animation: hasSig ? "cardpulse 2.5s ease-in-out infinite" : maeAlert ? "maepanic 2s ease-in-out infinite" : "none",
        transition: "border-color .25s",
      }}
    >
      {/* Top: nombre + precio */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "4px" }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <RText text={name} max={13} min={8} w={900} color={T.text} />
        </div>
        <div style={{ textAlign: "right", flexShrink: 0 }}>
          <div style={{ fontSize: "12px", fontWeight: 700, fontFamily: "monospace", color: T.text, lineHeight: 1 }}>
            {data?.price ? fmt(data.price, 5) : "—"}
          </div>
          {chg != null && (
            <div style={{ fontSize: "9px", fontFamily: "monospace", color: chg >= 0 ? T.call : T.put, lineHeight: 1 }}>
              {chg >= 0 ? "▲" : "▼"}{Math.abs(chg).toFixed(3)}%
            </div>
          )}
        </div>
      </div>

      {/* Sparkline */}
      <Spark data={prices} color={ac} h={26} />

      {/* Badge señal */}
      {hasSig && (
        <div style={{
          background: `${ac}1a`, border: `1px solid ${ac}`, color: ac,
          fontSize: "9px", fontWeight: 900, fontFamily: "monospace",
          padding: "1px 4px", textAlign: "center", letterSpacing: ".1em",
        }}>
          {sig.signal_type} · {((sig.quality_score || 0) * 100).toFixed(0)}%
        </div>
      )}

      {/* Badge pre-alerta */}
      {hasPre && (
        <div style={{
          background: `${T.pre}0e`, border: `1px solid ${T.pre}44`, color: T.pre,
          fontSize: "8.5px", fontFamily: "monospace", padding: "1px 4px", textAlign: "center",
          animation: "blinkslw 1.8s ease-in-out infinite",
        }}>
          ⏳ {pre.confluence_pct}%
        </div>
      )}

      {/* Tags de indicadores */}
      <div style={{ display: "flex", gap: "2px", flexWrap: "wrap" }}>
        {tags.map(({ k, v }) => {
          const hot = hovTerm === k;
          return (
            <span key={k}
              onMouseEnter={e => { e.stopPropagation(); setHovTerm(k); }}
              onMouseLeave={() => setHovTerm(null)}
              style={{
                fontSize: "8.5px", fontFamily: "monospace", padding: "0 3px", lineHeight: "14px",
                background: hot ? `${T.violet}18` : "#0e0e0e",
                color:      hot ? T.violet : v ? "#3a3a3a" : T.dim,
                border:     `1px solid ${hot ? T.violet : T.border}`,
                cursor: "help", transition: "all .1s",
              }}
            >
              {k}{v != null ? ` ${v}` : ""}
            </span>
          );
        })}
      </div>

      {/* ── Historial W/L ──────────────────────────────────────────────────── */}
      {recentWL.length > 0 && (
        <div
          style={{ display: "flex", alignItems: "center", gap: "2px", marginTop: "1px" }}
          onClick={e => e.stopPropagation()}
        >
          {/* Cuadros W/L */}
          <div style={{ display: "flex", gap: "1px", flex: 1, minWidth: 0 }}>
            {recentWL.map((entry, i) => (
              <div key={i} style={{
                width: "10px", height: "10px", flexShrink: 0,
                background: entry.r === "W" ? `${T.call}22` : `${T.put}22`,
                border:     `1px solid ${entry.r === "W" ? T.call : T.put}`,
                display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: "6px", fontFamily: "monospace", fontWeight: 700,
                color: entry.r === "W" ? T.call : T.put,
                lineHeight: 1,
              }}>
                {entry.r}
              </div>
            ))}
          </div>

          {/* Badge Win Rate con tooltip */}
          {winRate != null && (
            <div
              onMouseEnter={() => setWrHov(true)}
              onMouseLeave={() => setWrHov(false)}
              style={{ position: "relative", flexShrink: 0 }}
            >
              <div style={{
                fontSize: "8px", fontFamily: "monospace", fontWeight: 700,
                color: wrColor, padding: "0 3px", lineHeight: "12px",
                background: `${wrColor}15`,
                border: `1px solid ${wrColor}55`,
                cursor: "help",
              }}>
                {winRate}%
              </div>

              {/* Tooltip al hover */}
              {wrHov && (
                <div style={{
                  position: "absolute", bottom: "calc(100% + 4px)", right: 0,
                  background: "#111", border: `1px solid ${T.border}`,
                  borderRadius: "4px", padding: "5px 8px",
                  fontSize: "9px", fontFamily: "monospace", color: T.text,
                  whiteSpace: "nowrap", zIndex: 100,
                  boxShadow: "0 4px 12px rgba(0,0,0,.6)",
                }}>
                  <div style={{ fontWeight: 700, marginBottom: "3px", color: wrColor }}>
                    {sym.replace("OTC_", "")} · {winRate}% WR
                  </div>
                  <div style={{ color: T.call }}>✅ W: {history.filter(e => e.r === "W").length}</div>
                  <div style={{ color: T.put  }}>❌ L: {history.filter(e => e.r === "L").length}</div>
                  <div style={{ color: T.sub, marginTop: "2px" }}>
                    Total: {history.length} ops
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
});
