"""
Email Service — Reportes diarios de trading via Resend
Arquitectura: Clean Service Layer, async-safe, no bloquea WebSocket ni Auto-scan
"""

import os
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional
import resend

logger = logging.getLogger(__name__)

TZ_LOCAL = ZoneInfo("America/Havana")


# ─────────────────────────────────────────────────────────────────────────────
# HTML TEMPLATE
# ─────────────────────────────────────────────────────────────────────────────

def _build_pair_rows(pairs: list[dict]) -> str:
    rows = ""
    for p in pairs:
        wr = p.get("win_rate", 0)
        wr_color = "#22c55e" if wr >= 60 else "#f59e0b" if wr >= 50 else "#ef4444"
        rows += f"""
        <tr style="border-bottom:1px solid #1e293b;">
          <td style="padding:10px 12px;font-weight:600;color:#e2e8f0;">{p['symbol']}</td>
          <td style="padding:10px 12px;text-align:center;">
            <span style="background:#1e293b;color:#94a3b8;padding:3px 8px;border-radius:4px;font-size:12px;">
              {p['total']} señales
            </span>
          </td>
          <td style="padding:10px 12px;text-align:center;">
            <span style="background:#14532d;color:#22c55e;padding:3px 8px;border-radius:4px;font-size:12px;">
              ✅ {p['itm']}
            </span>
          </td>
          <td style="padding:10px 12px;text-align:center;">
            <span style="background:#450a0a;color:#ef4444;padding:3px 8px;border-radius:4px;font-size:12px;">
              ❌ {p['otm']}
            </span>
          </td>
          <td style="padding:10px 12px;text-align:center;font-weight:700;color:{wr_color};">{wr:.1f}%</td>
          <td style="padding:10px 12px;text-align:center;color:#94a3b8;">{p.get('avg_score', 0):.0f}%</td>
        </tr>"""
    return rows


def _build_execution_mode_section(auto: dict, manual: dict) -> str:
    def badge(wr: float) -> str:
        color = "#22c55e" if wr >= 60 else "#f59e0b" if wr >= 50 else "#ef4444"
        return f'<span style="color:{color};font-size:22px;font-weight:800;">{wr:.1f}%</span>'

    return f"""
    <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:24px;">
      <tr>
        <td width="48%" style="background:#0f172a;border:1px solid #1e293b;border-radius:10px;padding:20px;text-align:center;">
          <div style="color:#64748b;font-size:11px;letter-spacing:1px;margin-bottom:8px;">🤖 AUTO-EXEC</div>
          {badge(auto.get('win_rate', 0))}
          <div style="color:#475569;font-size:12px;margin-top:6px;">{auto.get('itm',0)}W / {auto.get('otm',0)}L de {auto.get('total',0)}</div>
        </td>
        <td width="4%"></td>
        <td width="48%" style="background:#0f172a;border:1px solid #1e293b;border-radius:10px;padding:20px;text-align:center;">
          <div style="color:#64748b;font-size:11px;letter-spacing:1px;margin-bottom:8px;">👤 MANUAL</div>
          {badge(manual.get('win_rate', 0))}
          <div style="color:#475569;font-size:12px;margin-top:6px;">{manual.get('itm',0)}W / {manual.get('otm',0)}L de {manual.get('total',0)}</div>
        </td>
      </tr>
    </table>"""


def _build_html(data: dict) -> str:
    now_local = datetime.now(TZ_LOCAL).strftime("%d/%m/%Y %H:%M")
    cb_alert = ""
    if data.get("circuit_breaker_triggered"):
        cb_alert = """
        <div style="background:#450a0a;border:1px solid #ef4444;border-radius:8px;padding:14px;margin-bottom:20px;color:#fca5a5;">
          ⚠️ <strong>Circuit Breaker activado</strong> — Se detectaron 3+ pérdidas consecutivas.
          El bot pausó el escaneo automáticamente para proteger el capital.
        </div>"""

    coverage = data.get("coverage", {})
    pair_rows = _build_pair_rows(data.get("pairs", []))
    exec_section = _build_execution_mode_section(
        data.get("auto_exec", {}), data.get("manual_exec", {})
    )

    return f"""<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Reporte Trading Bot</title></head>
<body style="margin:0;padding:0;background:#020617;font-family:'Segoe UI',Arial,sans-serif;">
<div style="max-width:680px;margin:0 auto;padding:24px 16px;">

  <!-- HEADER -->
  <div style="text-align:center;padding:28px 0 20px;">
    <div style="font-size:28px;font-weight:800;color:#e2e8f0;letter-spacing:-1px;">
      📊 RADAR <span style="color:#3b82f6;">v3.9</span>
    </div>
    <div style="color:#475569;font-size:13px;margin-top:4px;">
      Reporte Diario · {now_local} UTC-4
    </div>
  </div>

  {cb_alert}

  <!-- KPI CARDS -->
  <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:24px;">
    <tr>
      <td width="23%" style="background:#0f172a;border:1px solid #1e293b;border-radius:10px;padding:16px;text-align:center;">
        <div style="color:#64748b;font-size:10px;letter-spacing:1px;margin-bottom:4px;">SEÑALES 24H</div>
        <div style="color:#e2e8f0;font-size:26px;font-weight:800;">{data.get('total_signals', 0)}</div>
      </td>
      <td width="2%"></td>
      <td width="23%" style="background:#0f172a;border:1px solid #1e293b;border-radius:10px;padding:16px;text-align:center;">
        <div style="color:#64748b;font-size:10px;letter-spacing:1px;margin-bottom:4px;">WIN RATE</div>
        <div style="color:#22c55e;font-size:26px;font-weight:800;">{data.get('global_win_rate', 0):.1f}%</div>
      </td>
      <td width="2%"></td>
      <td width="23%" style="background:#0f172a;border:1px solid #1e293b;border-radius:10px;padding:16px;text-align:center;">
        <div style="color:#64748b;font-size:10px;letter-spacing:1px;margin-bottom:4px;">SCORE PROM</div>
        <div style="color:#3b82f6;font-size:26px;font-weight:800;">{data.get('avg_quality_score', 0):.0f}%</div>
      </td>
      <td width="2%"></td>
      <td width="23%" style="background:#0f172a;border:1px solid #1e293b;border-radius:10px;padding:16px;text-align:center;">
        <div style="color:#64748b;font-size:10px;letter-spacing:1px;margin-bottom:4px;">VERIFICADAS</div>
        <div style="color:#a78bfa;font-size:26px;font-weight:800;">{coverage.get('high_pct', 0):.0f}%</div>
      </td>
    </tr>
  </table>

  <!-- COBERTURA DE AUDITORÍA -->
  <div style="background:#0f172a;border:1px solid #1e293b;border-radius:10px;padding:16px;margin-bottom:24px;">
    <div style="color:#94a3b8;font-size:11px;letter-spacing:1px;margin-bottom:12px;">COBERTURA DE AUDITORÍA</div>
    <table width="100%" cellpadding="0" cellspacing="0">
      <tr>
        <td style="color:#22c55e;font-size:13px;">✅ Alta confianza</td>
        <td style="text-align:right;color:#e2e8f0;font-weight:600;">{coverage.get('high', 0)} señales</td>
      </tr>
      <tr><td colspan="2" style="padding:3px 0;"></td></tr>
      <tr>
        <td style="color:#f59e0b;font-size:13px;">⚠️ Confianza media</td>
        <td style="text-align:right;color:#e2e8f0;font-weight:600;">{coverage.get('medium', 0)} señales</td>
      </tr>
      <tr><td colspan="2" style="padding:3px 0;"></td></tr>
      <tr>
        <td style="color:#64748b;font-size:13px;">❓ Sin datos de cierre</td>
        <td style="text-align:right;color:#64748b;font-weight:600;">{coverage.get('no_data', 0)} señales</td>
      </tr>
    </table>
  </div>

  <!-- AUTO vs MANUAL -->
  <div style="color:#94a3b8;font-size:11px;letter-spacing:1px;margin-bottom:12px;">AUTO-EXEC vs MANUAL</div>
  {exec_section}

  <!-- TABLA POR PAR -->
  <div style="background:#0f172a;border:1px solid #1e293b;border-radius:10px;overflow:hidden;margin-bottom:24px;">
    <div style="padding:14px 16px;border-bottom:1px solid #1e293b;">
      <span style="color:#94a3b8;font-size:11px;letter-spacing:1px;">RENDIMIENTO POR PAR (solo alta confianza)</span>
    </div>
    <table width="100%" cellpadding="0" cellspacing="0">
      <tr style="background:#1e293b;">
        <th style="padding:8px 12px;text-align:left;color:#64748b;font-size:11px;font-weight:600;">PAR</th>
        <th style="padding:8px 12px;text-align:center;color:#64748b;font-size:11px;font-weight:600;">TOTAL</th>
        <th style="padding:8px 12px;text-align:center;color:#64748b;font-size:11px;font-weight:600;">ITM</th>
        <th style="padding:8px 12px;text-align:center;color:#64748b;font-size:11px;font-weight:600;">OTM</th>
        <th style="padding:8px 12px;text-align:center;color:#64748b;font-size:11px;font-weight:600;">WIN %</th>
        <th style="padding:8px 12px;text-align:center;color:#64748b;font-size:11px;font-weight:600;">SCORE</th>
      </tr>
      {pair_rows if pair_rows else '<tr><td colspan="6" style="padding:20px;text-align:center;color:#475569;">Sin datos verificados en las últimas 24h</td></tr>'}
    </table>
  </div>

  <!-- FOOTER -->
  <div style="text-align:center;color:#334155;font-size:11px;padding-top:16px;border-top:1px solid #1e293b;">
    Trading Bot v3.9 · Generado automáticamente · No constituye asesoramiento financiero
  </div>
</div>
</body>
</html>"""


# ─────────────────────────────────────────────────────────────────────────────
# EMAIL SERVICE
# ─────────────────────────────────────────────────────────────────────────────

class EmailService:
    def __init__(self, db):
        self.db = db
        api_key = os.getenv("RESEND_API_KEY", "")
        if api_key and api_key != "your_resend_api_key_here":
            resend.api_key = api_key
            self._configured = True
        else:
            self._configured = False
            logger.warning("⚠️  RESEND_API_KEY no configurada — emails desactivados")

    # ── Agregación de señales ────────────────────────────────────────────────

    async def _aggregate_signals(self) -> dict:
        since = datetime.utcnow() - timedelta(hours=24)
        cursor = self.db.signals.find({"timestamp": {"$gte": since}})
        signals = await cursor.to_list(length=2000)

        total = len(signals)
        coverage = {"high": 0, "medium": 0, "no_data": 0}
        pairs: dict[str, dict] = {}
        auto_exec = {"total": 0, "itm": 0, "otm": 0}
        manual_exec = {"total": 0, "itm": 0, "otm": 0}
        scores = []
        cb_triggered = False
        consecutive_losses = 0
        max_consecutive = 0

        for sig in sorted(signals, key=lambda x: x.get("timestamp", datetime.min)):
            confidence = sig.get("audit_confidence", "no_data")
            result = sig.get("theoretical_result")  # 'win' | 'loss' | None
            score = sig.get("quality_score", 0)
            symbol = sig.get("symbol", "UNKNOWN")
            exec_mode = sig.get("execution_mode", "manual")

            if score:
                scores.append(score * 100 if score <= 1 else score)

            # Cobertura
            if confidence == "high":
                coverage["high"] += 1
            elif confidence == "medium":
                coverage["medium"] += 1
            else:
                coverage["no_data"] += 1

            # Solo contabilizar win/loss con alta confianza
            if confidence == "high" and result in ("win", "loss"):
                is_win = result == "win"

                # Por par
                if symbol not in pairs:
                    pairs[symbol] = {"symbol": symbol, "total": 0, "itm": 0, "otm": 0, "scores": []}
                pairs[symbol]["total"] += 1
                if is_win:
                    pairs[symbol]["itm"] += 1
                else:
                    pairs[symbol]["otm"] += 1
                if score:
                    pairs[symbol]["scores"].append(score * 100 if score <= 1 else score)

                # Por modo de ejecución
                bucket = auto_exec if exec_mode == "auto" else manual_exec
                bucket["total"] += 1
                if is_win:
                    bucket["itm"] += 1
                else:
                    bucket["otm"] += 1

                # Circuit breaker tracking
                if is_win:
                    consecutive_losses = 0
                else:
                    consecutive_losses += 1
                    max_consecutive = max(max_consecutive, consecutive_losses)

        if max_consecutive >= 3:
            cb_triggered = True

        # Win rates
        def wr(d: dict) -> float:
            return (d["itm"] / d["total"] * 100) if d["total"] > 0 else 0.0

        verified = coverage["high"]
        global_itm = sum(p["itm"] for p in pairs.values())
        global_wr = (global_itm / verified * 100) if verified > 0 else 0.0

        pairs_list = sorted(
            [
                {
                    **p,
                    "win_rate": (p["itm"] / p["total"] * 100) if p["total"] > 0 else 0,
                    "avg_score": (sum(p["scores"]) / len(p["scores"])) if p["scores"] else 0,
                }
                for p in pairs.values()
            ],
            key=lambda x: x["win_rate"],
            reverse=True,
        )

        coverage["high_pct"] = (coverage["high"] / total * 100) if total > 0 else 0

        auto_exec["win_rate"] = wr(auto_exec)
        manual_exec["win_rate"] = wr(manual_exec)

        return {
            "total_signals": total,
            "global_win_rate": global_wr,
            "avg_quality_score": sum(scores) / len(scores) if scores else 0,
            "coverage": coverage,
            "pairs": pairs_list,
            "auto_exec": auto_exec,
            "manual_exec": manual_exec,
            "circuit_breaker_triggered": cb_triggered,
        }

    # ── Envío ────────────────────────────────────────────────────────────────

    async def send_daily_report(self) -> bool:
        if not self._configured:
            logger.info("📧 Email desactivado — omitiendo reporte diario")
            return False
        try:
            data = await self._aggregate_signals()
            html = _build_html(data)
            recipient = os.getenv("REPORT_EMAIL", "amustelierbeckles@gmail.com")
            now_local = datetime.now(TZ_LOCAL).strftime("%d/%m/%Y")

            resend.Emails.send({
                "from": "Trading Bot <noreply@tradingbot.com>",
                "to": [recipient],
                "subject": f"📊 Reporte Diario — {now_local} | WR: {data['global_win_rate']:.1f}% | {data['total_signals']} señales",
                "html": html,
            })
            logger.info(
                "📧 Reporte diario enviado a %s | %d señales | WR %.1f%%",
                recipient, data["total_signals"], data["global_win_rate"],
            )
            return True
        except Exception as e:
            logger.error("❌ Error enviando reporte email: %s", e)
            return False

    async def send_test_email(self, recipient: Optional[str] = None) -> dict:
        if not self._configured:
            return {"success": False, "error": "RESEND_API_KEY no configurada"}
        try:
            target = recipient or os.getenv("REPORT_EMAIL", "amustelierbeckles@gmail.com")
            data = await self._aggregate_signals()
            html = _build_html(data)

            resend.Emails.send({
                "from": "Trading Bot <noreply@tradingbot.com>",
                "to": [target],
                "subject": f"🧪 [TEST] Reporte Trading Bot — {datetime.now(TZ_LOCAL).strftime('%d/%m/%Y %H:%M')}",
                "html": html,
            })
            return {"success": True, "recipient": target, "signals_included": data["total_signals"]}
        except Exception as e:
            logger.error("❌ Error en test email: %s", e)
            return {"success": False, "error": str(e)}
