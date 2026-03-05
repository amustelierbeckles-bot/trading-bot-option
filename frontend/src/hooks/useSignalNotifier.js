/**
 * useSignalNotifier — Sistema de alertas con 4 niveles de prioridad
 *
 * FIRE       🔥  quality_score > 0.90 O confluencia ≥ 3 estrategias
 * VERY_STRONG 🚨  |CCI| > 140 Y confluencia ≥ 3
 * HIGH        ⚡  |CCI| > 140 O confluencia ≥ 3
 * NORMAL      📈/📉 resto
 *
 * Cada nivel usa Web Audio API con sonido diferente.
 */
import { useEffect, useRef } from "react";
import { toast } from "sonner";

// ─────────────────────────────────────────────────────────────────────────────
// CLASIFICACIÓN DE PRIORIDAD
// ─────────────────────────────────────────────────────────────────────────────
export function getSignalPriority(signal) {
  const cci        = Math.abs(signal.cci ?? 0);
  const strategies = signal.strategies_agreeing?.length ?? 0;
  const score      = signal.quality_score ?? signal.market_quality / 100 ?? 0;

  if (score > 0.90 || strategies >= 3) return "fire";
  if (cci > 140 && strategies >= 3)    return "very_strong";
  if (cci > 140 || strategies >= 2)    return "high";
  return "normal";
}

export function isFireSignal(signal) {
  return getSignalPriority(signal) === "fire";
}

// ─────────────────────────────────────────────────────────────────────────────
// MOTOR DE AUDIO — Web Audio API (sin archivos externos)
// ─────────────────────────────────────────────────────────────────────────────

/** Crea un contexto de audio seguro */
function makeCtx() {
  return new (window.AudioContext || window.webkitAudioContext)();
}

/** Genera un beep individual con parámetros configurables */
function beep(ctx, freq, type, vol, t0, duration) {
  const osc  = ctx.createOscillator();
  const gain = ctx.createGain();
  osc.connect(gain);
  gain.connect(ctx.destination);
  osc.type            = type;
  osc.frequency.value = freq;
  const t1 = t0 + duration;
  gain.gain.setValueAtTime(vol, t0);
  gain.gain.exponentialRampToValueAtTime(0.001, t1);
  osc.start(t0);
  osc.stop(t1 + 0.01);
}

/**
 * 🔥 FIRE — 3 beeps ultra-rápidos en frecuencia muy alta + crescendo final
 * El más urgente de todos. Square wave 1760Hz para máxima presencia.
 */
function playFireSound(isCall) {
  try {
    const ctx   = makeCtx();
    const freq  = isCall ? 1760 : 1480;
    const freq2 = isCall ? 2093 : 1760;

    // 3 beeps dobles ultra-rápidos (urgencia máxima)
    for (let i = 0; i < 3; i++) {
      beep(ctx, freq,  "square", 0.45, ctx.currentTime + i * 0.09, 0.06);
      beep(ctx, freq2, "square", 0.35, ctx.currentTime + i * 0.09 + 0.04, 0.04);
    }

    // Acorde de resolución largo con shimmer
    const offset = 0.40;
    const chord  = isCall
      ? [659, 784, 1047, 1319, 1760]
      : [1760, 1319, 1047, 784, 659];
    chord.forEach((f, i) => {
      beep(ctx, f, "sine", 0.22, ctx.currentTime + offset + i * 0.06, 0.28);
    });

    setTimeout(() => ctx.close().catch(() => {}), 2000);
  } catch (e) { console.warn("Audio (fire):", e.message); }
}

/** 🚨 VERY_STRONG — 3 beeps dobles sawtooth + acorde 5 notas */
function playVeryStrongSound(isCall) {
  try {
    const ctx  = makeCtx();
    const base = isCall ? 1175 : 1047;
    for (let i = 0; i < 3; i++) {
      beep(ctx, base,       "sawtooth", 0.40, ctx.currentTime + i * 0.22, 0.07);
      beep(ctx, base * 1.5, "sawtooth", 0.30, ctx.currentTime + i * 0.22 + 0.08, 0.07);
    }
    const chord = isCall ? [523, 659, 784, 1047, 1319] : [1319, 1047, 784, 659, 523];
    chord.forEach((f, i) =>
      beep(ctx, f, "sine", 0.24, ctx.currentTime + 0.85 + i * 0.07, 0.30)
    );
    setTimeout(() => ctx.close().catch(() => {}), 2500);
  } catch (e) { console.warn("Audio (very_strong):", e.message); }
}

/** ⚡ HIGH — 3 beeps square + acorde 4 notas */
function playHighSound(isCall) {
  try {
    const ctx  = makeCtx();
    const freq = isCall ? 1047 : 880;
    for (let i = 0; i < 3; i++)
      beep(ctx, freq, "square", 0.35, ctx.currentTime + i * 0.14, 0.09);

    const notes = isCall ? [523, 659, 784, 1047] : [1047, 784, 659, 523];
    notes.forEach((f, i) =>
      beep(ctx, f, "sine", 0.26, ctx.currentTime + 0.55 + i * 0.09, 0.22)
    );
    setTimeout(() => ctx.close().catch(() => {}), 2000);
  } catch (e) { console.warn("Audio (high):", e.message); }
}

/** 📈 NORMAL — acorde Do-Mi-Sol suave */
function playNormalSound(isCall) {
  try {
    const ctx   = makeCtx();
    const notes = isCall ? [523, 659, 784] : [784, 659, 523];
    notes.forEach((f, i) =>
      beep(ctx, f, "sine", 0.22, ctx.currentTime + i * 0.12, 0.15)
    );
    setTimeout(() => ctx.close().catch(() => {}), 1000);
  } catch (e) { console.warn("Audio (normal):", e.message); }
}

function playSound(signal) {
  const isCall   = signal.type === "CALL" || signal.type === "BUY";
  const priority = getSignalPriority(signal);
  const map = { fire: playFireSound, very_strong: playVeryStrongSound, high: playHighSound, normal: playNormalSound };
  (map[priority] ?? playNormalSound)(isCall);
}

// ─────────────────────────────────────────────────────────────────────────────
// NOTIFICACIONES DEL SISTEMA
// ─────────────────────────────────────────────────────────────────────────────
async function requestNotificationPermission() {
  if (!("Notification" in window)) return false;
  if (Notification.permission === "granted") return true;
  if (Notification.permission === "denied")  return false;
  return (await Notification.requestPermission()) === "granted";
}

function sendSystemNotification(signal, priority) {
  if (!("Notification" in window) || Notification.permission !== "granted") return;
  const isCall = signal.type === "CALL" || signal.type === "BUY";
  const meta   = {
    fire:        { icon: "🔥", label: "¡FUEGO! SEÑAL ÉLITE",    persist: true  },
    very_strong: { icon: "🚨", label: "¡MUY FUERTE!",            persist: true  },
    high:        { icon: "⚡", label: "Alta probabilidad",        persist: false },
    normal:      { icon: isCall ? "📈" : "📉", label: "",        persist: false },
  };
  const m = meta[priority] ?? meta.normal;

  const n = new Notification(
    `${m.icon} ${signal.type}${m.label ? " · " + m.label : ""} — ${signal.asset_name}`,
    {
      body:              `Score: ${((signal.quality_score ?? 0) * 100).toFixed(0)}% · Payout ${(signal.payout || 85).toFixed(0)}% · ${signal.strategies_agreeing?.length ?? 0} estrategias`,
      icon:              "/favicon.ico",
      tag:               signal.id,
      requireInteraction: m.persist,
      silent:            true,
    }
  );
  if (!m.persist) setTimeout(() => n.close(), 8000);
}

// ─────────────────────────────────────────────────────────────────────────────
// HOOK PRINCIPAL
// ─────────────────────────────────────────────────────────────────────────────
const PRIORITY_RANK = { fire: 3, very_strong: 2, high: 1, normal: 0 };
const TOAST_DURATION = { fire: 12000, very_strong: 10000, high: 7000, normal: 5000 };
const FIRE_BADGE  = "🔥 FUEGO";
const TOAST_BADGE = { fire: FIRE_BADGE, very_strong: "🚨 MUY FUERTE", high: "⚡ Alta prob.", normal: "" };

export default function useSignalNotifier(signals = []) {
  const knownIds    = useRef(new Set());
  const initialized = useRef(false);

  useEffect(() => {
    if (!initialized.current) {
      initialized.current = true;
      requestNotificationPermission();
    }
  }, []);

  useEffect(() => {
    if (!signals?.length) return;

    const newSignals = signals.filter(s => s.active && s.id && !knownIds.current.has(s.id));
    if (!newSignals.length) return;

    newSignals.forEach(s => knownIds.current.add(s.id));

    // Señal de mayor prioridad para el sonido (setTimeout 0 = microtask antes de window.open)
    const top      = [...newSignals].sort((a, b) => PRIORITY_RANK[getSignalPriority(b)] - PRIORITY_RANK[getSignalPriority(a)])[0];
    const topPri   = getSignalPriority(top);
    const isCall   = top.type === "CALL" || top.type === "BUY";

    setTimeout(() => playSound(top), 0);
    newSignals.forEach(s => sendSystemNotification(s, getSignalPriority(s)));

    // Toast
    if (newSignals.length === 1) {
      const badge = TOAST_BADGE[topPri];
      toast.success(
        `${badge ? badge + ": " : (isCall ? "📈 " : "📉 ")}${top.asset_name} — ${top.type}`,
        {
          description: `Score ${((top.quality_score ?? 0) * 100).toFixed(0)}% · Payout ${(top.payout || 85).toFixed(0)}% · ${top.strategies_agreeing?.length ?? 0} estrategias`,
          duration:    TOAST_DURATION[topPri],
          // Fondo especial para FIRE
          style: topPri === "fire"
            ? { background: "rgba(255,80,0,0.15)", borderColor: "rgba(255,140,0,0.5)" }
            : undefined,
        }
      );
    } else {
      const fireCnt = newSignals.filter(s => getSignalPriority(s) === "fire").length;
      toast.success(
        `${fireCnt ? `🔥 ${fireCnt} FUEGO + ` : ""}🎯 ${newSignals.length} señales nuevas`,
        {
          description: newSignals.map(s => `${getSignalPriority(s) === "fire" ? "🔥 " : ""}${s.type} ${s.asset_name}`).join(" · "),
          duration:    fireCnt ? 12000 : 8000,
        }
      );
    }
  }, [signals]);
}


