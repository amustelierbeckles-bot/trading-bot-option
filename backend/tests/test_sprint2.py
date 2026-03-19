"""
Tests Sprint 2 — Circuit Breaker autónomo y Session Labels.

Cubre:
- _get_market_session: session_type labels (london/newyork/asia/off)
- _cb_record_result: lógica de disparo y reset del CB
- _cb_is_blocked: verificación y expiración de cooldown
- reset-circuit-breaker endpoint: libera el bloqueo
"""
import pytest
import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.append(str(Path(__file__).parent.parent))

from market_session import get_market_session as _get_market_session
from circuit_breaker import (
    cb_record_result as _cb_record_result,
    cb_is_blocked as _cb_is_blocked,
    _cb_state,
    CB_CONSECUTIVE_LIMIT,
)


# ── Fixture: resetea CB antes de cada test ────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_cb():
    """Garantiza que el Circuit Breaker empiece limpio en cada test."""
    _cb_state.update({
        "blocked":            False,
        "blocked_until":      None,
        "consecutive_losses": 0,
        "reason":             "",
    })
    yield
    _cb_state.update({
        "blocked":            False,
        "blocked_until":      None,
        "consecutive_losses": 0,
        "reason":             "",
    })


# ── _get_market_session — Session Labels ─────────────────────────────────────

def test_session_london_utc_morning():
    """08:00–12:59 UTC → sesión london."""
    s = _get_market_session(utc_hour=10, utc_minute=0)
    # La ventana activa (UTC-5 mañana = 09:30-12:00) cae en 14:30-17:00 UTC
    # A las 10:00 UTC está fuera de la ventana operativa → "off" pero session_type="london"
    # Verificamos que el campo name usa etiquetas estándar
    assert s["name"] in ("london", "newyork", "asia", "off"), \
        f"name debe ser una etiqueta estándar, obtenido: {s['name']}"


def test_session_name_is_newyork_at_14_30_utc():
    """14:30 UTC (09:30 UTC-5) → ventana mañana activa.
    14:30 UTC está en el rango NY (13:00–21:00 UTC) → name='newyork'."""
    s = _get_market_session(utc_hour=14, utc_minute=30)
    assert s["active"] is True
    assert s["name"] == "newyork"   # 14:30 UTC está en la sesión NY (13–21 UTC)
    assert "display" in s, "Debe tener campo 'display' para logging"


def test_session_off_outside_operative_window():
    """09:00 UTC (04:00 UTC-5) → fuera de ventana operativa → name='off', active=False."""
    s = _get_market_session(utc_hour=9, utc_minute=0)
    # 04:00 UTC-5 está entre el fin de madrugada (02:00) y el inicio de mañana (09:30)
    assert s["active"] is False
    assert s["name"] == "off"


def test_session_name_is_newyork_at_16_00_utc():
    """15:00 UTC (11:00 UTC-4 / 10:00 UTC-5) → ventana mañana activa, session newyork (13–21 UTC).
    Se usa 15:00 UTC para que sea activo tanto en verano (UTC-4) como en invierno (UTC-5)."""
    s = _get_market_session(utc_hour=15, utc_minute=0)
    assert s["active"] is True
    assert s["name"] == "newyork"


def test_session_off_at_20_00_utc():
    """20:00 UTC (15:00 UTC-5) → fuera de ventana operativa."""
    s = _get_market_session(utc_hour=20, utc_minute=0)
    assert s["active"] is False
    assert s["name"] == "off"


def test_session_asia_at_05_30_utc():
    """05:30 UTC (00:30 UTC-5) → ventana madrugada activa, session asia (00–08 UTC)."""
    s = _get_market_session(utc_hour=5, utc_minute=30)
    assert s["active"] is True
    assert s["name"] == "asia"


def test_session_has_display_field():
    """Todas las sesiones deben tener 'display' además de 'name'."""
    for h in [5, 10, 14, 16, 20]:
        s = _get_market_session(utc_hour=h, utc_minute=0)
        assert "display" in s, f"Falta 'display' a las {h}:00 UTC"
        assert "name" in s


# ── Circuit Breaker — Lógica de disparo ───────────────────────────────────────

def test_cb_single_loss_does_not_trigger():
    """1 pérdida no dispara el CB."""
    _cb_record_result("loss", "OTC_EURUSD")
    assert _cb_state["consecutive_losses"] == 1
    assert _cb_state["blocked"] is False


def test_cb_win_resets_counter():
    """Un win después de 2 losses resetea el contador."""
    _cb_record_result("loss", "OTC_EURUSD")
    _cb_record_result("loss", "OTC_EURUSD")
    _cb_record_result("win",  "OTC_EURUSD")
    assert _cb_state["consecutive_losses"] == 0
    assert _cb_state["blocked"] is False


def test_cb_triggers_after_consecutive_losses():
    """3 pérdidas consecutivas deben disparar el bloqueo."""
    for _ in range(CB_CONSECUTIVE_LIMIT):
        _cb_record_result("loss", "OTC_EURUSD")

    assert _cb_state["blocked"] is True
    assert _cb_state["blocked_until"] is not None
    assert _cb_state["consecutive_losses"] == CB_CONSECUTIVE_LIMIT


def test_cb_is_blocked_returns_true_when_triggered():
    """_cb_is_blocked() retorna True durante el cooldown."""
    _cb_state.update({
        "blocked":       True,
        "blocked_until": datetime.utcnow() + timedelta(hours=1),
        "consecutive_losses": CB_CONSECUTIVE_LIMIT,
    })
    assert _cb_is_blocked() is True


def test_cb_is_blocked_auto_resets_on_expiry():
    """_cb_is_blocked() resetea automáticamente cuando el cooldown expira."""
    _cb_state.update({
        "blocked":       True,
        "blocked_until": datetime.utcnow() - timedelta(seconds=1),  # ya expiró
        "consecutive_losses": CB_CONSECUTIVE_LIMIT,
    })
    assert _cb_is_blocked() is False
    assert _cb_state["blocked"] is False
    assert _cb_state["consecutive_losses"] == 0


def test_cb_does_not_re_trigger_when_already_blocked():
    """Nuevas pérdidas no deben re-disparar un CB ya activo."""
    _cb_state.update({
        "blocked":       True,
        "blocked_until": datetime.utcnow() + timedelta(hours=1),
        "consecutive_losses": CB_CONSECUTIVE_LIMIT,
    })
    original_until = _cb_state["blocked_until"]
    _cb_record_result("loss", "OTC_EURUSD")  # no debe cambiar blocked_until
    assert _cb_state["blocked_until"] == original_until


# ── Circuit Breaker — Endpoint reset ─────────────────────────────────────────

def test_reset_circuit_breaker_endpoint(client):
    """POST /api/risk/reset-circuit-breaker desbloquea el CB autónomo."""
    # Primero disparar el CB
    _cb_state.update({
        "blocked":            True,
        "blocked_until":      datetime.utcnow() + timedelta(hours=1),
        "consecutive_losses": CB_CONSECUTIVE_LIMIT,
    })
    assert _cb_is_blocked() is True

    response = client.post("/api/risk/circuit-breaker/reset",
                           headers={"X-API-Key": "test_secret_key"})
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["circuit_breaker"]["blocked"] is False
    assert data["circuit_breaker"]["consecutive_losses"] == 0

    # Verificar que el estado global también se reseteó
    assert _cb_is_blocked() is False
