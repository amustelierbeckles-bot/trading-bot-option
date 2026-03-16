"""
Umbral dinámico de quality score.

El bot auto-calibra cada 10 ciclos de escaneo (~20 min).
Solo usa trades con audit_confidence='high' para evitar datos corruptos.
"""

_dynamic_min_quality: float = 0.55   # valor por defecto (sin calibración)
_MIN_TRADES_TO_CALIBRATE: int = 20   # mínimo de trades HIGH-CONFIDENCE para calibrar


def compute_optimal_threshold(trades: list) -> dict:
    """
    Analiza el Win Rate por bucket de quality score y encuentra
    el umbral mínimo donde WR >= MIN_WR_TARGET.

    Estrategia:
    - Divide los trades en 5 rangos: <55, 55-65, 65-75, 75-85, >85
    - Calcula WR real en cada rango
    - Recomienda el rango más bajo con WR >= 55%
    - Si ninguno supera el 55%, recomienda el de mejor WR

    Returns dict con análisis completo y umbral recomendado.
    """
    MIN_WR_TARGET = 55.0
    MIN_SAMPLE    = 5

    buckets = [
        ("< 0.55",    0.00, 0.55),
        ("0.55-0.65", 0.55, 0.65),
        ("0.65-0.75", 0.65, 0.75),
        ("0.75-0.85", 0.75, 0.85),
        ("> 0.85",    0.85, 1.10),
    ]

    analysis = []
    for label, lo, hi in buckets:
        bt = [t for t in trades if lo <= t.get("quality_score", 0) < hi]
        bw = [t for t in bt if t.get("result") == "win"]
        wr = round(len(bw) / len(bt) * 100, 1) if bt else None
        analysis.append({
            "range":        label,
            "threshold_lo": lo,
            "threshold_hi": hi,
            "total":        len(bt),
            "wins":         len(bw),
            "win_rate":     wr,
            "valid":        len(bt) >= MIN_SAMPLE and wr is not None,
            "profitable":   wr is not None and wr >= MIN_WR_TARGET,
        })

    optimal_threshold = 0.55
    recommendation    = "Sin datos suficientes — usando umbral por defecto (0.55)"
    calibrated        = False

    valid_profitable = [b for b in analysis if b["valid"] and b["profitable"]]
    valid_any        = [b for b in analysis if b["valid"]]

    if valid_profitable:
        best = min(valid_profitable, key=lambda b: b["threshold_lo"])
        optimal_threshold = best["threshold_lo"]
        calibrated        = True
        recommendation    = (
            f"Score ≥ {optimal_threshold:.2f} tiene WR {best['win_rate']}% "
            f"con {best['total']} operaciones — umbral recomendado"
        )
    elif valid_any:
        best = max(valid_any, key=lambda b: b["win_rate"] or 0)
        optimal_threshold = best["threshold_lo"]
        calibrated        = True
        recommendation    = (
            f"⚠️  Ningún bucket supera 55% WR. Mejor resultado: "
            f"score ≥ {optimal_threshold:.2f} con {best['win_rate']}% WR "
            f"({best['total']} ops). Considera revisar estrategias."
        )

    return {
        "total_trades":        len(trades),
        "min_trades_required": _MIN_TRADES_TO_CALIBRATE,
        "calibrated":          calibrated,
        "optimal_threshold":   optimal_threshold,
        "current_threshold":   _dynamic_min_quality,
        "recommendation":      recommendation,
        "min_wr_target":       MIN_WR_TARGET,
        "buckets":             analysis,
    }


def get_dynamic_threshold() -> float:
    """Retorna el umbral dinámico actual."""
    return _dynamic_min_quality


def set_dynamic_threshold(value: float) -> None:
    """Actualiza el umbral dinámico (llamado por auto-calibración)."""
    global _dynamic_min_quality
    _dynamic_min_quality = max(0.45, min(0.85, value))
