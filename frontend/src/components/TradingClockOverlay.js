/**
 * TradingClockOverlay
 *
 * Muestra el countdown del dashboard Y permite abrir una ventana
 * emergente independiente (pop-out) para ver el reloj mientras
 * operas en Pocket Option.
 *
 * Pop-out: window.open → postMessage en tiempo real → auto-cierre.
 */
import { useState, useEffect, useRef } from "react";

// ─── Constantes ───────────────────────────────────────────────────────────────
const DURATION = 120; // segundos por señal

// ─── Helpers ──────────────────────────────────────────────────────────────────
function secsLeft(ts) {
  if (!ts) return 0;
  const s = typeof ts === "string" ? ts : String(ts);
  const utc = s.endsWith("Z") || s.includes("+") ? s : s + "Z";
  return Math.max(0, DURATION - Math.floor((Date.now() - new Date(utc).getTime()) / 1000));
}

function fmt(s) {
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

// ─── HTML de la ventana pop-out (inyectado vía document.write) ───────────────
function buildPopupHTML(signal, secs) {
  const isCall = signal.type === "CALL" || signal.type === "BUY";
  const color  = isCall ? "#00FF94" : "#FF0055";

  return `<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>${signal.asset_name} ${signal.type}</title>
<style>
  *{margin:0;padding:0;box-sizing:border-box}
  html,body{
    width:100%;height:100%;
    background:#06060a;
    display:flex;flex-direction:column;
    align-items:center;justify-content:center;
    overflow:hidden;user-select:none;
    font-family:'Courier New',monospace;
  }
  #label{
    font-size:11px;letter-spacing:.18em;
    text-transform:uppercase;color:#ffffff66;margin-bottom:6px;
  }
  #timer{
    font-size:60px;font-weight:900;
    line-height:1;letter-spacing:.06em;
    transition:color .2s;
  }
  #warn{
    font-size:10px;letter-spacing:.14em;
    color:#F59E0B;margin-top:6px;display:none;
  }
  #track{
    width:78%;height:3px;
    background:rgba(255,255,255,.07);
    border-radius:999px;overflow:hidden;margin-top:10px;
  }
  #bar{height:100%;border-radius:999px;transition:width .3s linear}
  #foot{
    font-size:9px;color:#ffffff22;
    letter-spacing:.12em;margin-top:8px;
  }
  @keyframes blink{0%,100%{opacity:1}50%{opacity:.05}}
  .blink{animation:blink .42s step-start infinite}
</style>
</head>
<body>
  <div id="label">${isCall ? "▲" : "▼"} ${signal.asset_name} · ${signal.type}</div>
  <div id="timer" style="color:${color};text-shadow:0 0 24px ${color}88">${fmt(secs)}</div>
  <div id="warn">⚡ ENTRADA INMINENTE</div>
  <div id="track"><div id="bar" style="background:${color};width:${(secs/DURATION)*100}%;box-shadow:0 0 8px ${color}"></div></div>
  <div id="foot">BOT · EXP 2 MIN</div>

<script>
const DURATION=120;
const timerEl=document.getElementById('timer');
const barEl=document.getElementById('bar');
const warnEl=document.getElementById('warn');

window.addEventListener('message',function(e){
  if(!e.data||e.data.type!=='CLOCK_UPDATE') return;
  const{secs,color,done}=e.data;
  if(done){window.close();return;}

  timerEl.textContent=Math.floor(secs/60)+':'+(secs%60<10?'0':'')+(secs%60);
  barEl.style.width=((secs/DURATION)*100)+'%';

  if(secs<=5){
    timerEl.classList.add('blink');
    timerEl.style.color='#EF4444';
    timerEl.style.textShadow='0 0 24px #EF444488';
    warnEl.style.display='block';
    barEl.style.background='#EF4444';
    barEl.style.boxShadow='0 0 8px #EF4444';
  } else {
    timerEl.classList.remove('blink');
    timerEl.style.color=color;
    timerEl.style.textShadow='0 0 24px '+color+'88';
    warnEl.style.display='none';
    barEl.style.background=color;
    barEl.style.boxShadow='0 0 8px '+color;
  }
});
</script>
</body></html>`;
}

// ─────────────────────────────────────────────────────────────────────────────
// COMPONENTE
// ─────────────────────────────────────────────────────────────────────────────
export default function TradingClockOverlay({ clockInfo, onExpire, debugSignal }) {
  const signal  = debugSignal || (clockInfo && clockInfo.signal) || null;
  const [secs,  setSecs]    = useState(() => signal ? secsLeft(signal.timestamp) : DURATION);
  const [popped, setPopped] = useState(false);

  const tickRef   = useRef(null);
  const popupRef  = useRef(null);

  // ── Tick principal ──────────────────────────────────────────────────────────
  useEffect(() => {
    clearInterval(tickRef.current);
    if (!signal?.timestamp) return;

    const run = () => {
      const left = secsLeft(signal.timestamp);
      setSecs(left);

      // Sincroniza con el popup si está abierto
      if (popupRef.current && !popupRef.current.closed) {
        const isCall = signal.type === "CALL" || signal.type === "BUY";
        popupRef.current.postMessage({
          type:  "CLOCK_UPDATE",
          secs:  left,
          color: left <= 5 ? "#EF4444" : isCall ? "#00FF94" : "#FF0055",
          done:  left <= 0,
        }, "*");
      }

      if (left <= 0) {
        clearInterval(tickRef.current);
        if (popupRef.current && !popupRef.current.closed) popupRef.current.close();
        setPopped(false);
        onExpire?.();
      }
    };

    run();
    tickRef.current = setInterval(run, 300);
    return () => clearInterval(tickRef.current);
  }, [signal?.id, signal?.timestamp]); // deps estables: primitivos únicos por señal

  // Cierra el popup si el componente se desmonta
  useEffect(() => {
    return () => {
      clearInterval(tickRef.current);
      if (popupRef.current && !popupRef.current.closed) popupRef.current.close();
    };
  }, []);

  // ── Abrir ventana pop-out ───────────────────────────────────────────────────
  function openPopup() {
    if (!signal) return;

    // Cierra popup anterior si existe
    if (popupRef.current && !popupRef.current.closed) popupRef.current.close();

    const w = 240, h = 170;
    const left = window.screen.width  - w - 20;
    const top  = window.screen.height - h - 60;

    const popup = window.open(
      "",
      "trading_clock_popup",
      `width=${w},height=${h},left=${left},top=${top},` +
      `menubar=no,toolbar=no,location=no,status=no,` +
      `resizable=yes,scrollbars=no`
    );

    if (!popup) {
      alert("⚠ Permite ventanas emergentes para esta función.\n\nHaz clic en el ícono de la barra de dirección y permite popups para localhost.");
      return;
    }

    popup.document.write(buildPopupHTML(signal, secs));
    popup.document.close();
    popupRef.current = popup;
    setPopped(true);

    // Detecta si el usuario cierra la popup manualmente
    const checkClosed = setInterval(() => {
      if (popup.closed) { setPopped(false); clearInterval(checkClosed); }
    }, 500);
  }

  // ── No renderiza si no hay señal ────────────────────────────────────────────
  if (!signal) return null;

  const isCall  = signal.type === "CALL" || signal.type === "BUY";
  const critical = secs > 0 && secs <= 5;
  const pct     = Math.max(0, (secs / DURATION) * 100);
  const color   = critical ? "#EF4444" : isCall ? "#00FF94" : "#FF0055";

  return (
    <div style={{
      position:      "fixed",
      top:           90,
      left:          "50%",
      transform:     "translateX(-50%)",
      zIndex:        2147483647,
      userSelect:    "none",
    }}>
      {/* Cápsula glassmorphism */}
      <div style={{
        background:           "rgba(6,6,10,0.91)",
        backdropFilter:       "blur(24px) saturate(2)",
        WebkitBackdropFilter: "blur(24px) saturate(2)",
        border:               `1.5px solid ${color}30`,
        borderRadius:         18,
        padding:              "12px 28px 10px",
        minWidth:             240,
        textAlign:            "center",
        boxShadow:            `0 0 48px ${color}44, 0 4px 28px rgba(0,0,0,.75)`,
        position:             "relative",
      }}>

        {/* Botón pop-out — único elemento clickable */}
        <button
          onClick={openPopup}
          title={popped ? "Ventana flotante abierta" : "Abrir reloj en ventana flotante"}
          style={{
            position:   "absolute",
            top:        8, right: 8,
            background: popped ? color + "30" : "rgba(255,255,255,0.07)",
            border:     `1px solid ${popped ? color + "60" : "rgba(255,255,255,0.12)"}`,
            borderRadius: 6,
            color:      popped ? color : "rgba(255,255,255,0.4)",
            cursor:     "pointer",
            padding:    "3px 5px",
            fontSize:   11,
            lineHeight: 1,
            pointerEvents: "all",
            transition: "all .2s",
          }}
          onMouseEnter={e => e.target.style.opacity = "0.8"}
          onMouseLeave={e => e.target.style.opacity = "1"}
        >
          {popped ? "⧉✓" : "⧉"}
        </button>

        {/* Línea de brillo */}
        <div style={{
          position: "absolute", top: 0, left: "10%", right: "10%", height: 1,
          background: `linear-gradient(90deg,transparent,${color}50,transparent)`,
        }} />

        {/* Etiqueta par + tipo */}
        <div style={{
          fontSize: 10, letterSpacing: "0.2em", textTransform: "uppercase",
          color: color + "88", marginBottom: 5,
          fontFamily: "'JetBrains Mono', monospace",
          pointerEvents: "none",
        }}>
          {isCall ? "▲" : "▼"} {signal.asset_name} · {signal.type}
        </div>

        {/* DÍGITOS */}
        <div style={{
          fontSize:           64,
          fontWeight:         900,
          lineHeight:         1,
          color,
          letterSpacing:      "0.06em",
          textShadow:         `0 0 24px ${color}99, 0 0 48px ${color}44`,
          fontFamily:         "'JetBrains Mono', monospace",
          fontVariantNumeric: "tabular-nums",
          pointerEvents:      "none",
          animation:          critical ? "blink_c .42s step-start infinite" : "none",
        }}>
          {fmt(secs)}
        </div>

        {/* Alerta crítica */}
        {critical && (
          <div style={{
            fontSize: 10, color: "#F59E0B", letterSpacing: "0.14em",
            marginTop: 4, fontFamily: "monospace",
            textShadow: "0 0 10px #F59E0B", pointerEvents: "none",
          }}>⚡ ENTRADA INMINENTE</div>
        )}

        {/* Barra progreso */}
        <div style={{
          marginTop: 10, height: 3,
          background: "rgba(255,255,255,.06)",
          borderRadius: 999, overflow: "hidden",
          pointerEvents: "none",
        }}>
          <div style={{
            height: "100%", width: `${pct}%`,
            background: `linear-gradient(90deg,${color}60,${color})`,
            borderRadius: 999, boxShadow: `0 0 8px ${color}`,
            transition: "width .3s linear",
          }} />
        </div>

        {/* Pie */}
        <div style={{
          fontSize: 8, color: "rgba(255,255,255,.2)", letterSpacing: "0.12em",
          marginTop: 6, fontFamily: "monospace", pointerEvents: "none",
        }}>
          {popped ? "⧉ RELOJ FLOTANTE ACTIVO" : "EXP · 2 MIN · PULSA ⧉ PARA FLOTAR"}
        </div>
      </div>

      {/* Keyframe blink inline */}
      <style>{`@keyframes blink_c{0%,100%{opacity:1}50%{opacity:.05}}`}</style>
    </div>
  );
}


