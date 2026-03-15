# Skills Router — Pocket Option Bot

> Carga SOLO la skill relevante para la tarea actual.
> NO cargues todas las skills en cada turno — eso desperdicia contexto.

---

## Regla de Uso

Antes de actuar, detecta la tarea según las palabras clave del mensaje del usuario.
Carga únicamente la skill indicada. Si ninguna coincide, opera sin skill extra.

---

## Tabla de Detección

| Si el mensaje contiene...                                                                 | Carga esta skill                                              |
|-------------------------------------------------------------------------------------------|---------------------------------------------------------------|
| `endpoint`, `ruta`, `REST`, `API`, `schema`, `request`, `response`, `versionar`, `OpenAPI` | `.agents/skills/api-design-principles/SKILL.md`              |
| `arquitectura`, `módulo`, `hexagonal`, `DDD`, `clean`, `patrón`, `refactor`, `desacoplar`  | `.agents/skills/architecture-patterns/SKILL.md`              |
| `revisar`, `code review`, `PR`, `pull request`, `calidad`, `mejorar código`                | `.agents/skills/code-review/SKILL.md`                        |
| `analizar datos`, `estadísticas`, `métricas`, `win rate`, `reporte`, `CSV`, `pandas`       | `.agents/skills/data-analysis/SKILL.md`                      |
| `MongoDB`, `colección`, `índice`, `schema`, `migración`, `modelo`, `base de datos`         | `.agents/skills/database-schema-design/SKILL.md`             |
| `logs`, `monitoreo`, `alertas`, `observabilidad`, `Prometheus`, `dashboard`, `traceo`      | `.agents/skills/monitoring-observability/SKILL.md`           |
| `lento`, `optimizar`, `rendimiento`, `profiling`, `memoria`, `async`, `cache`, `bottleneck`| `.agents/skills/python-performance-optimization/SKILL.md`    |
| `seguridad`, `CORS`, `inyección`, `token`, `JWT`, `OWASP`, `rate limit`, `vulnerabilidad`  | `.agents/skills/security-best-practices/SKILL.md`            |

---

## Ejemplos de Activación

**Usuario:** "Agrega un nuevo endpoint para obtener el historial de señales"
→ Detecta: `endpoint` → Carga: `api-design-principles`

**Usuario:** "El bot está lento al procesar 20 pares en paralelo"
→ Detecta: `lento`, `paralelo` → Carga: `python-performance-optimization`

**Usuario:** "Revisa el código del email_service.py antes de hacer push"
→ Detecta: `revisar`, `código` → Carga: `code-review`

**Usuario:** "Diseña el índice de MongoDB para las señales"
→ Detecta: `MongoDB`, `índice` → Carga: `database-schema-design`

**Usuario:** "¿Cuál fue el win rate de esta semana?"
→ Detecta: `win rate`, `estadísticas` → Carga: `data-analysis`

---

## Regla de Combinación

Si el mensaje activa **2 o más** keywords de skills distintas, carga ambas.
Máximo 2 skills simultáneas para no saturar el contexto.

**Ejemplo:** "Optimiza el endpoint de señales que está lento"
→ `endpoint` + `lento` → Carga: `api-design-principles` + `python-performance-optimization`

---

## Skills NO cargar por defecto

Las siguientes skills son pesadas — cárgalas SOLO si el usuario lo pide explícitamente:
- `architecture-patterns` (solo en refactors grandes)
- `monitoring-observability` (solo al configurar infraestructura)
