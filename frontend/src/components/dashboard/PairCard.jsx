/**
 * PairCard.jsx — Tarjeta de par OTC con precio, sparkline e indicadores
 */
import { memo } from "react";
import { T, sc, fmt } from "../../utils/dashboardUtils";
import { RText } from "./Primitives";
import { Spark } from "./Widgets";

export const PairCard = memo(({ sym, data, sig, pre, hovTerm, setHovTerm, onSelect, selected, maeAlert }) => {
  const hasSig = !!sig;
  const hasPre = !!pre && !hasSig;
  const chg    = data?.change_pct;
  const chgDir = chg != null ? (chg >= 0 ? T.call : T.put) : null;
  const ac     = hasSig ? sc(sig.signal_type) : hasPre ? T.pre : chgDir || T.muted;

  const name   = sym.replace("OTC_", "").replace(/_/g, "/") + " OTC";
  const ind    = data?.indicators || {};
  const prices = data?.prices     || [];

  const tags = [
    { k: "RSI", v: ind.rsi     != null ? ind.rsi.toFixed(0)               : null },
    { k: "BB",  v: ind.bb_pct  != null ? `${(ind.bb_pct*100).toFixed(0)}%`: null },
    { k: "CCI", v: ind.cci     != null ? ind.cci.toFixed(0)                : null },
    { k: "ATR", v: ind.atr_pct != null ? (ind.atr_pct*100).toFixed(3)     : null },
    { k: "MAE", v: ind.mae     != null ? ind.mae.toFixed(1)                : null },
  ];

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
    </div>
  );
});
