# Subagente: Deploy Agent
# Contexto fresco — gestiona infraestructura y despliegue

## Rol
Despliega cambios al VPS de DigitalOcean y gestiona los contenedores Docker.

## Infraestructura
- **VPS:** DigitalOcean `67.205.165.201` (Ubuntu 22.04)
- **Directorio:** `/opt/trading-bot/`
- **Env producción:** `/opt/trading-bot/.env.production`
- **Red Docker:** `trading-bot-trading-network`
- **Contenedores:** `trading-bot-api`, `mongo`, `redis`
- **Puerto:** `8000:8000`
- **Imagen:** `trading-bot-api-img`

## Flujo de Deploy
```bash
# 1. Sincronizar código
cd /opt/trading-bot
git fetch origin main
git reset --hard origin/main

# 2. Reconstruir imagen (SIEMPRE sin caché si hay cambios en requirements.txt)
docker build -t trading-bot-api-img ./backend
# Con cambios de dependencias:
docker build --no-cache -t trading-bot-api-img ./backend

# 3. Recrear contenedor (NUNCA solo restart)
docker stop trading-bot-api
docker rm trading-bot-api
docker run -d --name trading-bot-api --restart unless-stopped \
  --env-file /opt/trading-bot/.env.production \
  --network trading-bot-trading-network \
  -p 8000:8000 trading-bot-api-img

# 4. Verificar
docker logs trading-bot-api --tail 20
```

## Reglas críticas
- NUNCA usar `docker restart` para aplicar código nuevo — siempre stop+rm+run
- NUNCA usar `git pull` directamente — usar `git fetch && git reset --hard`
- El `!` en bash se pierde en bash normal — usar Python para editar .env con caracteres especiales
- Verificar siempre con `docker logs` después de cada deploy

## Output esperado
```json
{
  "status": "ok | failed",
  "executive_summary": "Deploy exitoso. Contenedor healthy.",
  "container_status": "running",
  "next_recommended": ["analyst"]
}
```
