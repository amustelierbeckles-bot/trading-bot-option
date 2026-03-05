/**
 * KPIStrip.jsx — Banda de métricas superiores (CALL / PUT / SEÑALES / ALERTANDO)
 */
import { memo, useRef, useEffect } from "react";
import { T } from "../../utils/dashboardUtils";
import { Ico } from "./Header";

export const KPIStrip = memo(({ signals, preAlerts }) => {
  const calls  = signals.filter(s => s.signal_type === "CALL").length;
  const puts   = signals.filter(s => s.signal_type === "PUT").length;
  const fires  = signals.filter(s => (s.quality_score || 0) >= 0.8).length;
  const alerts = Object.keys(preAlerts).length;

  const kpis = [
    { l: "CALL",      v: calls,  c: T.call, ico: Ico.arrowU },
    { l: "PUT",       v: puts,   c: T.put,  ico: Ico.arrowD },
    { l: "SEÑALES",   v: fires,  c: T.fire, ico: Ico.wave   },
    { l: "ALERTANDO", v: alerts, c: T.pre,  ico: Ico.bell   },
  ];

  return (
    <div style={{ display: "flex", gap: "1px", flexShrink: 0, height: "46px", borderBottom: `1px solid ${T.border}` }}>
      {kpis.map(k => (
        <div key={k.l} style={{
          flex: 1, display: "flex", alignItems: "center", gap: "10px",
          padding: "0 16px",
          background: k.v > 0 ? `${k.c}12` : "#0a0a0a",
          borderRight: "1px solid #1e1e1e", transition: "background .3s",
        }}>
          <span style={{
            color: k.c, opacity: k.v > 0 ? 0.9 : 0.25, flexShrink: 0,
            filter: k.v > 0 ? `drop-shadow(0 0 4px ${k.c})` : "none",
            display: "flex", alignItems: "center",
          }}>
            {k.ico}
          </span>
          <span style={{
            fontSize: "26px", fontWeight: 800,
            fontFamily: "'IBM Plex Mono',monospace", color: k.c, lineHeight: 1,
            textShadow: k.v > 0 ? `0 0 14px ${k.c}99` : "none",
          }}>
            {k.v}
          </span>
          <span style={{
            fontSize: "9px", fontWeight: 800, color: k.c,
            letterSpacing: ".14em", fontFamily: "monospace",
            opacity: k.v > 0 ? 0.9 : 0.3, lineHeight: 1,
          }}>
            {k.l}
          </span>
        </div>
      ))}
    </div>
  );
});

/**
 * LogFeed.jsx — Feed de logs del sistema
 */
export const LogFeed = memo(({ logs }) => {
  const end = useRef(null);
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth" }); }, [logs]);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", background: T.surface }}>
      <div style={{
        padding: "3px 8px", fontSize: "9px", color: T.muted, letterSpacing: ".14em",
        borderBottom: `1px solid ${T.border}`, flexShrink: 0, fontFamily: "monospace",
      }}>
        ◈ SISTEMA · LOG
      </div>
      <div style={{ flex: 1, overflowY: "auto", scrollbarWidth: "none", padding: "2px 0" }}>
        {logs.map((l, i) => (
          <div key={i} style={{
            padding: "1.5px 8px", fontSize: "10.5px",
            fontFamily: "'IBM Plex Mono',monospace",
            color: l.c || T.muted,
            opacity: 0.2 + (i / Math.max(logs.length - 1, 1)) * 0.8,
            whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", lineHeight: 1.4,
          }}>
            <span style={{ color: T.dim, marginRight: "5px" }}>{l.t}</span>{l.m}
          </div>
        ))}
        <div ref={end} />
      </div>
    </div>
  );
});

/**
 * Spark.jsx — Mini sparkline SVG con gradiente
 */
export const Spark = memo(({ data, color, h = 28 }) => {
  if (!data?.length || data.length < 2) return <div style={{ height: `${h}px` }} />;
  const W = 100, H = h;
  const lo = Math.min(...data), hi = Math.max(...data), rng = hi - lo || 1;
  const pts = data.map((v, i) => {
    const x = (i / (data.length - 1)) * W;
    const y = H - ((v - lo) / rng) * (H - 2) - 1;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const gradId = `sg${color.replace(/[^a-zA-Z0-9]/g, "")}`;
  const pathD  = `M ${pts.split(" ")[0]} L ${pts.split(" ").slice(1).join(" L ")} L ${W},${H} L 0,${H} Z`;

  return (
    <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ display: "block" }}>
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%"   stopColor={color} stopOpacity="0.18" />
          <stop offset="100%" stopColor={color} stopOpacity="0"    />
        </linearGradient>
      </defs>
      <path d={pathD} fill={`url(#${gradId})`} />
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" opacity=".9" />
    </svg>
  );
});
