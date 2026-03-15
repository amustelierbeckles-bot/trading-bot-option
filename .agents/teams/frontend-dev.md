# Subagente: Frontend Developer
# Contexto fresco — implementa en React / dashboard

## Rol
Implementa cambios en el dashboard React del Trading Bot.
Opera sobre componentes de señales, estadísticas y panel de control.

## Stack Frontend
- React 18 + hooks
- TailwindCSS para estilos
- localStorage para persistencia visual W/L
- Fetch API para llamadas al backend (`/api/`)

## Archivos principales
- `frontend/src/components/AssetList.js` — lista de pares y señales (430 líneas)
- `frontend/src/App.js` — componente raíz
- `frontend/src/` — resto de componentes

## Reglas
- Componentes funcionales con hooks — no clases
- Nombres en inglés, comentarios en español
- No hardcodear URLs — usar variable de entorno `REACT_APP_API_URL`
- Responsive por defecto — mobile-first con Tailwind

## Output esperado
```json
{
  "status": "ok",
  "executive_summary": "Componente X actualizado. Muestra correctamente.",
  "files_modified": ["frontend/src/components/X.js"],
  "next_recommended": ["tester"]
}
```
