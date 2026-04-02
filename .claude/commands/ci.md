# /ci — Diagnóstico de CI failures en GitHub Actions

Diagnostica y corrige fallos en el pipeline CI del repo `amustelierbeckles-bot/trading-bot-option`.

## 1. Ver estado actual del CI

```bash
gh run list --repo amustelierbeckles-bot/trading-bot-option --limit 5
gh run view <RUN_ID> --repo amustelierbeckles-bot/trading-bot-option --log-failed
```

## 2. Reproducir localmente

```bash
cd backend
pip install -r requirements.txt
pytest tests/ -v 2>&1 | head -80
```

## 3. Patrones de error conocidos

| Error | Causa probable | Fix |
|-------|---------------|-----|
| `ModuleNotFoundError` | Dependencia faltante en requirements.txt | Agregar módulo |
| `ConnectionRefusedError` en tests | Test intenta conectar a MongoDB/Redis real | Mock o fixture faltante |
| `ImportError` circular | Módulo nuevo con import circular | Revisar dependencias |
| `fixture 'X' not found` | conftest.py desactualizado | Agregar fixture |
| Timeout en WebSocket test | Test espera conexión real | Mock del WebSocket |

## 4. Archivos de test relevantes

- `backend/tests/conftest.py` — fixtures compartidas (MongoDB mock, Redis mock)
- `backend/tests/test_po_websocket_pipeline.py` — WebSocket pipeline
- `backend/tests/test_circuit_breaker.py` — CB + Redis
- `backend/tests/test_strategies.py` — señales

## 5. Antes de pushear un fix

```bash
pytest tests/ -v                    # todos los tests en verde
pytest tests/ -k "test_fallido"     # solo el test que falló
```

## 6. Módulos críticos — no modificar sin confirmación

`auto_exec.py` · `circuit_breaker.py` · `antifragile.py` · `risk_manager.py`
