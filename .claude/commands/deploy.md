# /deploy — Redeploy completo en VPS

Ejecuta el redeploy completo del trading bot en producción. Sigue estos pasos en orden:

## 1. Confirmar antes de ejecutar

Pregunta al usuario: "¿Confirmas redeploy en VPS `67.205.165.201` (producción real)?"
No continúes sin confirmación explícita.

## 2. Secuencia de deploy

```bash
ssh -i C:/Users/muste/.ssh/trading_bot_key root@67.205.165.201
cd /opt/trading-bot && git pull origin main
docker build --no-cache -t trading-bot-api-img:latest -f backend/Dockerfile backend/
docker stop trading-bot-api && docker rm trading-bot-api
docker run -d --name trading-bot-api \
  --network trading-bot_trading-network \
  --env-file /opt/trading-bot/.env.production \
  -p 8000:8000 trading-bot-api-img:latest
```

**NUNCA usar** `docker compose --force-recreate` — causa `KeyError: ContainerConfig`.

## 3. Verificar post-deploy (esperar ~10s)

```bash
docker logs trading-bot-api --tail 30
curl -s http://67.205.165.201:8000/api/health | python3 -m json.tool
```

## 4. Interpretar resultado

- `po_websocket.connected = true` + `ready_pairs > 0` → ✅ Todo OK
- `connected = true` + `ready_pairs = 0` → Bot conectado pero fuera de ventana (09:30–00:00 UTC-4), normal
- `connected = false` → Problema de auth o proxy — revisar logs
- Loop de reconexión cada ~2min en logs → SSID expirado o IP bloqueada

## 5. Variables críticas en .env.production

Si el deploy fue para actualizar credenciales, verificar que estén presentes:
- `AUTO_EXECUTE=true`
- `ACCOUNT_MODE=real`
- `PO_PROXY_URL=socks5://nskpjqbk:541oyok0gzpn@31.98.14.221:5898`
- `PO_USER_ID=120600861`
- `PO_SECRET=701e816f8df8df027ab56dbe83fd76b6`
