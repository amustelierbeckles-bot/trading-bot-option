/**
 * Primitives.jsx — Componentes UI pequeños y reutilizables
 *   StatusBar  — Barra 4px top indicadora de estado
 *   Splitter   — Divisor arrastrable entre paneles
 *   RText      — Texto responsivo auto-reducible
 */
import { memo, useRef, useState, useEffect } from "react";
import { T } from "../../utils/dashboardUtils";

// ── StatusBar ─────────────────────────────────────────────────────────────────
export const StatusBar = memo(({ active }) => {
  const color = active === "CALL" ? T.call : active === "PUT" ? T.put : T.idle;
  const live  = active !== "IDLE";
  return (
    <div style={{
      position: "fixed", top: 0, left: 0, right: 0, height: "4px", zIndex: 9999,
      background: live
        ? `linear-gradient(90deg,transparent,${color} 20%,${color} 80%,transparent)`
        : color,
      boxShadow:  live ? `0 0 14px ${color}88` : "none",
      animation:  live ? "pulsebar 1.4s ease-in-out infinite" : "none",
      transition: "background .4s",
    }}/>
  );
});

// ── Splitter ──────────────────────────────────────────────────────────────────
export const Splitter = memo(({ onDrag }) => {
  const live = useRef(false);

  const down = (e) => {
    e.preventDefault();
    live.current = true;
    const mv = (ev) => { if (live.current) onDrag(ev.clientX); };
    const up  = ()  => { live.current = false; window.removeEventListener("mousemove", mv); };
    window.addEventListener("mousemove", mv);
    window.addEventListener("mouseup", up, { once: true });
  };

  return (
    <div
      onMouseDown={down}
      style={{ width: "3px", flexShrink: 0, cursor: "col-resize", zIndex: 20, background: "#444444" }}
    />
  );
});

// ── RText ─────────────────────────────────────────────────────────────────────
export const RText = memo(({ text, max = 22, min = 8, w = 900, color }) => {
  const _color = color || T.text;
  const el     = useRef(null);
  const [fs, setFs] = useState(max);

  useEffect(() => {
    const node = el.current; if (!node) return;
    let s = max; node.style.fontSize = `${s}px`;
    while (node.scrollWidth > node.clientWidth + 1 && s > min) {
      s -= 0.5; node.style.fontSize = `${s}px`;
    }
    setFs(s);
  }, [text, max, min]);

  return (
    <span ref={el} style={{
      fontSize: `${fs}px`, fontWeight: w, display: "block",
      whiteSpace: "nowrap", overflow: "hidden", lineHeight: 1.05,
      letterSpacing: "-0.02em", color: _color,
      fontFamily: "'IBM Plex Mono',monospace",
    }}>
      {text}
    </span>
  );
});
