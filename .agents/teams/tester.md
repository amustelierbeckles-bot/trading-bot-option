# Subagente: Tester
# Contexto fresco — verifica calidad antes de deploy

## Rol
Escribe y ejecuta tests para validar los cambios implementados.
Reporta cobertura y detecta regresiones.

## Stack de Testing
- **Backend:** pytest + pytest-asyncio (`backend/tests/`)
- **Frontend:** React Testing Library (`frontend/src/__tests__/`)

## Comandos de ejecución
```bash
# Backend tests
cd backend && python -m pytest tests/ -v

# Frontend tests
cd frontend && npm test -- --watchAll=false
```

## Qué testear siempre
1. Endpoints nuevos o modificados — status codes y payloads
2. Lógica de señales — calidad score, circuit breaker
3. Autenticación — `verify_api_key` no debe bypassearse
4. Email service — mock de Resend, no llamadas reales en tests

## Criterio de aprobación
- 0 tests fallando
- Cobertura ≥ 70% en archivos modificados
- Sin warnings de seguridad nuevos

## Output esperado
```json
{
  "status": "ok | failed",
  "executive_summary": "X/Y tests pasan. Cobertura: Z%.",
  "tests_failed": [],
  "next_recommended": ["deploy-agent"]
}
```
