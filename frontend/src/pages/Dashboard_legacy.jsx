/**
 * RADAR v2.7 — Dashboard Principal
 * Layout: Timer izquierdo · Grid central · Aparato Crítico derecho
 * Barra de Risk + Circuit Breaker · KPI strip · Split Panes persistentes
 */
import React, {
  useState, useEffect, useRef, useCallback, useMemo, memo
} from "react";
import { useNavigate } from "react-router-dom";
import ActiveSignalBanner  from "../components/ActiveSignalBanner";
import TradingClockOverlay from "../components/TradingClockOverlay";
import { isSignalLive, getSecondsLeft, formatTime } from "../utils/signalTime";

const API = process.env.REACT_APP_BACKEND_URL || "http://localhost:8000";
const API_KEY = process.env.REACT_APP_API_KEY;

/* ── Design tokens ─────────────────────────────────────────────────────────── */
const T = {
  bg:      "#000",
  surface: "#090909",
  card:    "#0F0F0F",
  border:  "#333333",
  text:    "#E0E0E0",
  sub:     "#888",
  muted:   "#555",
  dim:     "#2a2a2a",
  call:    "#00FF41",   // Verde Neón Vibrante
  put:     "#FF3131",   // Rojo Brillante
  fire:    "#FFAC1C",   // Naranja Eléctrico
  pre:     "#00FFFF",   // Cian Eléctrico (Alertando)
  violet:  "#9D6FFF",
  idle:    "#2a2a2a",
  warn:    "#FF3131",
};
const sc = t => t==="CALL"?T.call:t==="PUT"?T.put:t==="FIRE"?T.fire:T.pre;
const fmt = (v,d=5) => v!=null ? Number(v).toFixed(d) : "—";
const PANE_KEY = "radar_v27_panes";

/* ─────────────────────────────────────────────────────────────────────────────
 * getHealthColor(value, type) — Semáforo de salud del Aparato Crítico
 *
 * Umbrales de trading profesional:
 *   win_rate:      > 60% verde | 50–60% amarillo | < 50% rojo
 *   profit_factor: > 1.20 verde | 1.05–1.20 amarillo | < 1.05 rojo
 *   mae:           < 10 verde  | 10–20 amarillo    | > 20 rojo
 *   latency:       < 100 verde | 100–300 amarillo   | > 300 rojo
 *
 * Returns: { color: hex, status: "success"|"warning"|"danger", icon: JSX }
 * ───────────────────────────────────────────────────────────────────────────*/
const HEALTH_COLORS = {
  success: "#00FF41",
  warning: "#FFAC1C",
  danger:  "#FF3131",
  unknown: "#555555",
};

const HEALTH_ICONS = {
  success: <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="#00FF41" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"/></svg>,
  warning: <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="#FFAC1C" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>,
  danger:  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="#FF3131" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>,
  unknown: null,
};

function getHealthColor(value, type) {
  if (value == null) return { color: HEALTH_COLORS.unknown, status: "unknown", icon: null };
  const v = Number(value);
  let status;
  switch (type) {
    case "win_rate":
      status = v > 60 ? "success" : v >= 50 ? "warning" : "danger"; break;
    case "profit_factor":
      status = v > 1.20 ? "success" : v >= 1.05 ? "warning" : "danger"; break;
    case "mae":
      status = v < 10 ? "success" : v <= 20 ? "warning" : "danger"; break;
    case "latency":
      status = v < 100 ? "success" : v <= 300 ? "warning" : "danger"; break;
    default:
      status = "unknown";
  }
  return { color: HEALTH_COLORS[status], status, icon: HEALTH_ICONS[status] };
}

/* ─────────────────────────────────────────────────────────────────────────────
 * normalizeBackendData(raw) — Adapta la respuesta del backend al esquema JSON
 * oficial del RADAR v2.9. Acepta tanto el formato legado como el nuevo.
 * ───────────────────────────────────────────────────────────────────────────*/
function normalizeStats(raw) {
  if (!raw) return null;
  // Si ya viene en formato crítico estructurado, extraer valores directamente
  const ca = raw.critical_apparatus;
  if (ca) {
    return {
      win_rate:      ca.win_rate?.value     ?? null,
      profit_factor: ca.profit_factor?.value?? null,
      mae_avg_pips:  ca.mae?.value          ?? null,
      latency_avg_ms:ca.latency?.value      ?? null,
      total_trades:  raw.total_trades       ?? 0,
      total_wins:    raw.total_wins         ?? 0,
      total_losses:  raw.total_losses       ?? 0,
    };
  }
  // Formato legado del backend (ya estructurado)
  return raw;
}

function normalizeSignals(raw) {
  if (!raw?.signals) return [];
  return raw.signals;
}

function normalizeMarketAsset(asset) {
  // Acepta el esquema JSON oficial del RADAR v2.9
  if (!asset) return null;
  return {
    price:      asset.price,
    change_pct: asset.change_pct,
    prices:     asset.sparkline_data || asset.prices || [],
    trend:      asset.trend,
    is_real:    asset.is_real ?? true,
  };
}


/* ── ResponsiveText ────────────────────────────────────────────────────────── */
const RText = memo(({text,max=22,min=8,w=900,color=T.text}) => {
  const el = useRef(null);
  const [fs,setFs] = useState(max);
  useEffect(()=>{
    const node=el.current; if(!node)return;
    let s=max; node.style.fontSize=`${s}px`;
    while(node.scrollWidth>node.clientWidth+1&&s>min){s-=.5;node.style.fontSize=`${s}px`;}
    setFs(s);
  },[text,max,min]);
  return <span ref={el} style={{fontSize:`${fs}px`,fontWeight:w,display:"block",
    whiteSpace:"nowrap",overflow:"hidden",lineHeight:1.05,letterSpacing:"-0.02em",
    color,fontFamily:"'IBM Plex Mono',monospace"}}>{text}</span>;
});

/* ── StatusBar 4px top ─────────────────────────────────────────────────────── */
const StatusBar = memo(({active}) => {
  const color = active==="CALL"?T.call:active==="PUT"?T.put:T.idle;
  const live  = active!=="IDLE";
  return <div style={{position:"fixed",top:0,left:0,right:0,height:"4px",zIndex:9999,
    background:live?`linear-gradient(90deg,transparent,${color} 20%,${color} 80%,transparent)`:color,
    boxShadow:live?`0 0 14px ${color}88`:"none",
    animation:live?"pulsebar 1.4s ease-in-out infinite":"none",transition:"background .4s"}}/>;
});

/* ── Splitter ──────────────────────────────────────────────────────────────── */
const Splitter = memo(({onDrag}) => {
  const [hot,setHot]=useState(false); const live=useRef(false);
  const down=(e)=>{e.preventDefault();live.current=true;
    const mv=(ev)=>{if(live.current)onDrag(ev.clientX);};
    const up=()=>{live.current=false;window.removeEventListener("mousemove",mv);};
    window.addEventListener("mousemove",mv);window.addEventListener("mouseup",up,{once:true});};
  return <div onMouseDown={down} onMouseEnter={()=>setHot(true)} onMouseLeave={()=>setHot(false)}
    style={{width:"3px",flexShrink:0,cursor:"col-resize",zIndex:20,
      background:"#444444",boxShadow:"none",cursor:"col-resize"}}/>;
});

/* ── Circuit Breaker Bar ───────────────────────────────────────────────────── */
const CBBar = memo(({risk,onNewSession}) => {
  const cb      = risk?.circuit_breaker;
  const streak  = risk?.streak;
  const sizing  = risk?.sizing;
  const sWR     = risk?.session_win_rate;
  const blocked = cb?.triggered;

  const [countdown,setCountdown] = useState("");
  useEffect(()=>{
    if(!blocked||!cb?.cooldown_minutes)return;
    const tick=()=>{
      const mins=cb.cooldown_minutes;
      const m=Math.floor(mins); const s=Math.round((mins-m)*60);
      setCountdown(`${String(m).padStart(2,"0")}:${String(s).padStart(2,"0")}`);
    };
    tick(); const id=setInterval(tick,1000); return ()=>clearInterval(id);
  },[blocked,cb]);

  if(!risk)return null;

  const last3 = streak?.last_3||[];
  const streakType = streak?.type==="W"?"W":streak?.type==="L"?"L":null;
  const streakCount= streak?.count||0;

  return (
    <div style={{display:"flex",alignItems:"center",gap:"10px",padding:"0 12px",
      height:"34px",flexShrink:0,
      background:blocked?"#1a0505":T.surface,
      borderBottom:`1px solid ${blocked?T.put:T.border}`,
      fontSize:"11px",fontFamily:"monospace"}}>

      {/* Status */}
      {blocked
        ? <><span style={{color:T.put,fontSize:"10px"}}>🛑</span>
            <span style={{fontWeight:900,color:T.put,letterSpacing:".05em"}}>BLOQUEADO</span>
            <div style={{background:T.put,color:"#000",fontWeight:900,padding:"1px 8px",fontSize:"10px"}}>
              Reanuda en {countdown}
            </div></>
        : <span style={{color:T.call,fontWeight:700}}>✅ OK</span>}

      <span style={{color:T.dim}}>|</span>

      {/* Streak */}
      <span style={{color:T.sub}}>Racha:</span>
      <span style={{fontWeight:900,
        color:streakType==="W"?T.call:streakType==="L"?T.put:T.muted}}>
        {streakType?`${streakCount}${streakType}`:"—"}
      </span>
      {last3.map((r,i)=>(
        <span key={i} style={{fontWeight:900,fontSize:"10px",padding:"0 4px",
          background:r==="W"?`${T.call}18`:`${T.put}18`,
          color:r==="W"?T.call:T.put,border:`1px solid ${r==="W"?T.call:T.put}44`}}>
          {r}
        </span>
      ))}

      <span style={{color:T.dim}}>|</span>

      {/* Bet */}
      {sizing && <>
        <span style={{color:T.sub}}>Apuesta:</span>
        <span style={{fontWeight:900,color:T.violet}}>${sizing.suggested_amount}</span>
        <span style={{color:T.muted,fontSize:"10px"}}>({sizing.risk_pct_effective}%)</span>
        <span style={{color:T.dim}}>|</span>
      </>}

      {/* Session WR */}
      {sWR!=null && <>
        <span style={{color:T.sub}}>Sesión WR:</span>
        <span style={{fontWeight:900,color:sWR>=55?T.call:sWR>=45?T.pre:T.put}}>{sWR}%</span>
      </>}

      <div style={{flex:1}}/>

      {/* New session button */}
      <button onClick={onNewSession} style={{background:"transparent",
        border:`1px solid ${T.dim}`,color:T.muted,padding:"1px 8px",
        fontSize:"10px",cursor:"pointer",fontFamily:"monospace",
        transition:"all .15s"}}
        onMouseEnter={e=>{e.target.style.borderColor=T.call;e.target.style.color=T.call;}}
        onMouseLeave={e=>{e.target.style.borderColor=T.dim;e.target.style.color=T.muted;}}>
        🔄 Nueva Sesión
      </button>
    </div>
  );
});

/* ── Header ────────────────────────────────────────────────────────────────── */
// SVG icons inline — no external dependency
const Ico = {
  chart:   <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>,
  gauge:   <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 2a10 10 0 0 1 7.38 16.75"/><path d="M12 2a10 10 0 0 0-7.38 16.75"/><line x1="12" y1="12" x2="15.2" y2="8.8"/><circle cx="12" cy="12" r="1.5"/></svg>,
  refresh: <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>,
  bolt:    <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>,
  arrowU:  <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><polygon points="12 4 20 20 4 20"/></svg>,
  arrowD:  <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><polygon points="12 20 4 4 20 4"/></svg>,
  wave:    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><path d="M2 12 C5 6, 8 18, 12 12 C16 6, 19 18, 22 12"/></svg>,
  bell:    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>,
};

const HdrBtn = ({icon, label, onClick, accent}) => (
  <button onClick={onClick} style={{
    display:"flex",alignItems:"center",gap:"5px",
    background:"transparent",
    color: accent||T.muted,
    border:`1px solid ${accent?`${accent}55`:T.border}`,
    padding:"2px 9px",fontSize:"10px",
    fontWeight:700,fontFamily:"monospace",cursor:"pointer",letterSpacing:".05em",
    transition:"all .15s",height:"22px",
  }}
  onMouseEnter={e=>{e.currentTarget.style.color=accent||T.text;e.currentTarget.style.borderColor=accent||"#555";}}
  onMouseLeave={e=>{e.currentTarget.style.color=accent||T.muted;e.currentTarget.style.borderColor=accent?`${accent}55`:T.border;}}
  >
    {icon}
    <span>{label}</span>
  </button>
);

const Header = memo(({session,utc5,latMs,latAlert,onScan,scanning,onNav,onRefresh}) => (
  <header style={{display:"flex",alignItems:"center",gap:"8px",padding:"0 12px",
    height:"36px",flexShrink:0,borderBottom:`1px solid ${T.border}`,background:T.surface,
    outline:latAlert?`1px solid ${T.violet}55`:"none"}}>

    <span style={{fontSize:"15px",fontWeight:900,color:T.call,
      fontFamily:"'IBM Plex Mono',monospace",letterSpacing:"-0.06em"}}>⬡ RADAR</span>
    <span style={{fontSize:"9px",color:T.dim,fontFamily:"monospace"}}>v2.9</span>

    {session&&<div style={{fontSize:"9px",fontWeight:700,color:T.call,
      background:"#001a0d",padding:"1px 7px",border:`1px solid ${T.call}33`,
      fontFamily:"monospace",letterSpacing:".06em"}}>{session}</div>}

    <span style={{fontSize:"10px",color:T.muted,fontFamily:"monospace"}}>· UTC-5 {utc5}</span>

    {latAlert&&<span style={{fontSize:"10px",color:T.violet,fontFamily:"monospace",
      animation:"blink .6s step-end infinite"}}>⚠ {latMs}ms</span>}

    <div style={{flex:1}}/>

    <HdrBtn icon={Ico.chart}   label="Backtesting" onClick={()=>onNav("/backtesting")}/>
    <HdrBtn icon={Ico.gauge}   label="Rendimiento"  onClick={()=>onNav("/performance")}/>
    <HdrBtn icon={Ico.refresh} label="Actualizar"   onClick={onRefresh}/>

    {/* ESCANEAR — accent verde */}
    <button onClick={onScan} disabled={scanning} style={{
      display:"flex",alignItems:"center",gap:"5px",
      background:scanning?`${T.call}18`:`${T.call}0d`,
      color:T.call,border:`1px solid ${T.call}`,
      padding:"2px 11px",fontSize:"10px",fontWeight:900,
      cursor:"pointer",fontFamily:"monospace",letterSpacing:".08em",height:"22px",
    }}>
      {Ico.bolt}
      <span>{scanning?"ESCANEANDO…":"ESCANEAR"}</span>
    </button>
  </header>
));

/* ── KPI Strip ─────────────────────────────────────────────────────────────── */
const KPIStrip = memo(({signals,preAlerts}) => {
  const calls  = signals.filter(s=>s.signal_type==="CALL").length;
  const puts   = signals.filter(s=>s.signal_type==="PUT").length;
  const fires  = signals.filter(s=>(s.quality_score||0)>=.8).length;
  const alerts = Object.keys(preAlerts).length;

  const kpis = [
    { l:"CALL",      v:calls,  c:T.call, ico:Ico.arrowU },
    { l:"PUT",       v:puts,   c:T.put,  ico:Ico.arrowD },
    { l:"SEÑALES",   v:fires,  c:T.fire, ico:Ico.wave   },
    { l:"ALERTANDO", v:alerts, c:T.pre,  ico:Ico.bell   },
  ];

  return (
    <div style={{display:"flex",gap:"1px",flexShrink:0,height:"46px",
      borderBottom:`1px solid ${T.border}`}}>
      {kpis.map(k=>(
        <div key={k.l} style={{flex:1,display:"flex",alignItems:"center",gap:"10px",
          padding:"0 16px",
          background:k.v>0?`${k.c}12`:"#0a0a0a",
          borderRight:`1px solid #1e1e1e`,transition:"background .3s"}}>

          {/* Icon */}
          <span style={{color:k.c,opacity:k.v>0?0.9:0.25,flexShrink:0,
            filter:k.v>0?`drop-shadow(0 0 4px ${k.c})`:"none",
            display:"flex",alignItems:"center"}}>
            {k.ico}
          </span>

          {/* Number */}
          <span style={{fontSize:"26px",fontWeight:800,
            fontFamily:"'IBM Plex Mono',monospace",color:k.c,lineHeight:1,
            textShadow:k.v>0?`0 0 14px ${k.c}99`:"none"}}>
            {k.v}
          </span>

          {/* Label */}
          <span style={{fontSize:"9px",fontWeight:800,color:k.c,
            letterSpacing:".14em",fontFamily:"monospace",
            opacity:k.v>0?0.9:0.3,lineHeight:1}}>
            {k.l}
          </span>
        </div>
      ))}
    </div>
  );
});

/* ── Log Feed ──────────────────────────────────────────────────────────────── */
const LogFeed = memo(({logs}) => {
  const end=useRef(null);
  useEffect(()=>{end.current?.scrollIntoView({behavior:"smooth"});},[logs]);
  return (
    <div style={{display:"flex",flexDirection:"column",height:"100%",background:T.surface}}>
      <div style={{padding:"3px 8px",fontSize:"9px",color:T.muted,letterSpacing:".14em",
        borderBottom:`1px solid ${T.border}`,flexShrink:0,fontFamily:"monospace"}}>
        ◈ SISTEMA · LOG
      </div>
      <div style={{flex:1,overflowY:"auto",scrollbarWidth:"none",padding:"2px 0"}}>
        {logs.map((l,i)=>(
          <div key={i} style={{padding:"1.5px 8px",fontSize:"10.5px",fontFamily:"'IBM Plex Mono',monospace",
            color:l.c||T.muted,opacity:.2+(i/Math.max(logs.length-1,1))*.8,
            whiteSpace:"nowrap",overflow:"hidden",textOverflow:"ellipsis",lineHeight:1.4}}>
            <span style={{color:T.dim,marginRight:"5px"}}>{l.t}</span>{l.m}
          </div>
        ))}
        <div ref={end}/>
      </div>
    </div>
  );
});

/* ── Active Timer Panel (left pane) ────────────────────────────────────────── */
const TimerPanel = memo(({signals,risk}) => {
  const topSig = signals.reduce((b,s)=>!b||s.quality_score>b.quality_score?s:b,null);
  const [secs,setSecs] = useState(0);
  useEffect(()=>{
    if(!topSig)return;
    const tick=()=>setSecs(getSecondsLeft(topSig.signal_timestamp||topSig.created_at));
    tick(); const id=setInterval(tick,500); return ()=>clearInterval(id);
  },[topSig]);

  const cb       = risk?.circuit_breaker;
  const blocked  = cb?.triggered;
  const sizing   = risk?.sizing;

  return (
    <div style={{display:"flex",flexDirection:"column",height:"100%",background:T.surface}}>
      {/* Active signal timer */}
      {topSig ? (
        <div style={{padding:"12px 10px",borderBottom:`1px solid ${T.border}`,
          background:`${sc(topSig.signal_type)}07`}}>
          <div style={{fontSize:"9px",color:T.muted,fontFamily:"monospace",
            letterSpacing:".12em",marginBottom:"4px"}}>
            {topSig.signal_type} ACTIVO
          </div>
          {/* Big countdown */}
          <div style={{fontSize:"44px",fontWeight:900,fontFamily:"'IBM Plex Mono',monospace",
            color:secs<=5?T.put:secs<=15?T.pre:sc(topSig.signal_type),
            lineHeight:1,letterSpacing:"-0.04em",textAlign:"center",
            animation:secs<=5?"blink .5s step-end infinite":"none"}}>
            {formatTime(secs)}
          </div>
          {/* Asset name */}
          <div style={{marginTop:"4px",textAlign:"center"}}>
            <RText text={(topSig.asset_name||topSig.symbol||"").replace("OTC_","").replace(/_/g,"/")+
              (topSig.symbol?.includes("OTC")?" OTC":"")}
              max={16} min={9} w={900}
              color={sc(topSig.signal_type)}/>
          </div>
          {/* Details */}
          <div style={{display:"flex",justifyContent:"space-around",marginTop:"6px"}}>
            {[
              ["Conf",`${((topSig.quality_score||0)*100).toFixed(0)}%`],
              ["Exp","2 MIN"],
              ["CCI",topSig.cci?.toFixed(0)||"—"],
            ].map(([k,v])=>(
              <div key={k} style={{textAlign:"center"}}>
                <div style={{fontSize:"8px",color:T.muted,fontFamily:"monospace"}}>{k}</div>
                <div style={{fontSize:"11px",fontWeight:700,fontFamily:"monospace",color:T.text}}>{v}</div>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div style={{padding:"14px 10px",borderBottom:`1px solid ${T.border}`,
          textAlign:"center"}}>
          <div style={{fontSize:"9px",color:T.dim,fontFamily:"monospace",letterSpacing:".12em"}}>
            SIN SEÑAL ACTIVA
          </div>
          <div style={{fontSize:"28px",fontWeight:900,fontFamily:"'IBM Plex Mono',monospace",
            color:T.dim,marginTop:"4px"}}>—:——</div>
        </div>
      )}

      {/* Risk sizing */}
      {sizing && (
        <div style={{padding:"8px 10px",borderBottom:`1px solid ${T.border}`}}>
          <div style={{fontSize:"9px",color:T.muted,fontFamily:"monospace",
            letterSpacing:".1em",marginBottom:"3px"}}>APUESTA SUGERIDA</div>
          <div style={{fontSize:"20px",fontWeight:900,fontFamily:"'IBM Plex Mono',monospace",
            color:T.violet}}>${sizing.suggested_amount}</div>
          <div style={{fontSize:"9px",color:T.sub,fontFamily:"monospace"}}>
            {sizing.risk_pct_effective}% · {sizing.multiplier_reason}</div>
        </div>
      )}

      {/* CB blocked warning */}
      {blocked && (
        <div style={{padding:"8px 10px",background:"#1a0505",
          borderBottom:`1px solid ${T.put}`,margin:"0"}}>
          <div style={{fontSize:"10px",fontWeight:900,color:T.put,fontFamily:"monospace"}}>
            🛑 OPERACIÓN BLOQUEADA
          </div>
          <div style={{fontSize:"9px",color:"#cc4444",fontFamily:"monospace",marginTop:"2px",lineHeight:1.4}}>
            {cb.reason?.replace("🛑 ","")}</div>
        </div>
      )}

      {/* Logs */}
      <div style={{flex:1,overflow:"hidden"}}>
        <LogFeed logs={[]}/>
      </div>
    </div>
  );
});

/* ── Sparkline ─────────────────────────────────────────────────────────────── */
const Spark = memo(({data,color,h=28}) => {
  if(!data?.length||data.length<2)return <div style={{height:`${h}px`}}/>;
  const W=100,H=h;
  const lo=Math.min(...data),hi=Math.max(...data),rng=hi-lo||1;
  const pts=data.map((v,i)=>{
    const x=(i/(data.length-1))*W;
    const y=H-((v-lo)/rng)*(H-2)-1;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const gradId = `sg${color.replace(/[^a-zA-Z0-9]/g,"")}`;
  // Build closed path for fill: line + bottom-right + bottom-left
  const pathD = `M ${pts.split(" ")[0]} L ${pts.split(" ").slice(1).join(" L ")} L ${W},${H} L 0,${H} Z`;
  return (
    <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none" style={{display:"block"}}>
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%"   stopColor={color} stopOpacity="0.18"/>
          <stop offset="100%" stopColor={color} stopOpacity="0"/>
        </linearGradient>
      </defs>
      <path d={pathD} fill={`url(#${gradId})`}/>
      <polyline points={pts} fill="none" stroke={color}
        strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" opacity=".9"/>
    </svg>
  );
});

/* ── PairCard ───────────────────────────────────────────────────────────────── */
const PairCard = memo(({sym,data,sig,pre,hovTerm,setHovTerm,onSelect,selected,maeAlert}) => {
  const hasSig = !!sig;
  const hasPre = !!pre&&!hasSig;
  const chg    = data?.change_pct;
  const chgDir = chg!=null?(chg>=0?T.call:T.put):null;
  const ac     = hasSig?sc(sig.signal_type):hasPre?T.pre:chgDir||T.muted;

  const name   = sym.replace("OTC_","").replace(/_/g,"/")+" OTC";
  const ind    = data?.indicators||{};
  const prices = data?.prices||[];

  const tags=[
    {k:"RSI", v:ind.rsi    !=null?ind.rsi.toFixed(0)              :null},
    {k:"BB",  v:ind.bb_pct !=null?`${(ind.bb_pct*100).toFixed(0)}%`:null},
    {k:"CCI", v:ind.cci    !=null?ind.cci.toFixed(0)               :null},
    {k:"ATR", v:ind.atr_pct!=null?(ind.atr_pct*100).toFixed(3)     :null},
    {k:"MAE", v:ind.mae    !=null?ind.mae.toFixed(1)               :null},
  ];

  return (
    <div onClick={()=>onSelect(sig||null)}
      style={{background:hasSig?`${ac}0e`:selected?`${T.violet}0e`:"#0F0F0F",
        border:`1px solid ${hasSig?ac:selected?T.violet:chgDir?`${chgDir}44`:"#333333"}`,
        borderTop:`2px solid ${hasSig?ac:hasPre?T.pre:chgDir?`${chgDir}cc`:"#333333"}`,
        padding:"6px 7px 5px",display:"flex",flexDirection:"column",gap:"2px",
        minWidth:0,cursor:"pointer",
        animation:hasSig?"cardpulse 2.5s ease-in-out infinite":maeAlert?"maepanic 2s ease-in-out infinite":"none",
        transition:"border-color .25s"}}>

      {/* Top row: name + price */}
      <div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start",gap:"4px"}}>
        <div style={{minWidth:0,flex:1}}>
          <RText text={name} max={13} min={8} w={900} color={T.text}/>
        </div>
        <div style={{textAlign:"right",flexShrink:0}}>
          <div style={{fontSize:"12px",fontWeight:700,fontFamily:"monospace",color:T.text,lineHeight:1}}>
            {data?.price?fmt(data.price,5):"—"}
          </div>
          {chg!=null&&(
            <div style={{fontSize:"9px",fontFamily:"monospace",
              color:chg>=0?T.call:T.put,lineHeight:1}}>
              {chg>=0?"▲":"▼"}{Math.abs(chg).toFixed(3)}%
            </div>
          )}
        </div>
      </div>

      {/* Sparkline */}
      <Spark data={prices} color={ac} h={26}/>

      {/* Signal/prealert badge */}
      {hasSig&&(
        <div style={{background:`${ac}1a`,border:`1px solid ${ac}`,color:ac,
          fontSize:"9px",fontWeight:900,fontFamily:"monospace",
          padding:"1px 4px",textAlign:"center",letterSpacing:".1em"}}>
          {sig.signal_type} · {((sig.quality_score||0)*100).toFixed(0)}%
        </div>
      )}
      {hasPre&&(
        <div style={{background:`${T.pre}0e`,border:`1px solid ${T.pre}44`,color:T.pre,
          fontSize:"8.5px",fontFamily:"monospace",padding:"1px 4px",textAlign:"center",
          animation:"blinkslw 1.8s ease-in-out infinite"}}>
          ⏳ {pre.confluence_pct}%
        </div>
      )}

      {/* Indicator tags */}
      <div style={{display:"flex",gap:"2px",flexWrap:"wrap"}}>
        {tags.map(({k,v})=>{
          const hot=hovTerm===k;
          return <span key={k}
            onMouseEnter={e=>{e.stopPropagation();setHovTerm(k);}}
            onMouseLeave={()=>setHovTerm(null)}
            style={{fontSize:"8.5px",fontFamily:"monospace",padding:"0 3px",lineHeight:"14px",
              background:hot?`${T.violet}18`:"#0e0e0e",
              color:hot?T.violet:v?"#3a3a3a":T.dim,
              border:`1px solid ${hot?T.violet:T.border}`,cursor:"help",transition:"all .1s"}}>
            {k}{v!=null?` ${v}`:""}
          </span>;
        })}
      </div>
    </div>
  );
});

/* ── Glosario ───────────────────────────────────────────────────────────────── */
const GLOSS = {
  RSI: {full:"Relative Strength Index",def:"Oscilador 0–100. >70 sobrecompra, <30 sobreventa.",
    rows:[{l:">70 Sobrecompra",c:T.put},{l:"30–70 Neutral",c:T.muted},{l:"<30 Sobreventa",c:T.call}]},
  BB:  {full:"Bollinger Bands %B",def:"Posición del precio dentro del canal ±2σ.",
    rows:[{l:">80% Banda sup.",c:T.put},{l:"20–80% Centro",c:T.muted},{l:"<20% Banda inf.",c:T.call}]},
  CCI: {full:"Commodity Channel Index",def:"Desvío estadístico del precio vs su media.",
    rows:[{l:">100 → CALL",c:T.call},{l:"±100 Rango",c:T.muted},{l:"<-100 → PUT",c:T.put}]},
  ATR: {full:"Average True Range %",def:"Volatilidad real del mercado en las últimas velas.",
    rows:[{l:">1.8% Alta",c:T.fire},{l:"1–1.8% Normal",c:T.muted},{l:"<1% Plano",c:T.dim}]},
  MAE: {full:"Max Adverse Excursion",def:"Cuánto retrocede el precio antes de tocar el objetivo.",
    rows:[{l:"<3px Limpio",c:T.call},{l:"3–10px Moderado",c:T.pre},{l:">10px Riesgoso",c:T.put}]},
  EMA: {full:"Exponential Moving Average",def:"Tendencia suavizada. Precio encima = alcista.",
    rows:[{l:"Precio > EMA → CALL",c:T.call},{l:"Precio < EMA → PUT",c:T.put}]},
  MACD:{full:"MACD Convergence Divergence",def:"EMA12 − EMA26 + señal. Momentum del mercado.",
    rows:[{l:"MACD > Señal → CALL",c:T.call},{l:"MACD < Señal → PUT",c:T.put}]},
};

/* ── Right Panel: Glosario + Señal Activa + Aparato Crítico ────────────────── */
const RightPanel = memo(({hovTerm,topSig,selectedSig,stats,session,risk,onMaeAlert}) => {
  const dispSig = selectedSig||topSig;
  const wr  = stats?.win_rate     ?? null;
  const pf  = stats?.profit_factor?? null;
  const mae = stats?.mae_avg_pips ?? null;
  const lat = stats?.latency_avg_ms?? null;
  const ops = stats?.total_trades ?? 0;
  const w   = stats?.total_wins   ?? 0;
  const l   = stats?.total_losses ?? 0;
  const cb  = risk?.circuit_breaker;
  const blocked = cb?.triggered;

  // ── Semáforo oficial via getHealthColor() ────────────────────────────────
  const wrH   = getHealthColor(wr,  "win_rate");
  const pfH   = getHealthColor(pf,  "profit_factor");
  const maeH  = getHealthColor(mae, "mae");
  const latH  = getHealthColor(lat, "latency");
  const wrC   = wrH.color;
  const pfC   = pfH.color;
  const maeC  = maeH.color;
  const latC  = latH.color;

  // MAE en rojo → tarjetas parpadean levemente (señal de pánico)
  const maeAlert = maeH.status === "danger";
  useEffect(()=>{ if(onMaeAlert) onMaeAlert(maeAlert); },[maeAlert]);

  const g = hovTerm?GLOSS[hovTerm]:null;

  const Dx=({label,val,color,note,sub,icon,status})=>(
    <div style={{padding:"6px 10px",borderBottom:`1px solid ${T.border}`,
      background:status==="danger"?"#1a0505":status==="warning"?"#1a1500":"transparent",
      transition:"background .3s"}}>
      <div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start"}}>
        <div style={{flex:1,minWidth:0}}>
          <div style={{display:"flex",alignItems:"center",gap:"4px",marginBottom:"1px"}}>
            {icon&&<span style={{display:"flex",alignItems:"center",flexShrink:0}}>{icon}</span>}
            <div style={{fontSize:"9px",color:T.muted,fontFamily:"monospace",
              letterSpacing:".08em"}}>{label}</div>
          </div>
          {sub&&<div style={{fontSize:"9px",color,fontFamily:"monospace"}}>{sub}</div>}
        </div>
        <span style={{fontSize:"20px",fontWeight:900,fontFamily:"'IBM Plex Mono',monospace",
          color,lineHeight:1,textShadow:status==="danger"||status==="success"?`0 0 10px ${color}66`:"none"}}>
          {val??"—"}
        </span>
      </div>
      <div style={{fontSize:"9px",color:"#444",fontFamily:"monospace",lineHeight:1.35,marginTop:"2px"}}>{note}</div>
    </div>
  );

  return (
    <div style={{display:"flex",flexDirection:"column",height:"100%",overflow:"hidden"}}>

      {/* Glosario hover */}
      <div style={{padding:"7px 10px",borderBottom:`1px solid ${T.border}`,
        minHeight:"100px",background:g?"#040c06":T.surface,flexShrink:0,transition:"background .2s"}}>
        <div style={{fontSize:"9px",color:T.muted,fontFamily:"monospace",
          letterSpacing:".14em",marginBottom:"4px"}}>
          ◈ GLOSARIO{g?` · ${hovTerm}`:" · hover etiqueta"}
        </div>
        {g?(<>
          <div style={{fontSize:"11px",fontWeight:700,fontFamily:"monospace",color:T.violet,marginBottom:"3px"}}>{g.full}</div>
          <div style={{fontSize:"9.5px",color:"#555",fontFamily:"monospace",lineHeight:1.4,marginBottom:"4px"}}>{g.def}</div>
          {g.rows.map((r,i)=>(
            <div key={i} style={{fontSize:"9px",color:r.c,fontFamily:"monospace",
              display:"flex",alignItems:"center",gap:"4px",lineHeight:"15px"}}>
              <span style={{fontSize:"4px"}}>◆</span>{r.l}
            </div>
          ))}
        </>):(
          <div style={{fontSize:"9px",color:T.dim,fontFamily:"monospace",lineHeight:2}}>
            RSI · BB · CCI · ATR · MAE · EMA · MACD
          </div>
        )}
      </div>

      {/* Señal Activa panel */}
      {dispSig && (
        <div style={{padding:"8px 10px",borderBottom:`1px solid ${T.border}`,
          background:`${sc(dispSig.signal_type)}07`,flexShrink:0}}>
          <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:"3px"}}>
            <span style={{fontSize:"9px",color:T.muted,fontFamily:"monospace"}}>
              {selectedSig?"SEÑAL SELECCIONADA":"SEÑAL TOP"}
            </span>
            <span style={{fontSize:"12px",fontWeight:900,fontFamily:"monospace",
              color:sc(dispSig.signal_type),letterSpacing:".06em",
              background:`${sc(dispSig.signal_type)}22`,padding:"0 6px",
              border:`1px solid ${sc(dispSig.signal_type)}`}}>
              {dispSig.signal_type}
            </span>
          </div>
          <RText text={(dispSig.asset_name||dispSig.symbol||"")
            .replace("OTC_","").replace(/_/g,"/")+
            (dispSig.symbol?.includes("OTC")?" OTC":"")}
            max={16} min={9} w={900}/>
          <div style={{display:"flex",gap:"8px",marginTop:"4px",flexWrap:"wrap"}}>
            {[
              ["Payout",dispSig.payout_pct?`${dispSig.payout_pct}%`:null],
              ["CCI",dispSig.cci?.toFixed(0)],
              ["Score",`${((dispSig.quality_score||0)*100).toFixed(0)}%`],
              ["Exp","2 MIN"],
            ].map(([k,v])=>v?(
              <span key={k} style={{fontSize:"9px",fontFamily:"monospace"}}>
                <span style={{color:T.muted}}>{k} </span>
                <span style={{color:T.text,fontWeight:700}}>{v}</span>
              </span>
            ):null)}
          </div>
          {dispSig.reasons_text&&(
            <div style={{fontSize:"9px",color:T.sub,fontFamily:"monospace",
              marginTop:"4px",lineHeight:1.4}}>{dispSig.reasons_text}</div>
          )}
          {blocked&&(
            <div style={{marginTop:"5px",background:"#1a0505",
              border:`1px solid ${T.put}`,padding:"4px 6px"}}>
              <div style={{fontSize:"9px",fontWeight:900,color:T.put,fontFamily:"monospace"}}>
                🛑 OPERACIÓN BLOQUEADA
              </div>
              <div style={{fontSize:"8.5px",color:"#cc4444",fontFamily:"monospace",marginTop:"1px"}}>
                {cb.reason?.replace("🛑 ","")}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Aparato Crítico */}
      <div style={{fontSize:"9px",color:T.muted,fontFamily:"monospace",letterSpacing:".14em",
        padding:"3px 8px",borderBottom:`1px solid ${T.border}`,flexShrink:0,background:T.surface}}>
        ◈ APARATO CRÍTICO
      </div>

      <div style={{flex:1,overflowY:"auto",scrollbarWidth:"none"}}>
        <Dx label="EFECTIVIDAD DE SEÑALES"
            val={wr!=null?`${wr}%`:null} color={wrC} icon={wrH.icon} status={wrH.status}
            note="Win Rate. Umbral profesional: >60% verde · 50–60% precaución · <50% peligro."
            sub={wr!=null?(wrH.status==="success"?"✓ Operando sobre umbral":wrH.status==="warning"?"⚡ En zona de precaución":"✗ Por debajo del umbral mínimo"):null}/>
        <Dx label="SALUD DE CUENTA"
            val={pf!=null?pf.toFixed(2):null} color={pfC} icon={pfH.icon} status={pfH.status}
            note="Profit Factor. >1.20 verde · 1.05–1.20 precaución · <1.05 peligro."
            sub={pf!=null?(pfH.status==="success"?"✓ Sistema rentable":pfH.status==="warning"?"⚡ Margen estrecho":"✗ Sistema en pérdida"):null}/>
        <Dx label="RIESGO DE RETROCESO (MAE)"
            val={mae!=null?`${mae} pips`:null} color={maeC} icon={maeH.icon} status={maeH.status}
            note="Max Adverse Excursion. <10 pips verde · 10–20 precaución · >20 peligro."
            sub={mae!=null?(maeH.status==="success"?"✓ Retroceso controlado":maeH.status==="warning"?"⚡ Retroceso moderado":"✗ Alto retroceso — revisar SL"):null}/>
        <Dx label="CALIDAD DE CONEXIÓN"
            val={lat!=null?`${lat} ms`:null} color={latC} icon={latH.icon} status={latH.status}
            note="Latencia de señal. <100ms verde · 100–300ms precaución · >300ms peligro."
            sub={lat!=null?(latH.status==="success"?"✓ Conexión óptima":latH.status==="warning"?"⚡ Latencia aceptable":"✗ Alta latencia — no operar"):null}/>

        {/* Sesión */}
        <div style={{padding:"7px 10px",borderBottom:`1px solid ${T.border}`}}>
          <div style={{fontSize:"9px",color:T.muted,fontFamily:"monospace",
            letterSpacing:".08em",marginBottom:"5px"}}>SESIÓN</div>
          <div style={{display:"flex",justifyContent:"space-between"}}>
            {[{label:"Ops",val:ops,c:T.text},{label:"Wins",val:w,c:T.call},
              {label:"Loss",val:l,c:T.put},
              {label:"WR",val:wr!=null?`${wr}%`:"—",c:wrC}
            ].map(({label,val,c})=>(
              <div key={label} style={{textAlign:"center"}}>
                <div style={{fontSize:"16px",fontWeight:900,fontFamily:"'IBM Plex Mono',monospace",
                  color:c,lineHeight:1}}>{val}</div>
                <div style={{fontSize:"8px",color:T.muted,fontFamily:"monospace",marginTop:"2px"}}>{label}</div>
              </div>
            ))}
          </div>
        </div>

        {session&&<div style={{padding:"5px 10px",fontSize:"9px",color:T.dim,fontFamily:"monospace",lineHeight:1.4}}>{session}</div>}
      </div>
    </div>
  );
});

/* ── ALL PAIRS ──────────────────────────────────────────────────────────────── */
const ALL_PAIRS=[
  "OTC_EURUSD","OTC_GBPUSD","OTC_USDJPY","OTC_USDCHF",
  "OTC_AUDUSD","OTC_NZDUSD","OTC_USDCAD","OTC_EURJPY",
  "OTC_EURGBP","OTC_EURAUD","OTC_EURCAD","OTC_EURCHF",
  "OTC_GBPJPY","OTC_GBPAUD","OTC_GBPCAD","OTC_GBPCHF",
  "OTC_AUDJPY","OTC_AUDCAD","OTC_CADJPY","OTC_CHFJPY",
];

function initPanes(){
  try{return JSON.parse(localStorage.getItem(PANE_KEY))||{L:220,R:235};}
  catch{return{L:220,R:235};}
}

/* ── MAIN ───────────────────────────────────────────────────────────────────── */
export default function Dashboard() {
  const navigate = useNavigate();
  const [signals,   setSig]   = useState([]);
  const [preAlerts, setPre]   = useState({});
  const [mktData,   setMkt]   = useState({});
  const [stats,     setStats] = useState(null);
  const [risk,      setRisk]  = useState(null);
  const [logs,      setLogs]  = useState([]);
  const [scanning,  setScan]  = useState(false);
  const [session,   setSess]  = useState("");
  const [utc5,      setUtc5]  = useState("--:--:--");
  const [latMs,     setLatMs] = useState(0);
  const [latAlert,  setLatA]  = useState(false);
  const [tradeAct,  setAct]   = useState("IDLE");
  const [hovTerm,   setHov]   = useState(null);
  const [selSig,    setSelSig]= useState(null);
  const [panes,     setPanes] = useState(initPanes);
  const [maeAlert,  setMaeAlert] = useState(false);
  const wrapRef = useRef(null);
  const [balance,   setBalance] = useState(() => {
    try{return parseFloat(localStorage.getItem("radar_balance")||"1000");}catch{return 1000;}
  });
  const [sessStart, setSessStart] = useState(() =>
    localStorage.getItem("radar_sess_start")||""
  );

  const log = useCallback((m,c=T.muted)=>{
    const d=new Date();
    const t=`${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}:${String(d.getSeconds()).padStart(2,"0")}`;
    setLogs(p=>[...p.slice(-120),{m,c,t}]);
  },[]);

  /* UTC-5 clock */
  useEffect(()=>{
    const tick=()=>{
      const now=new Date();
      const ms5=now.getTime()+now.getTimezoneOffset()*60000-5*3600000;
      const d5=new Date(ms5);
      setUtc5(`${String(d5.getHours()).padStart(2,"0")}:${String(d5.getMinutes()).padStart(2,"0")}:${String(d5.getSeconds()).padStart(2,"0")}`);
    };
    tick(); const id=setInterval(tick,1000); return ()=>clearInterval(id);
  },[]);

  const fetchSig = useCallback(async()=>{
    const t0=Date.now();
    try{
      const r=await fetch(`${API}/api/signals/active`);
      const ms=Date.now()-t0; const data=await r.json();
      setLatMs(ms); setLatA(ms>3000);
      const live=(data.signals||[]).filter(s=>isSignalLive(s)).map(s=>({...s,signal_type:s.signal_type||s.type}));
      setSig(live); setSess(data.session?.name||data.session_name||"");
      if(live.length){
        const top=live.reduce((b,s)=>s.quality_score>(b?.quality_score||0)?s:b,null);
        setAct(top.signal_type);
        log(`✓ ${top.signal_type} ${top.asset_name||top.symbol} · ${((top.quality_score||0)*100).toFixed(0)}%`,sc(top.signal_type));
      }else setAct("IDLE");
    }catch{log("✗ Error señales",T.put);}
  },[log]);

  const fetchPre = useCallback(async()=>{
    try{const d=await fetch(`${API}/api/pre-alerts/active`).then(r=>r.json()); setPre(d.pre_alerts||{});}catch{}
  },[]);

  const fetchStats = useCallback(async()=>{
    try{const raw=await fetch(`${API}/api/trades/stats`).then(r=>r.json()); setStats(normalizeStats(raw));}catch{}
  },[]);

  const fetchRisk = useCallback(async()=>{
    try{
      const body={balance,risk_pct:5.0,session_start:sessStart};
      const headers = {"Content-Type":"application/json"};
      if (API_KEY) headers["X-API-Key"] = API_KEY;
      const d=await fetch(`${API}/api/risk/status`,{method:"POST",
        headers,body:JSON.stringify(body)}).then(r=>r.json());
      setRisk(d);
    }catch{}
  },[balance,sessStart]);

  const fetchMkt = useCallback(async()=>{
    const results=await Promise.allSettled(
      ALL_PAIRS.map(sym=>fetch(`${API}/api/market-data/${sym}`)
        .then(r=>r.json()).then(d=>[sym,d]))
    );
    const map={};
    results.forEach(r=>{
      if(r.status==="fulfilled"){
        const[k,v]=r.value;
        if(v)map[k]=normalizeMarketAsset(v);
      }
    });
    setMkt(map);
  },[]);

  const newSession = useCallback(async()=>{
    const now=new Date().toISOString();
    setSessStart(now); localStorage.setItem("radar_sess_start",now);
    try{
      const headers = {};
      if (API_KEY) headers["X-API-Key"] = API_KEY;
      await fetch(`${API}/api/risk/reset-circuit-breaker`,{method:"POST", headers});
    }catch{}
    log("🔄 Nueva sesión iniciada",T.call);
    fetchRisk();
  },[fetchRisk,log]);

  useEffect(()=>{
    log("🚀 RADAR v2.7 arriba",T.call);
    log("Ventanas: 09:30–12:00 · 00:00–02:00 UTC-5",T.muted);
    fetchSig(); fetchPre(); fetchStats(); fetchRisk(); fetchMkt();
    const i1=setInterval(fetchSig,   30000);
    const i2=setInterval(fetchPre,   20000);
    const i3=setInterval(fetchStats, 60000);
    const i4=setInterval(fetchRisk,  30000);
    const i5=setInterval(fetchMkt,   15000);
    return()=>[i1,i2,i3,i4,i5].forEach(clearInterval);
  },[]);

  const scan = useCallback(async()=>{
    setScan(true); log("▶ Escaneo manual…",T.call);
    try{
      const headers = {};
      if (API_KEY) headers["X-API-Key"] = API_KEY;
      await fetch(`${API}/api/scan`,{method:"POST", headers});
      await fetchSig(); log("✓ Scan completado",T.call);
    }catch{log("✗ Error scan",T.put);}
    setScan(false);
  },[fetchSig,log]);

  const refresh = useCallback(()=>{
    fetchSig(); fetchPre(); fetchStats(); fetchRisk(); fetchMkt();
    log("↺ Actualizado",T.call);
  },[fetchSig,fetchPre,fetchStats,fetchRisk,fetchMkt,log]);

  const sigMap  = useMemo(()=>Object.fromEntries(signals.map(s=>[s.symbol,s])),[signals]);
  const topSig  = useMemo(()=>signals.reduce((b,s)=>!b||s.quality_score>b.quality_score?s:b,null),[signals]);
  const pairs   = useMemo(()=>[...ALL_PAIRS].sort((a,b)=>{
    const aS=!!sigMap[a],bS=!!sigMap[b],aP=!!preAlerts[a],bP=!!preAlerts[b];
    if(aS&&!bS)return-1; if(!aS&&bS)return 1;
    if(aP&&!bP)return-1; if(!aP&&bP)return 1;
    return 0;
  }),[sigMap,preAlerts]);

  /* Splitter drag */
  const dragL=useCallback((x)=>{
    const r=wrapRef.current?.getBoundingClientRect(); if(!r)return;
    const w=Math.max(160,Math.min(300,x-r.left));
    setPanes(p=>{const n={...p,L:w};localStorage.setItem(PANE_KEY,JSON.stringify(n));return n;});
  },[]);
  const dragR=useCallback((x)=>{
    const r=wrapRef.current?.getBoundingClientRect(); if(!r)return;
    const w=Math.max(190,Math.min(320,r.right-x));
    setPanes(p=>{const n={...p,R:w};localStorage.setItem(PANE_KEY,JSON.stringify(n));return n;});
  },[]);

  return (
    <>
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

      <StatusBar active={tradeAct}/>

      <div style={{display:"flex",flexDirection:"column",height:"100vh",
        paddingTop:"4px",background:T.bg}}>

        <Header session={session} utc5={utc5} latMs={latMs} latAlert={latAlert}
          onScan={scan} scanning={scanning} onNav={navigate} onRefresh={refresh}/>

        <CBBar risk={risk} onNewSession={newSession}/>

        <KPIStrip signals={signals} preAlerts={preAlerts}/>

        {/* 3-column body */}
        <div ref={wrapRef} style={{display:"flex",flex:1,overflow:"hidden",minHeight:0}}>

          {/* LEFT — Timer + Logs */}
          <div style={{width:`${panes.L}px`,flexShrink:0,overflow:"hidden",
            borderRight:`1px solid ${T.border}`}}>
            <TimerPanel signals={signals} risk={risk}/>
          </div>

          <Splitter onDrag={dragL}/>

          {/* CENTER — Asset Grid */}
          <div style={{flex:1,minWidth:0,overflow:"auto",padding:"5px"}}>
            <div style={{display:"grid",
              gridTemplateColumns:"repeat(auto-fill,minmax(155px,1fr))",gap:"4px"}}>
              {pairs.map(sym=>(
                <PairCard key={sym} sym={sym} data={mktData[sym]}
                  sig={sigMap[sym]} pre={preAlerts[sym]}
                  hovTerm={hovTerm} setHovTerm={setHov}
                  onSelect={s=>{setSelSig(prev=>prev?.symbol===sym?null:s);}}
                  selected={selSig?.symbol===sym}
                  maeAlert={maeAlert}/>
              ))}
            </div>
          </div>

          <Splitter onDrag={dragR}/>

          {/* RIGHT — Glossary + Signal + Aparato Crítico */}
          <div style={{width:`${panes.R}px`,flexShrink:0,overflow:"hidden",
            borderLeft:`1px solid ${T.border}`,display:"flex",flexDirection:"column"}}>
            <RightPanel hovTerm={hovTerm} topSig={topSig} selectedSig={selSig}
              stats={stats} session={session} risk={risk}
              onMaeAlert={setMaeAlert}/>
          </div>

        </div>
      </div>

      <ActiveSignalBanner  signals={signals}/>
      <TradingClockOverlay signals={signals}/>
    </>
  );
}
