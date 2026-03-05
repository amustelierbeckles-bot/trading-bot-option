import pytest
import sys
import os
from pathlib import Path
from unittest.mock import MagicMock

# Añadir el directorio padre (backend) al sys.path para poder importar server.py
sys.path.append(str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient
from server import app, MultiStrategyEnsemble, KeltnerRSIStrategy, CCIAlligatorStrategy, RSIBollingerStrategy, MACDStochasticStrategy, EMACrossoverStrategy

@pytest.fixture
def mock_env_vars(monkeypatch):
    """
    Simula variables de entorno para evitar errores de configuración
    """
    monkeypatch.setenv("API_SECRET_KEY", "test_secret_key")
    monkeypatch.setenv("MONGO_URI", "mongodb://localhost:27017")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")

@pytest.fixture
def client(mock_env_vars):
    """
    Cliente de prueba síncrono para endpoints que no requieren async DB
    """
    # 1. Simular dependencias de Base de Datos
    app.state.mongodb = MagicMock()
    app.state.db = MagicMock()
    app.state.redis = MagicMock()
    app.state.signals_store = MagicMock()
    app.state.use_mongo = False  # Para tests rápidos sin DB real

    # 2. Inicializar Estrategias y Ensemble (simulando el startup event)
    strategies = {
        "keltner_rsi": KeltnerRSIStrategy(),
        "cci_alligator": CCIAlligatorStrategy(),
        "rsi_bollinger": RSIBollingerStrategy(),
        "macd_stoch": MACDStochasticStrategy(),
        "ema_cross": EMACrossoverStrategy(),
    }
    app.state.strategies = strategies
    app.state.ensemble = MultiStrategyEnsemble(list(strategies.values()))

    # 3. Devolver el cliente usando el contexto (with) para ejecutar eventos de ciclo de vida si los hubiera
    with TestClient(app) as test_client:
        yield test_client
