import pytest
from server import app

# Eliminamos la creación global de client.
# Pytest inyectará el fixture 'client' definido en conftest.py automáticamente
# cuando lo pidamos como argumento en las funciones de test.

def test_health_check(client):
    """
    Verifica que el servidor responda correctamente en la ruta raíz o health.
    """
    response = client.get("/")
    # El endpoint raiz no existe en server.py, asi que 404 es correcto,
    # lo importante es que responda el servidor (no 500 ni connection refused)
    assert response.status_code in [200, 404]

def test_scan_signals_unauthorized(client):
    """
    Verifica que el endpoint de escaneo requiera autenticación si está protegido.
    """
    # Intentamos escanear sin API Key
    response = client.post("/api/signals/scan", json={"symbols": ["OTC_EURUSD"]})
    
    # Debería ser 401 Unauthorized o 403 Forbidden
    assert response.status_code in [401, 403]

def test_scan_signals_authorized(client, monkeypatch):
    """
    Verifica el escaneo con credenciales simuladas.
    Comprueba que la respuesta tenga la estructura correcta
    y que el quality_score esté presente en cada señal generada.
    """
    monkeypatch.setenv("API_SECRET_KEY", "test_secret_key")

    headers = {"X-API-Key": "test_secret_key"}
    payload = {
        "symbols": ["OTC_EURUSD"],
        "timeframe": "1m",
        "min_confidence": 0.1  # Bajo para maximizar chance de señal
    }

    response = client.post("/api/signals/scan", json=payload, headers=headers)

    if response.status_code != 200:
        print(f"Error en scan: {response.text}")

    assert response.status_code == 200
    data = response.json()

    # Estructura básica de la respuesta
    assert "signals" in data
    assert "new_signals" in data
    assert isinstance(data["signals"], list)
    assert data["new_signals"] == len(data["signals"])

    # Si se generaron señales, verificar que tengan los campos requeridos
    for signal in data["signals"]:
        assert "quality_score" in signal, "quality_score debe estar en cada señal"
        assert "data_source"   in signal, "data_source debe indicar si datos son reales o simulados"
        assert "type"          in signal, "type debe ser CALL o PUT"
        assert signal["type"]  in ("CALL", "PUT")
        assert 0.0 <= signal["quality_score"] <= 1.0, "quality_score debe estar entre 0 y 1"
