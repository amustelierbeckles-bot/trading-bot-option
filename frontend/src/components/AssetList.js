/**
 * AssetList — Malla de activos monitoreados
 *
 * 3 fases por casilla:
 * 1. ALERTA  → borde naranja (🔥) o blanco (estándar) + color CALL/PUT
 * 2. ACCIÓN  → sparkline en vivo tras clic en "Abrir PO"
 * 3. EXPIRY  → "Validando..." → resultado → historial [W][L] persistente
 *
 * Tooltip hover: fila [W][L] sin color, último resaltado, Win Rate %
 * Historial: localStorage (persiste sesión del día)
 */
import { useState, useEffect, useRef } from "react";
import { TrendingUp, TrendingDown, Clock, Flame } from "lucide-react";
import { Badge } from "@/components/ui/badge";

const API = process.env.REACT_APP_BACKEND_URL + "/api";

// ─── Sparkline SVG ───────────────────────────────────────────────────────────
function Sparkline({ prices = [], color = "#00FF94", width = 72, height = 26 }) {
  if (prices.length < 2) return null;
  const min   = Math.min(...prices);
  const max   = Math.max(...prices);
  const range = max - min || Math.abs(min) * 0.001 || 0.0001;
  const pad   = 2;

  const pts = prices.map((p, i) => {
    const x = (i / (prices.length - 1)) * width;
    const y = pad + (height - pad * 2) - ((p - min) / range) * (height - pad * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");

  const lastY = pad + (height - pad * 2) -
    ((prices[prices.length - 1] - min) / range) * (height - pad * 2);

  return (
    <svg width={width} height={height} style={{ overflow: "visible", display: "block", flexShrink: 0 }}>
      <polyline points={`0,${height} ${pts} ${width},${height}`} fill={color + "18"} stroke="none" />
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.6"
        strokeLinejoin="round" strokeLinecap="round" opacity="0.9" />
      <circle cx={width} cy={lastY} r="2.5" fill={color} opacity="0.95" />
      <circle cx={width} cy={lastY} r="4"   fill={color} opacity="0.2"  />
    </svg>
  );
}

// ─── Historial inline [W][L] (sin colores, monocromático) ─────────────────────
function InlineHistory({ entries = [] }) {
  if (entries.length === 0) return null;
  const wins  = entries.filter(e => e.r === "W").length;
  const total = entries.length;
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 6,
      marginTop: 6, paddingTop: 5, borderTop: "1px solid rgba(255,255,255,0.06)",
    }}>
      <div style={{ display: "flex", gap: 2, flexWrap: "wrap" }}>
        {entries.slice(-10).map((e, i) => (
          <span key={i} style={{
            fontSize: 8, fontFamily: "monospace", fontWeight: 600,
            color: "rgba(255,255,255,0.45)",
            border: "1px solid rgba(255,255,255,0.12)",
            borderRadius: 2, padding: "0 2px",
            lineHeight: "14px",
          }}>
            {e.r}
          </span>
        ))}
      </div>
      <span style={{
        fontSize: 9, fontFamily: "monospace",
        color: "rgba(255,255,255,0.35)", whiteSpace: "nowrap",
      }}>
        {wins}/{total}
      </span>
    </div>
  );
}

// ─── Tooltip hover ────────────────────────────────────────────────────────────
function HistoryTooltip({ history }) {
  const entries = history?.entries ?? [];
  const winRate = history?.winRate ?? 0;

  if (entries.length === 0) return (
    <div style={{
      position: "absolute", bottom: "calc(100% + 8px)", left: "50%",
      transform: "translateX(-50%)", zIndex: 1000, pointerEvents: "none",
      background: "rgba(8,8,14,0.97)", border: "1px solid rgba(255,255,255,0.1)",
      borderRadius: 10, padding: "8px 12px",
      whiteSpace: "nowrap", fontSize: 11, color: "rgba(255,255,255,0.4)",
      fontFamily: "monospace", boxShadow: "0 4px 20px rgba(0,0,0,0.6)",
    }}>
      Sin operaciones hoy
    </div>
  );

  const last = entries[entries.length - 1];
  const wins = entries.filter(e => e.r === "W").length;
  return (
    <div style={{
      position: "absolute", bottom: "calc(100% + 8px)", left: "50%",
      transform: "translateX(-50%)", zIndex: 1000, pointerEvents: "none",
      background: "rgba(8,8,14,0.97)", border: "1px solid rgba(255,255,255,0.12)",
      borderRadius: 10, padding: "10px 14px", minWidth: 140,
      boxShadow: "0 4px 24px rgba(0,0,0,0.7)",
    }}>
      {/* Win Rate */}
      <div style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
        marginBottom: 8, paddingBottom: 6,
        borderBottom: "1px solid rgba(255,255,255,0.08)",
      }}>
        <span style={{ fontSize: 10, color: "rgba(255,255,255,0.5)", fontFamily: "monospace", letterSpacing: "0.1em" }}>
          WIN RATE
        </span>
        <span style={{
          fontSize: 14, fontWeight: 900, fontFamily: "monospace",
          color: "rgba(255,255,255,0.9)",
        }}>
          {winRate}%
        </span>
      </div>

      {/* [W] [L] sin colores — monocromático */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 3, justifyContent: "center" }}>
        {entries.map((e, i) => {
          const isLast = i === entries.length - 1;
          return (
            <span key={i} style={{
              display: "inline-flex", alignItems: "center", justifyContent: "center",
              width: isLast ? 20 : 16, height: isLast ? 20 : 16,
              fontSize: isLast ? 10 : 9,
              fontWeight: isLast ? 900 : 500,
              fontFamily: "monospace",
              color: "rgba(255,255,255,0.6)",
              border: isLast
                ? "2px solid rgba(255,255,255,0.5)"
                : "1px solid rgba(255,255,255,0.15)",
              borderRadius: 3,
              background: isLast ? "rgba(255,255,255,0.08)" : "transparent",
            }}>
              {e.r}
            </span>
          );
        })}
      </div>

      {/* Totales */}
      <div style={{
        display: "flex", justifyContent: "center", gap: 10,
        marginTop: 8, fontSize: 10, fontFamily: "monospace",
        color: "rgba(255,255,255,0.35)",
      }}>
        <span>{wins}W / {entries.length - wins}L</span>
      </div>
    </div>
  );
}

// ─── Tarjeta de activo ────────────────────────────────────────────────────────
function AssetCard({ asset, isSelected, onSelect, signal, preAlert, isValidating, history }) {
  const [hovered, setHovered]       = useState(false);
  const [priceTick, setPriceTick]   = useState(null);
  const [showSparkline, setSparkline] = useState(false);
  const tickRef    = useRef(null);
  const priceRef   = useRef(null);
  const prevSym    = useRef(asset.symbol);

  if (prevSym.current !== asset.symbol) {
    prevSym.current = asset.symbol;
    priceRef.current = null;
  }

  const isFire     = signal?.quality_score > 0.80 || (signal?.strategies_agreeing?.length >= 3);
  const isCall     = signal?.type === "CALL" || signal?.type === "BUY";
  const isPreAlert = !signal && !!preAlert;
  const preIsCall  = preAlert?.type === "CALL";

  // Colores por estado: señal completa, pre-alerta o neutro
  const dirColor   = signal
    ? (isCall ? "#00FF94" : "#FF0055")
    : isPreAlert
      ? (preIsCall ? "#FFB347" : "#FF8C69")  // naranja cálido para pre-alerta
      : null;
  const flashColor = isFire ? "#FF6B00" : signal ? "#ffffff" : isPreAlert ? "#FFB347" : null;

  const [flashOn, setFlashOn] = useState(true);
  useEffect(() => {
    if (!signal && !isPreAlert) { setFlashOn(true); return; }
    const interval = isFire ? 500 : isPreAlert ? 1200 : 800;
    const id = setInterval(() => setFlashOn(f => !f), interval);
    return () => clearInterval(id);
  }, [!!signal, isFire, isPreAlert]);

  // Sparkline polling
  const hasSignal = !!(signal || isSelected || isPreAlert);
  useEffect(() => {
    if (!hasSignal) { clearInterval(tickRef.current); setSparkline(false); return; }
    setSparkline(true);
    const base = asset.current_price || 1.0;
    if (!priceRef.current) {
      const syn = Array.from({ length: 12 }, (_, i) =>
        parseFloat((base + base * 0.0008 * (Math.random() - 0.5) * (i + 1)).toFixed(6))
      );
      priceRef.current = { price: base, prices: syn, change: asset.price_change_24h || 0 };
      setPriceTick(priceRef.current);
    }
    const fetchPrice = async () => {
      try {
        const r = await fetch(`${API}/market-data/${asset.symbol}`);
        if (!r.ok) return;
        const data = await r.json();
        if (!Array.isArray(data) || data.length < 2) return;
        const prices = data.slice(-14).map(c => parseFloat(c.close)).filter(p => p > 0);
        if (prices.length < 2) return;
        const last = prices[prices.length - 1], prev = prices[prices.length - 2];
        const tick = { price: last, prices, change: ((last - prev) / prev) * 100 };
        priceRef.current = tick;
        setPriceTick(tick);
      } catch (_) {}
    };
    fetchPrice();
    clearInterval(tickRef.current);
    tickRef.current = setInterval(fetchPrice, 10000);
    return () => clearInterval(tickRef.current);
  }, [hasSignal, asset.symbol, asset.current_price, asset.price_change_24h]);

  const price     = priceTick?.price ?? asset.current_price;
  const change    = priceTick?.change ?? asset.price_change_24h;
  const changeCol = change >= 0 ? "#00FF94" : "#FF0055";
  const sparkColor = signal ? dirColor : isPreAlert ? "#FFB347" : changeCol;
  const entries   = history?.entries ?? [];

  // Border: señal completa > pre-alerta > seleccionado > neutro
  const borderColor = signal
    ? (flashOn ? (flashColor + "bb") : (dirColor + "50"))
    : isPreAlert
      ? (flashOn ? "rgba(255,179,71,0.7)" : "rgba(255,179,71,0.25)")
      : isSelected ? "#6366f1" : "rgba(255,255,255,0.08)";

  const bgColor = signal
    ? `${dirColor}08`
    : isPreAlert
      ? "rgba(255,179,71,0.05)"
      : isSelected ? "rgba(99,102,241,0.12)" : "rgba(255,255,255,0.03)";

  const shadow = signal
    ? `0 0 ${flashOn && isFire ? 20 : 10}px ${isFire ? "rgba(255,107,0,0.3)" : dirColor + "25"}`
    : isPreAlert
      ? `0 0 ${flashOn ? 14 : 6}px rgba(255,179,71,0.2)`
      : "none";

  return (
    <div style={{ position: "relative" }}>
      <button
        onClick={() => onSelect(asset)}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        style={{
          width: "100%", textAlign: "left",
          padding: "9px 10px",           // compacto
          borderRadius: 8, cursor: "pointer", transition: "all 0.2s",
          background: bgColor, border: `1.5px solid ${borderColor}`, boxShadow: shadow,
        }}
      >
        {/* Header: nombre + badges */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 4 }}>
          <div style={{ minWidth: 0, flex: 1 }}>
            <div style={{
              fontSize: 11, fontWeight: 700, lineHeight: 1.2,
              color: signal ? dirColor : isPreAlert ? "#FFB347" : "rgba(255,255,255,0.9)",
              overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
            }}>
              {asset.name}
              {isFire && signal && <Flame style={{ display: "inline", width: 10, height: 10, marginLeft: 3, color: "#FF6B00" }} />}
            </div>
            <div style={{ fontSize: 9, color: "rgba(255,255,255,0.28)", fontFamily: "monospace", marginTop: 1 }}>
              {asset.symbol}
            </div>
          </div>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 2, flexShrink: 0 }}>
            {asset.symbol.startsWith("OTC_") && (
              <Badge variant="outline" style={{
                fontSize: 8, fontFamily: "monospace", padding: "0 4px",
                background: "rgba(0,255,148,0.06)", color: "#00FF94",
                border: "1px solid rgba(0,255,148,0.2)",
              }}>
                <Clock style={{ width: 8, height: 8, marginRight: 2 }} />OTC
              </Badge>
            )}
          </div>
        </div>

        {/* Badge: señal completa */}
        {signal && !isValidating && (
          <div style={{
            display: "flex", alignItems: "center", gap: 5,
            marginBottom: 4, padding: "2px 6px",
            background: `${dirColor}18`, borderRadius: 5, border: `1px solid ${dirColor}40`,
          }}>
            <div style={{
              width: 5, height: 5, borderRadius: "50%",
              background: isFire ? "#FF6B00" : dirColor,
              boxShadow: `0 0 5px ${isFire ? "#FF6B00" : dirColor}`,
              animation: "asset-pulse 1s infinite",
            }} />
            <span style={{
              fontSize: 9, fontWeight: 700, fontFamily: "monospace",
              color: dirColor, letterSpacing: "0.08em",
            }}>
              {isCall ? "▲ CALL" : "▼ PUT"}{isFire ? " 🔥" : ""}
            </span>
          </div>
        )}

        {/* Badge: PRE-ALERTA — estado de alineación */}
        {isPreAlert && !isValidating && (
          <div style={{
            display: "flex", alignItems: "center", gap: 5,
            marginBottom: 4, padding: "2px 6px",
            background: "rgba(255,179,71,0.1)", borderRadius: 5,
            border: "1px solid rgba(255,179,71,0.35)",
          }}>
            <div style={{
              width: 5, height: 5, borderRadius: "50%",
              background: "#FFB347",
              boxShadow: "0 0 5px #FFB347",
              animation: "asset-pulse 1.5s infinite",
            }} />
            <span style={{
              fontSize: 9, fontWeight: 700, fontFamily: "monospace",
              color: "#FFB347", letterSpacing: "0.08em",
            }}>
              ⏳ {preIsCall ? "▲" : "▼"} ALINEANDO {preAlert.confluence_pct}%
            </span>
          </div>
        )}

        {/* Validando */}
        {isValidating && (
          <div style={{
            fontSize: 9, fontFamily: "monospace", color: "#FACC15",
            background: "rgba(250,204,21,0.08)", border: "1px solid rgba(250,204,21,0.3)",
            borderRadius: 5, padding: "2px 6px", marginBottom: 4, letterSpacing: "0.08em",
          }}>
            ⏳ Validando...
          </div>
        )}

        {/* Precio + sparkline */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end" }}>
          <div>
            <div style={{ fontSize: 13, fontWeight: 700, fontFamily: "monospace", color: "rgba(255,255,255,0.9)", lineHeight: 1 }}>
              {typeof price === "number" ? price.toFixed(price > 10 ? 2 : 5) : "--"}
            </div>
            <div style={{
              fontSize: 9, fontFamily: "monospace", fontWeight: 500,
              color: changeCol, display: "flex", alignItems: "center", gap: 2, marginTop: 2,
            }}>
              {change >= 0 ? <TrendingUp style={{ width: 9, height: 9 }} /> : <TrendingDown style={{ width: 9, height: 9 }} />}
              {change >= 0 ? "+" : ""}{change?.toFixed(2)}%
            </div>
          </div>
          {showSparkline && priceTick?.prices && (
            <Sparkline prices={priceTick.prices} color={sparkColor} width={60} height={22} />
          )}
        </div>

        {/* Historial inline [W][L] */}
        <InlineHistory entries={entries} />
      </button>

      {/* Tooltip en hover */}
      {hovered && <HistoryTooltip history={history} />}
    </div>
  );
}

// ─── Componente principal ─────────────────────────────────────────────────────
export default function AssetList({
  assets = [],
  selectedAsset,
  onSelectAsset,
  activeSignals = {},
  preAlerts = {},
  validatingSymbol = null,
  tradeHistories = {},
}) {
  // Orden: señal completa > pre-alerta > validando > neutro
  const sorted = [...assets].sort((a, b) => {
    const score = sym => {
      if (activeSignals[sym])    return 3;
      if (preAlerts[sym])        return 2;
      if (validatingSymbol===sym) return 1;
      return 0;
    };
    return score(b.symbol) - score(a.symbol);
  });

  return (
    <>
      <style>{`
        @keyframes asset-pulse{0%,100%{opacity:1}50%{opacity:.4}}
      `}</style>
      {/* Grid responsivo de alta densidad: 2 cols mínimo, hasta 4 en pantallas anchas */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))",
          gap: 8,
        }}
        data-testid="asset-list-grid"
      >
        {sorted.map((asset) => (
          <AssetCard
            key={asset.id}
            asset={asset}
            isSelected={selectedAsset?.id === asset.id}
            onSelect={onSelectAsset}
            signal={activeSignals[asset.symbol] ?? null}
            preAlert={preAlerts[asset.symbol] ?? null}
            isValidating={validatingSymbol === asset.symbol}
            history={tradeHistories[asset.symbol]}
          />
        ))}
      </div>
    </>
  );
}
