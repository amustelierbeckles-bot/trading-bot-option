/**
 * Header.jsx — Cabecera RADAR con botones de navegación y escaneo
 */
import { memo } from "react";
import { T } from "../../utils/dashboardUtils";

// ── SVG Icons ─────────────────────────────────────────────────────────────────
export const Ico = {
  chart:   <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>,
  gauge:   <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 2a10 10 0 0 1 7.38 16.75"/><path d="M12 2a10 10 0 0 0-7.38 16.75"/><line x1="12" y1="12" x2="15.2" y2="8.8"/><circle cx="12" cy="12" r="1.5"/></svg>,
  refresh: <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>,
  bolt:    <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>,
  arrowU:  <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><polygon points="12 4 20 20 4 20"/></svg>,
  arrowD:  <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><polygon points="12 20 4 4 20 4"/></svg>,
  wave:    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><path d="M2 12 C5 6, 8 18, 12 12 C16 6, 19 18, 22 12"/></svg>,
  bell:    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>,
};

// ── HdrBtn ────────────────────────────────────────────────────────────────────
const HdrBtn = ({ icon, label, onClick, accent }) => (
  <button onClick={onClick} style={{
    display: "flex", alignItems: "center", gap: "5px",
    background: "transparent",
    color:  accent || T.muted,
    border: `1px solid ${accent ? `${accent}55` : T.border}`,
    padding: "2px 9px", fontSize: "10px",
    fontWeight: 700, fontFamily: "monospace", cursor: "pointer",
    letterSpacing: ".05em", transition: "all .15s", height: "22px",
  }}
  onMouseEnter={e => { e.currentTarget.style.color = accent || T.text; e.currentTarget.style.borderColor = accent || "#555"; }}
  onMouseLeave={e => { e.currentTarget.style.color = accent || T.muted; e.currentTarget.style.borderColor = accent ? `${accent}55` : T.border; }}
  >
    {icon}
    <span>{label}</span>
  </button>
);

// ── Header ────────────────────────────────────────────────────────────────────
export const Header = memo(({ session, utc5, latMs, latAlert, onScan, scanning, onNav, onRefresh }) => (
  <header style={{
    display: "flex", alignItems: "center", gap: "8px",
    padding: "0 12px", height: "36px", flexShrink: 0,
    borderBottom: `1px solid ${T.border}`, background: T.surface,
    outline: latAlert ? `1px solid ${T.violet}55` : "none",
  }}>
    <span style={{ fontSize: "15px", fontWeight: 900, color: T.call, fontFamily: "'IBM Plex Mono',monospace", letterSpacing: "-0.06em" }}>⬡ RADAR</span>
    <span style={{ fontSize: "9px", color: T.dim, fontFamily: "monospace" }}>v2.9</span>

    {session && (
      <div style={{
        fontSize: "9px", fontWeight: 700, color: T.call,
        background: "#001a0d", padding: "1px 7px",
        border: `1px solid ${T.call}33`, fontFamily: "monospace", letterSpacing: ".06em",
      }}>
        {session}
      </div>
    )}

    <span style={{ fontSize: "10px", color: T.muted, fontFamily: "monospace" }}>· UTC-5 {utc5}</span>

    {latAlert && (
      <span style={{ fontSize: "10px", color: T.violet, fontFamily: "monospace", animation: "blink .6s step-end infinite" }}>
        ⚠ {latMs}ms
      </span>
    )}

    <div style={{ flex: 1 }} />

    <HdrBtn icon={Ico.chart}   label="Backtesting" onClick={() => onNav("/backtesting")} />
    <HdrBtn icon={Ico.gauge}   label="Rendimiento"  onClick={() => onNav("/performance")} />
    <HdrBtn icon={Ico.refresh} label="Actualizar"   onClick={onRefresh} />

    <button onClick={onScan} disabled={scanning} style={{
      display: "flex", alignItems: "center", gap: "5px",
      background: scanning ? `${T.call}18` : `${T.call}0d`,
      color: T.call, border: `1px solid ${T.call}`,
      padding: "2px 11px", fontSize: "10px", fontWeight: 900,
      cursor: "pointer", fontFamily: "monospace", letterSpacing: ".08em", height: "22px",
    }}>
      {Ico.bolt}
      <span>{scanning ? "ESCANEANDO…" : "ESCANEAR"}</span>
    </button>
  </header>
));
