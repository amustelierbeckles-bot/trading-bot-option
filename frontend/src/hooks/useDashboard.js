/**
 * useDashboard.js — Hook principal del RADAR v2.9
 * Centraliza todo el estado, fetches e intervalos del Dashboard
 */
import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { isSignalLive } from "../utils/signalTime";
import {
  API, API_KEY, T, sc, ALL_PAIRS, PANE_KEY,
  initPanes, normalizeStats, normalizeMarketAsset,
} from "../utils/dashboardUtils";
import { onWLUpdate } from "../utils/wlHistory";

export default function useDashboard() {
  // ── Estado ────────────────────────────────────────────────────────────────
  const [signals,   setSig]      = useState([]);
  const [preAlerts, setPre]      = useState({});
  const [mktData,   setMkt]      = useState({});
  const [stats,     setStats]    = useState(null);
  const [risk,      setRisk]     = useState(null);
  const [logs,      setLogs]     = useState([]);
  const [scanning,  setScan]     = useState(false);
  const [session,   setSess]     = useState("");
  const [utc5,      setUtc5]     = useState("--:--:--");
  const [latMs,     setLatMs]    = useState(0);
  const [latAlert,  setLatA]     = useState(false);
  const [tradeAct,  setAct]      = useState("IDLE");
  const [hovTerm,   setHov]      = useState(null);
  const [selSig,    setSelSig]   = useState(null);
  const [panes,     setPanes]    = useState(initPanes);
  const [maeAlert,  setMaeAlert] = useState(false);
  const wrapRef = useRef(null);

  const [balance, setBalance] = useState(() => {
    try { return parseFloat(localStorage.getItem("radar_balance") || "1000"); }
    catch { return 1000; }
  });
  const [sessStart, setSessStart] = useState(() =>
    localStorage.getItem("radar_sess_start") || ""
  );
  // Incrementa cada vez que se registra un W/L → fuerza re-render de PairCards
  const [wlVersion, setWlVersion] = useState(0);

  // ── Logger ────────────────────────────────────────────────────────────────
  const log = useCallback((m, c = T.muted) => {
    const d = new Date();
    const t = `${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}:${String(d.getSeconds()).padStart(2,"0")}`;
    setLogs(p => [...p.slice(-120), { m, c, t }]);
  }, []);

  // ── Reloj local (timezone-aware — ajuste automático DST) ─────────────────
  useEffect(() => {
    const tick = () => {
      const now = new Date();
      // Usa la API Intl para obtener la hora local correcta con DST automático
      const timeStr = now.toLocaleTimeString("en-US", {
        timeZone: "America/Havana",
        hour12:   false,
        hour:     "2-digit",
        minute:   "2-digit",
        second:   "2-digit",
      });
      setUtc5(timeStr);
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  // ── Fetches ───────────────────────────────────────────────────────────────
  const lastSigIdRef = useRef(null);
  const fetchSig = useCallback(async () => {
    const t0 = Date.now();
    try {
      const r    = await fetch(`${API}/api/signals/active`);
      const ms   = Date.now() - t0;
      const data = await r.json();
      setLatMs(ms); setLatA(ms > 3000);
      const live = (data.signals || [])
        .filter(s => isSignalLive(s))
        .map(s => ({ ...s, signal_type: s.signal_type || s.type }));
      setSig(live);
      setSess(data.session?.name || data.session_name || "");
      if (live.length) {
        const top = live.reduce((b, s) => s.quality_score > (b?.quality_score || 0) ? s : b, null);
        setAct(top.signal_type);
        // Solo logea si la señal es nueva (distinto id)
        if (top.id !== lastSigIdRef.current) {
          lastSigIdRef.current = top.id;
          log(`✓ ${top.signal_type} ${top.asset_name || top.symbol} · ${((top.quality_score || 0) * 100).toFixed(0)}%`, sc(top.signal_type));
        }
      } else {
        setAct("IDLE");
      }
    } catch { log("✗ Señales de error", T.put); }
  }, [log]);

  const fetchPre = useCallback(async () => {
    try {
      const d = await fetch(`${API}/api/pre-alerts/active`).then(r => r.json());
      setPre(d.pre_alerts || {});
    } catch {}
  }, []);

  const fetchStats = useCallback(async () => {
    try {
      const raw = await fetch(`${API}/api/trades/stats`).then(r => r.json());
      setStats(normalizeStats(raw));
    } catch {}
  }, []);

  const fetchRisk = useCallback(async () => {
    try {
      const body    = { balance, risk_pct: 5.0, session_start: sessStart };
      const headers = { "Content-Type": "application/json" };
      if (API_KEY) headers["X-API-Key"] = API_KEY;
      const d = await fetch(`${API}/api/risk/status`, {
        method: "POST", headers, body: JSON.stringify(body),
      }).then(r => r.json());
      setRisk(d);
    } catch {}
  }, [balance, sessStart]);

  const fetchMkt = useCallback(async () => {
    const results = await Promise.allSettled(
      ALL_PAIRS.map(sym =>
        fetch(`${API}/api/market-data/${sym}`)
          .then(r => r.json())
          .then(d => [sym, d])
      )
    );
    const map = {};
    results.forEach(r => {
      if (r.status === "fulfilled") {
        const [k, v] = r.value;
        if (v) map[k] = normalizeMarketAsset(v);
      }
    });
    setMkt(map);
  }, []);

  // ── Nueva sesión ──────────────────────────────────────────────────────────
  const newSession = useCallback(async () => {
    const now = new Date().toISOString();
    setSessStart(now);
    localStorage.setItem("radar_sess_start", now);
    try {
      const headers = {};
      if (API_KEY) headers["X-API-Key"] = API_KEY;
      await fetch(`${API}/api/risk/reset-circuit-breaker`, { method: "POST", headers });
    } catch {}
    log("🔄 Nueva sesión iniciada", T.call);
    fetchRisk();
  }, [fetchRisk, log]);

  // ── Listener W/L para re-render de PairCards ─────────────────────────────
  useEffect(() => {
    return onWLUpdate(() => setWlVersion(v => v + 1));
  }, []);

  // ── Montaje ───────────────────────────────────────────────────────────────
  useEffect(() => {
    log("🚀 RADAR v2.7 arriba", T.call);
    log("Ventanas: 09:30–12:00 · 00:00–02:00 UTC-5", T.muted);
    fetchSig(); fetchPre(); fetchStats(); fetchRisk(); fetchMkt();
    const i1 = setInterval(fetchSig,    5000);  // señales cada 5s (antes 30s)
    const i2 = setInterval(fetchPre,   10000);  // pre-alertas cada 10s
    const i3 = setInterval(fetchStats, 60000);
    const i4 = setInterval(fetchRisk,  30000);
    const i5 = setInterval(fetchMkt,   15000);
    return () => [i1, i2, i3, i4, i5].forEach(clearInterval);
  }, []); // eslint-disable-line

  // ── Acciones ──────────────────────────────────────────────────────────────
  const scan = useCallback(async () => {
    setScan(true);
    log("▶ Escaneo manual…", T.call);
    try {
      const headers = {};
      if (API_KEY) headers["X-API-Key"] = API_KEY;
      await fetch(`${API}/api/scan`, { method: "POST", headers });
      await fetchSig();
      log("✓ Scan completado", T.call);
    } catch { log("✗ Error scan", T.put); }
    setScan(false);
  }, [fetchSig, log]);

  const refresh = useCallback(() => {
    fetchSig(); fetchPre(); fetchStats(); fetchRisk(); fetchMkt();
    log("↺ Actualizado", T.call);
  }, [fetchSig, fetchPre, fetchStats, fetchRisk, fetchMkt, log]);

  // ── Memos ─────────────────────────────────────────────────────────────────
  const sigMap = useMemo(() =>
    Object.fromEntries(signals.map(s => [s.symbol, s])), [signals]);

  const topSig = useMemo(() =>
    signals.reduce((b, s) => !b || s.quality_score > b.quality_score ? s : b, null), [signals]);

  const pairs = useMemo(() =>
    [...ALL_PAIRS].sort((a, b) => {
      const aS = !!sigMap[a], bS = !!sigMap[b];
      const aP = !!preAlerts[a], bP = !!preAlerts[b];
      if (aS && !bS) return -1; if (!aS && bS) return 1;
      if (aP && !bP) return -1; if (!aP && bP) return 1;
      return 0;
    }), [sigMap, preAlerts]);

  // ── Splitter drag ─────────────────────────────────────────────────────────
  const dragL = useCallback((x) => {
    const r = wrapRef.current?.getBoundingClientRect(); if (!r) return;
    const w = Math.max(160, Math.min(300, x - r.left));
    setPanes(p => { const n = { ...p, L: w }; localStorage.setItem(PANE_KEY, JSON.stringify(n)); return n; });
  }, []);

  const dragR = useCallback((x) => {
    const r = wrapRef.current?.getBoundingClientRect(); if (!r) return;
    const w = Math.max(190, Math.min(320, r.right - x));
    setPanes(p => { const n = { ...p, R: w }; localStorage.setItem(PANE_KEY, JSON.stringify(n)); return n; });
  }, []);

  return {
    // Estado
    signals, preAlerts, mktData, stats, risk, logs, scanning,
    session, utc5, latMs, latAlert, tradeAct, hovTerm, selSig,
    panes, maeAlert, wrapRef, balance, sessStart,
    wlVersion,  // ← versión del historial W/L para forzar re-render de PairCards
    // Setters
    setHov, setSelSig, setMaeAlert, setBalance,
    // Acciones
    scan, refresh, newSession, dragL, dragR,
    // Memos
    sigMap, topSig, pairs,
  };
}
