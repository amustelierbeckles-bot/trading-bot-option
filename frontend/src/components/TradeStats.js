/**
 * TradeStats — Panel de estadísticas de operaciones
 *
 * Muestra: Win Rate global, Profit Factor, histórico por par,
 * por hora del día y por nivel de calidad del score.
 * Se actualiza con los datos del backend cada vez que se monta.
 */
import { useState, useEffect } from "react";
import { TrendingUp, TrendingDown, Trophy, Target, BarChart2, Clock, RefreshCw } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

function WinRateBadge({ rate }) {
  const color = rate >= 60 ? "text-buy border-buy/40 bg-buy/10"
              : rate >= 50 ? "text-yellow-400 border-yellow-400/40 bg-yellow-400/10"
              :              "text-sell border-sell/40 bg-sell/10";
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded font-mono font-bold text-xs border ${color}`}>
      {rate.toFixed(1)}%
    </span>
  );
}

function StatBlock({ label, value, sub, color = "text-foreground" }) {
  return (
    <div className="text-center">
      <p className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground mb-1">{label}</p>
      <p className={`text-3xl font-black font-heading ${color}`}>{value}</p>
      {sub && <p className="text-[10px] text-muted-foreground font-mono mt-0.5">{sub}</p>}
    </div>
  );
}

export default function TradeStats() {
  const [stats,    setStats]    = useState(null);
  const [loading,  setLoading]  = useState(true);
  const [section,  setSection]  = useState("pair"); // "pair" | "hour" | "score"

  const load = async () => {
    setLoading(true);
    try {
      const r = await fetch(`${API}/trades/stats?days=30`);
      setStats(await r.json());
    } catch { /* silencioso */ }
    finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  if (loading) return (
    <Card className="bg-card border-border">
      <CardContent className="py-10 text-center text-muted-foreground font-mono text-sm">
        Cargando estadísticas...
      </CardContent>
    </Card>
  );

  if (!stats || stats.total_trades === 0) return (
    <Card className="bg-card border-border">
      <CardHeader>
        <CardTitle className="text-lg font-heading">Rendimiento Real</CardTitle>
        <CardDescription className="font-mono text-xs">
          Registra tus operaciones con ✅/❌ en cada señal
        </CardDescription>
      </CardHeader>
      <CardContent className="py-8 text-center">
        <Trophy className="w-10 h-10 text-muted-foreground/30 mx-auto mb-3" />
        <p className="text-sm text-muted-foreground font-mono">Sin operaciones registradas aún</p>
        <p className="text-xs text-muted-foreground/60 font-mono mt-1">
          Abre una señal en PO → regresa → pulsa Gané o Perdí
        </p>
      </CardContent>
    </Card>
  );

  const pfColor  = stats.profit_factor >= 1.5 ? "text-buy"
                 : stats.profit_factor >= 1.0  ? "text-yellow-400"
                 :                               "text-sell";
  const wrColor  = stats.win_rate >= 60 ? "text-buy"
                 : stats.win_rate >= 50  ? "text-yellow-400"
                 :                         "text-sell";

  // Par con mejor win rate (mínimo 3 operaciones)
  const bestPair = Object.entries(stats.by_pair)
    .filter(([, v]) => v.total >= 3)
    .sort(([, a], [, b]) => b.win_rate - a.win_rate)[0];

  const tabs = [
    { key: "pair",  label: "Por par",   icon: BarChart2 },
    { key: "hour",  label: "Por hora",  icon: Clock     },
    { key: "score", label: "Por score", icon: Target    },
  ];

  return (
    <Card className="bg-card border-border">
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-lg font-heading">Rendimiento Real</CardTitle>
            <CardDescription className="font-mono text-xs">
              Últimos 30 días · {stats.total_trades} operaciones
            </CardDescription>
          </div>
          <button
            onClick={load}
            className="text-muted-foreground hover:text-foreground transition-colors"
            title="Actualizar"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </CardHeader>

      <CardContent className="space-y-5">

        {/* ── Métricas principales ─────────────────────────────────────── */}
        <div className="grid grid-cols-3 gap-4 py-3 border-y border-border">
          <StatBlock
            label="Win Rate"
            value={`${stats.win_rate}%`}
            sub={`${stats.total_wins}W / ${stats.total_losses}L`}
            color={wrColor}
          />
          <StatBlock
            label="Profit Factor"
            value={stats.profit_factor.toFixed(2)}
            sub={stats.profit_factor >= 1 ? "Rentable ✓" : "En pérdida"}
            color={pfColor}
          />
          <StatBlock
            label="Operaciones"
            value={stats.total_trades}
            sub={bestPair ? `Mejor: ${bestPair[1].asset_name?.replace(" OTC","")}` : "—"}
            color="text-primary"
          />
        </div>

        {/* ── Tabs de desglose ─────────────────────────────────────────── */}
        <div>
          <div className="flex gap-1 mb-3">
            {tabs.map(({ key, label, icon: Icon }) => (
              <button
                key={key}
                onClick={() => setSection(key)}
                className={`flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-mono transition-all
                  ${section === key
                    ? "bg-primary/10 text-primary border border-primary/30"
                    : "text-muted-foreground hover:text-foreground"}`}
              >
                <Icon className="w-3 h-3" />
                {label}
              </button>
            ))}
          </div>

          {/* Por par */}
          {section === "pair" && (
            <div className="space-y-2">
              {Object.entries(stats.by_pair)
                .sort(([, a], [, b]) => b.total - a.total)
                .map(([sym, v]) => (
                  <div key={sym} className="flex items-center justify-between py-1.5 border-b border-border/40 last:border-0">
                    <div className="flex items-center gap-2">
                      {v.win_rate >= 60
                        ? <TrendingUp className="w-3.5 h-3.5 text-buy" />
                        : <TrendingDown className="w-3.5 h-3.5 text-sell" />}
                      <span className="text-sm font-mono">{v.asset_name || sym}</span>
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="text-[11px] text-muted-foreground font-mono">
                        {v.wins}W / {v.total - v.wins}L
                      </span>
                      <WinRateBadge rate={v.win_rate} />
                    </div>
                  </div>
                ))}
            </div>
          )}

          {/* Por hora */}
          {section === "hour" && (
            <div className="space-y-2">
              {Object.entries(stats.by_hour)
                .sort(([a], [b]) => Number(a) - Number(b))
                .map(([h, v]) => (
                  <div key={h} className="flex items-center justify-between py-1.5 border-b border-border/40 last:border-0">
                    <span className="text-sm font-mono text-muted-foreground">
                      {h.padStart(2,"0")}:00 UTC
                    </span>
                    <div className="flex items-center gap-3">
                      <div className="w-24 bg-border rounded-full h-1.5 overflow-hidden">
                        <div
                          className="h-full rounded-full"
                          style={{
                            width: `${v.win_rate}%`,
                            background: v.win_rate >= 60 ? "#00FF94" : v.win_rate >= 50 ? "#FACC15" : "#FF0055",
                          }}
                        />
                      </div>
                      <WinRateBadge rate={v.win_rate} />
                    </div>
                  </div>
                ))}
            </div>
          )}

          {/* Por score */}
          {section === "score" && (
            <div className="space-y-2">
              {Object.entries(stats.by_score).map(([label, v]) => (
                <div key={label} className="flex items-center justify-between py-1.5 border-b border-border/40 last:border-0">
                  <div className="flex items-center gap-2">
                    <Badge variant="outline" className="font-mono text-[10px] text-primary border-primary/30">
                      Score {label}
                    </Badge>
                    <span className="text-xs text-muted-foreground font-mono">{v.total} ops</span>
                  </div>
                  <WinRateBadge rate={v.win_rate} />
                </div>
              ))}
              {Object.keys(stats.by_score).length === 0 && (
                <p className="text-xs text-muted-foreground font-mono text-center py-4">
                  Registra más operaciones para ver este análisis
                </p>
              )}
            </div>
          )}
        </div>

      </CardContent>
    </Card>
  );
}

