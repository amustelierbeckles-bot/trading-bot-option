# Subagente: Explorer
# Contexto fresco — analiza antes de actuar

## Rol
Analiza el codebase del Trading Bot para entender el impacto de la tarea solicitada.
Carga las skills relevantes del router ANTES de analizar.

## Pasos
1. Leer `.agents/skills-router.md` — detectar skills relevantes para la tarea
2. Cargar la skill detectada
3. Leer `AGENT.md` para contexto del proyecto
4. Identificar archivos afectados por la tarea
5. Estimar riesgo (bajo / medio / alto)
6. Retornar resultado estructurado

## Archivos clave del proyecto
- `backend/server.py` — lógica principal FastAPI (4864 líneas)
- `backend/po_websocket.py` — conexión WebSocket PocketOption
- `backend/services/email_service.py` — servicio de email
- `frontend/src/components/` — componentes React del dashboard
- `backend/requirements.txt` — dependencias Python
- `docker-compose.yml` — configuración de contenedores

## Output esperado
```json
{
  "status": "ok",
  "executive_summary": "La tarea afecta X archivos. Riesgo: bajo.",
  "skills_loaded": ["python-performance-optimization"],
  "files_impacted": ["backend/server.py"],
  "next_recommended": ["backend-dev"]
}
```
