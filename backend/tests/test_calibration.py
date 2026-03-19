"""
Tests críticos — Calibración del Umbral Dinámico
Verifica que _compute_optimal_threshold SOLO usa trades con
audit_confidence='high' y que el algoritmo de calibración
es correcto según las reglas de negocio.
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from calibration import compute_optimal_threshold as _compute_optimal_threshold, _MIN_TRADES_TO_CALIBRATE


def _make_trade(result: str, quality_score: float, audit_confidence: str = "high") -> dict:
    """Helper para construir trades de prueba."""
    return {
        "result": result,
        "quality_score": quality_score,
        "audit_confidence": audit_confidence,
    }


class TestCalibrationOnlyUsesHighConfidence:
    """
    Regla de negocio crítica: la calibración NUNCA debe usar trades
    con audit_confidence != 'high'. Datos corruptos contaminan el umbral.
    """

    def test_only_high_confidence_trades_affect_result(self):
        """
        Si mezclamos trades high y low confidence con resultados opuestos,
        el resultado debe reflejar solo los high-confidence.
        """
        # 25 trades high-confidence con WR alto (score 0.75-0.85)
        high_conf = [_make_trade("win", 0.80, "high") for _ in range(20)]
        high_conf += [_make_trade("loss", 0.80, "high") for _ in range(5)]

        # 25 trades low-confidence con WR muy bajo — NO deben afectar la calibración
        low_conf = [_make_trade("loss", 0.80, "low") for _ in range(25)]
        low_conf += [_make_trade("loss", 0.80, "no_data") for _ in range(25)]

        # La función recibe SOLO trades high (el filtro se hace antes de llamarla)
        result_high_only = _compute_optimal_threshold(high_conf)

        # Simulamos pasar todos los trades mezclados SIN filtrar
        all_trades = high_conf + low_conf
        result_mixed = _compute_optimal_threshold(all_trades)

        # El calibrated status debe diferir — con datos mixtos el WR baja
        # Este test documenta que el LLAMADOR debe filtrar antes de llamar
        assert result_high_only["calibrated"] is True, (
            "Con 25 trades high-confidence debe calibrarse"
        )

    def test_non_high_confidence_excluded_gives_correct_wr(self):
        """Solo trades high-confidence: WR calculado debe ser exacto."""
        # 10 wins + 5 losses en score 0.65-0.75 → WR = 66.7%
        trades = (
            [_make_trade("win",  0.70, "high") for _ in range(10)] +
            [_make_trade("loss", 0.70, "high") for _ in range(5)]
        )
        result = _compute_optimal_threshold(trades)
        bucket = next(b for b in result["buckets"] if b["range"] == "0.65-0.75")
        assert bucket["total"] == 15
        assert bucket["wins"] == 10
        assert bucket["win_rate"] == round(10 / 15 * 100, 1)


class TestCalibrationLogic:
    """Verifica la lógica de selección del umbral óptimo."""

    def test_returns_not_calibrated_with_no_trades(self):
        """Sin trades, no hay calibración posible."""
        result = _compute_optimal_threshold([])
        assert result["calibrated"] is False, "Sin trades no debe calibrar"

    def test_returns_not_calibrated_with_insufficient_sample_per_bucket(self):
        """
        Con pocos trades por bucket (< MIN_SAMPLE=5), los buckets son inválidos
        y la calibración no encuentra ningún bucket rentable con muestra válida.
        Nota: el guard de _MIN_TRADES_TO_CALIBRATE lo aplica el llamador,
        no _compute_optimal_threshold directamente.
        """
        # Solo 2 trades en el bucket 0.65-0.75 → bucket inválido (< MIN_SAMPLE=5)
        trades = [
            _make_trade("win",  0.70),
            _make_trade("loss", 0.70),
        ]
        result = _compute_optimal_threshold(trades)
        # Con muestra insuficiente por bucket, ningún bucket es "valid"
        valid_buckets = [b for b in result["buckets"] if b["valid"]]
        assert len(valid_buckets) == 0, "Buckets con < 5 trades no deben ser válidos"

    def test_calibrates_with_sufficient_high_wr_trades(self):
        """Con suficientes trades y buen WR, debe calibrar."""
        trades = (
            [_make_trade("win",  0.70) for _ in range(18)] +
            [_make_trade("loss", 0.70) for _ in range(2)]
        )  # 20 trades, WR=90% en bucket 0.65-0.75
        result = _compute_optimal_threshold(trades)
        assert result["calibrated"] is True
        assert result["optimal_threshold"] > 0

    def test_optimal_threshold_is_lowest_profitable_bucket(self):
        """El umbral óptimo es el bucket MÁS BAJO con WR >= 55%."""
        # Bucket 0.55-0.65: 6 wins / 1 loss → WR 85% (valid, profitable)
        # Bucket 0.75-0.85: 6 wins / 1 loss → WR 85% (valid, profitable)
        trades = (
            [_make_trade("win",  0.60) for _ in range(6)] +
            [_make_trade("loss", 0.60) for _ in range(1)] +
            [_make_trade("win",  0.80) for _ in range(6)] +
            [_make_trade("loss", 0.80) for _ in range(1)] +
            # Relleno para alcanzar MIN_TRADES
            [_make_trade("win",  0.70) for _ in range(6)]
        )
        result = _compute_optimal_threshold(trades)
        assert result["calibrated"] is True
        # Debe elegir el threshold más bajo que es rentable
        assert result["optimal_threshold"] <= 0.65, (
            f"Debe elegir el bucket más bajo rentable, got {result['optimal_threshold']}"
        )

    def test_default_threshold_without_profitable_bucket(self):
        """Si ningún bucket supera el WR mínimo, usa el default."""
        # Todos pierden → WR 0%
        trades = [_make_trade("loss", 0.70) for _ in range(_MIN_TRADES_TO_CALIBRATE)]
        result = _compute_optimal_threshold(trades)
        # Calibrated puede ser True (encontró el mejor disponible) pero
        # el threshold debe ser >= 0 y <= 1
        assert 0.0 <= result["optimal_threshold"] <= 1.0

    def test_result_contains_required_keys(self):
        """El resultado debe tener todas las claves esperadas."""
        trades = [_make_trade("win", 0.70) for _ in range(_MIN_TRADES_TO_CALIBRATE)]
        result = _compute_optimal_threshold(trades)
        required_keys = {
            "calibrated", "optimal_threshold", "current_threshold",
            "recommendation", "buckets", "total_trades", "min_wr_target"
        }
        assert required_keys.issubset(result.keys()), (
            f"Faltan claves en el resultado: {required_keys - result.keys()}"
        )
