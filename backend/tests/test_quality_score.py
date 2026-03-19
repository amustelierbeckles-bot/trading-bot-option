"""
Tests críticos — Quality Score
Verifica que _quality_score retorna valores válidos dentro del rango [0, 1]
y que los componentes del score se comportan según las reglas del negocio.
"""
import sys
import os
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from scoring import quality_score as _quality_score


class TestQualityScoreRange:
    """El score siempre debe estar entre 0.0 y 1.0 — regla de negocio absoluta."""

    def test_score_with_minimal_signal(self):
        signal = {"confidence": 0, "cci": 0, "strategies_agreeing": [], "n_total": 1}
        score = _quality_score(signal)
        assert 0.0 <= score <= 1.0, f"Score fuera de rango: {score}"

    def test_score_with_perfect_signal(self):
        signal = {
            "confidence": 1.0,
            "cci": 200,
            "strategies_agreeing": ["cci_alligator", "rsi_bollinger",
                                    "macd_stochastic", "ema_crossover",
                                    "range_breakout"],
            "n_total": 5,
            "type": "CALL",
        }
        score = _quality_score(signal)
        assert 0.0 <= score <= 1.0, f"Score fuera de rango: {score}"

    def test_score_with_high_confidence(self):
        signal = {
            "confidence": 0.9,
            "cci": 150,
            "strategies_agreeing": ["cci_alligator", "macd_stochastic"],
            "n_total": 5,
            "type": "PUT",
        }
        score = _quality_score(signal)
        assert 0.0 <= score <= 1.0

    def test_score_is_float(self):
        signal = {"confidence": 0.7, "cci": 100, "strategies_agreeing": ["cci_alligator"], "n_total": 5}
        score = _quality_score(signal)
        assert isinstance(score, float)

    def test_score_rounded_to_4_decimals(self):
        signal = {"confidence": 0.7, "cci": 100, "strategies_agreeing": ["cci_alligator"], "n_total": 5}
        score = _quality_score(signal)
        assert score == round(score, 4)


class TestQualityScoreLogic:
    """Verifica que las reglas de negocio del score son correctas."""

    def test_more_strategies_gives_higher_score(self):
        """Más estrategias en acuerdo → mayor score (más confluencia ortogonal)."""
        base = {"confidence": 0.7, "cci": 100, "n_total": 5, "type": "CALL"}

        signal_1 = {**base, "strategies_agreeing": ["cci_alligator"]}
        signal_5 = {**base, "strategies_agreeing": [
            "cci_alligator", "rsi_bollinger", "macd_stochastic",
            "ema_crossover", "range_breakout"
        ]}

        score_1 = _quality_score(signal_1)
        score_5 = _quality_score(signal_5)
        assert score_5 > score_1, (
            f"5 estrategias ({score_5}) debe superar 1 estrategia ({score_1})"
        )

    def test_high_cci_increases_score(self):
        """CCI más alto (más momentum) debe producir mayor score."""
        base = {"confidence": 0.7, "strategies_agreeing": ["cci_alligator"], "n_total": 5}

        score_low_cci  = _quality_score({**base, "cci": 10})
        score_high_cci = _quality_score({**base, "cci": 250})
        assert score_high_cci > score_low_cci, (
            f"CCI alto ({score_high_cci}) debe superar CCI bajo ({score_low_cci})"
        )

    def test_full_consensus_bonus(self):
        """Cuando todas las estrategias acuerdan, el bonus de consenso se activa."""
        base = {"confidence": 0.7, "cci": 100, "type": "CALL"}

        signal_full = {**base, "strategies_agreeing": ["a", "b", "c"], "n_total": 3}
        signal_part = {**base, "strategies_agreeing": ["a", "b"],      "n_total": 3}

        score_full = _quality_score(signal_full)
        score_part = _quality_score(signal_part)
        assert score_full > score_part, (
            f"Consenso completo ({score_full}) debe superar parcial ({score_part})"
        )

    def test_zero_confidence_gives_low_score(self):
        """Confianza cero produce un score bajo."""
        signal = {"confidence": 0.0, "cci": 0, "strategies_agreeing": [], "n_total": 1}
        score = _quality_score(signal)
        assert score < 0.3, f"Score con confianza 0 debería ser bajo, got {score}"
