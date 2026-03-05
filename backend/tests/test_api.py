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
    """
    # Seteamos la clave secreta para el test
    monkeypatch.setenv("API_SECRET_KEY", "test_secret_key")
    
    headers = {"X-API-Key": "test_secret_key"}
    payload = {
        "symbols": ["OTC_EURUSD"],
        "timeframe": "1m",
        "min_confidence": 0.1 # Bajo para asegurar que encuentre algo
    }
    
    response = client.post("/api/signals/scan", json=payload, headers=headers)
    
    # Debug si falla
    if response.status_code != 200:
        print(f"Error en scan: {response.text}")
        
    assert response.status_code == 200
    data = response.json()
    assert "signals" in data
    assert isinstance(data["signals"], list)
