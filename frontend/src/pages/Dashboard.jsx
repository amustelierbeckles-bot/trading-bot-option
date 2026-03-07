/**
 * Dashboard.jsx — RADAR v2.9
 * Layout: Timer izquierdo · Grid central · Aparato Crítico derecho
 *
 * Este archivo ahora solo hace UNA cosa: componer el layout.
 * Toda la lógica está en hooks/useDashboard.js
 * Todos los componentes están en components/dashboard/
 */
import React from "react";
import { useNavigate } from "react-router-dom";

import ActiveSignalBanner  from "../components/ActiveSignalBanner.js";
import TradingClockOverlay from "../components/TradingClockOverlay.js";

import useDashboard from "../hooks/useDashboard";
import { T } from "../utils/dashboardUtils";

import { StatusBar }  from "../components/dashboard/Primitives";
import { Splitter }   from "../components/dashboard/Primitives";
import { Header }     from "../components/dashboard/Header";
import { CBBar }      from "../components/dashboard/CBBar";
import { KPIStrip }   from "../components/dashboard/Widgets";
import { TimerPanel } from "../components/dashboard/TimerPanel";
import { PairCard }   from "../components/dashboard/PairCard";
import { RightPanel } from "../components/dashboard/RightPanel";

export default function Dashboard() {
  const navigate = useNavigate();

  const {
    signals, preAlerts, mktData, stats, risk, logs,
    scanning, session, utc5, latMs, latAlert, tradeAct,
    hovTerm, selSig, panes, maeAlert, wrapRef,
    wlVersion,
    setHov, setSelSig, setMaeAlert,
    scan, refresh, newSession, dragL, dragR,
    sigMap, topSig, pairs,
  } = useDashboard();

  return (
    <>
      {/* ── Estilos globales ── */}
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;700&display=swap');
        *{box-sizing:border-box;margin:0;padding:0;}
        body{background:#000;color:#E0E0E0;overflow:hidden;
             font-family:'IBM Plex Mono','Courier New',monospace;}
        ::-webkit-scrollbar{width:3px;height:3px;}
        ::-webkit-scrollbar-thumb{background:#1c1c1c;}
        ::-webkit-scrollbar-track{background:transparent;}
        @keyframes pulsebar{0%,100%{opacity:1;filter:brightness(1);}50%{opacity:.5;filter:brightness(1.5);}}
        @keyframes cardpulse{0%,100%{box-shadow:none;}50%{box-shadow:0 0 10px rgba(0,255,148,.1);}}
        @keyframes blink{0%,100%{opacity:1;}50%{opacity:0;}}
        @keyframes blinkslw{0%,100%{opacity:1;}50%{opacity:.3;}}
        @keyframes maepanic{0%,100%{border-color:var(--card-border,#333);}50%{border-color:#FF313166;}}
      `}</style>

      {/* Barra de estado top */}
      <StatusBar active={tradeAct} />

      <div style={{ display: "flex", flexDirection: "column", height: "100vh", paddingTop: "4px", background: T.bg }}>

        {/* Header */}
        <Header
          session={session} utc5={utc5} latMs={latMs} latAlert={latAlert}
          onScan={scan} scanning={scanning}
          onNav={navigate} onRefresh={refresh}
        />

        {/* Circuit Breaker */}
        <CBBar risk={risk} onNewSession={newSession} />

        {/* KPI Strip */}
        <KPIStrip signals={signals} preAlerts={preAlerts} />

        {/* Body: 3 columnas */}
        <div ref={wrapRef} style={{ display: "flex", flex: 1, overflow: "hidden", minHeight: 0 }}>

          {/* LEFT — Timer + Logs */}
          <div style={{ width: `${panes.L}px`, flexShrink: 0, overflow: "hidden", borderRight: `1px solid ${T.border}` }}>
            <TimerPanel signals={signals} risk={risk} logs={logs} />
          </div>

          <Splitter onDrag={dragL} />

          {/* CENTER — Grid de pares */}
          <div style={{ flex: 1, minWidth: 0, overflow: "auto", padding: "5px" }}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(155px,1fr))", gap: "4px" }}>
              {pairs.map(sym => (
                <PairCard
                  key={sym}
                  sym={sym}
                  data={mktData[sym]}
                  sig={sigMap[sym]}
                  pre={preAlerts[sym]}
                  hovTerm={hovTerm}
                  setHovTerm={setHov}
                  onSelect={s => setSelSig(prev => prev?.symbol === sym ? null : s)}
                  selected={selSig?.symbol === sym}
                  maeAlert={maeAlert}
                  wlVersion={wlVersion}
                />
              ))}
            </div>
          </div>

          <Splitter onDrag={dragR} />

          {/* RIGHT — Glosario + Señal + Aparato Crítico */}
          <div style={{ width: `${panes.R}px`, flexShrink: 0, overflow: "hidden", borderLeft: `1px solid ${T.border}`, display: "flex", flexDirection: "column" }}>
            <RightPanel
              hovTerm={hovTerm}
              topSig={topSig}
              selectedSig={selSig}
              stats={stats}
              session={session}
              risk={risk}
              onMaeAlert={setMaeAlert}
            />
          </div>

        </div>
      </div>

      <ActiveSignalBanner  signals={signals} />
      <TradingClockOverlay signals={signals} />
    </>
  );
}
