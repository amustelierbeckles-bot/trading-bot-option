"""
Tests críticos — Circuit Breaker
Verifica que el CB bloquea correctamente tras N pérdidas consecutivas
y que se resetea tras una victoria o al expirar el cooldown.
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.append(str(Path(__file__).parent.parent))

from circuit_breaker import (
    cb_is_blocked as _cb_is_blocked,
    cb_record_result as _cb_record_result,
    _cb_state,
    CB_CONSECUTIVE_LIMIT,
)


def _reset_cb():
    """Resetea el estado del Circuit Breaker antes de cada test."""
    _cb_state.update({
        "blocked": False,
        "blocked_until": None,
        "consecutive_losses": 0,
        "reason": "",
    })


class TestCircuitBreakerBlocking:
    """El CB debe bloquear tras exactamente CB_CONSECUTIVE_LIMIT pérdidas."""

    def test_not_blocked_initially(self):
        _reset_cb()
        assert _cb_is_blocked() is False

    def test_not_blocked_after_fewer_losses_than_limit(self):
        _reset_cb()
        for _ in range(CB_CONSECUTIVE_LIMIT - 1):
            _cb_record_result("loss", "EURUSD")
        assert _cb_is_blocked() is False

    def test_blocked_after_consecutive_losses_reach_limit(self):
        _reset_cb()
        for _ in range(CB_CONSECUTIVE_LIMIT):
            _cb_record_result("loss", "EURUSD")
        assert _cb_is_blocked() is True, (
            f"Debe bloquear tras {CB_CONSECUTIVE_LIMIT} pérdidas consecutivas"
        )

    def test_blocked_state_has_reason(self):
        _reset_cb()
        for _ in range(CB_CONSECUTIVE_LIMIT):
            _cb_record_result("loss", "GBPJPY")
        assert _cb_state["reason"] != "", "El CB bloqueado debe tener una razón registrada"

    def test_blocked_state_has_blocked_until(self):
        _reset_cb()
        for _ in range(CB_CONSECUTIVE_LIMIT):
            _cb_record_result("loss", "AUDUSD")
        assert _cb_state["blocked_until"] is not None, (
            "El CB bloqueado debe tener una fecha de expiración"
        )
        assert _cb_state["blocked_until"] > datetime.utcnow(), (
            "La fecha de expiración debe ser en el futuro"
        )


class TestCircuitBreakerReset:
    """Una victoria debe resetear el contador de pérdidas consecutivas."""

    def test_win_resets_consecutive_losses(self):
        _reset_cb()
        for _ in range(CB_CONSECUTIVE_LIMIT - 1):
            _cb_record_result("loss", "EURUSD")
        _cb_record_result("win", "EURUSD")
        assert _cb_state["consecutive_losses"] == 0, (
            "Una victoria debe resetear el contador de pérdidas"
        )

    def test_win_prevents_blocking(self):
        _reset_cb()
        for _ in range(CB_CONSECUTIVE_LIMIT - 1):
            _cb_record_result("loss", "EURUSD")
        _cb_record_result("win", "EURUSD")
        _cb_record_result("loss", "EURUSD")
        assert _cb_is_blocked() is False, (
            "Después de una victoria, una sola pérdida no debe bloquear"
        )

    def test_cooldown_expiry_auto_resets(self):
        """Cuando el cooldown expira, el CB se resetea automáticamente."""
        _reset_cb()
        # Simula bloqueo con cooldown ya expirado
        _cb_state.update({
            "blocked": True,
            "blocked_until": datetime.utcnow() - timedelta(minutes=1),
            "consecutive_losses": CB_CONSECUTIVE_LIMIT,
            "reason": "test",
        })
        # _cb_is_blocked debe detectar la expiración y resetear
        result = _cb_is_blocked()
        assert result is False, "El CB expirado debe auto-resetearse"
        assert _cb_state["blocked"] is False
        assert _cb_state["consecutive_losses"] == 0


class TestCircuitBreakerIdempotency:
    """El CB no debe re-dispararse si ya está bloqueado."""

    def test_additional_losses_dont_change_blocked_until(self):
        _reset_cb()
        for _ in range(CB_CONSECUTIVE_LIMIT):
            _cb_record_result("loss", "EURUSD")

        blocked_until_first = _cb_state["blocked_until"]
        # Pérdida adicional mientras ya está bloqueado
        _cb_record_result("loss", "EURUSD")
        assert _cb_state["blocked_until"] == blocked_until_first, (
            "El CB ya bloqueado no debe cambiar su blocked_until"
        )
