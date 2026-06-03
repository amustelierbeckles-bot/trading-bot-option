# Lecciones — Pocket-option-bot

Reglas anti-error del proyecto. Revisar al inicio de sesión (CLAUDE.md self-improvement loop).

## L1 — `docker restart` NO recarga `.env` (2026-06-02)
**Síntoma:** rotamos `TELEGRAM_BOT_TOKEN` en `.env.production`, `docker restart trading-bot-api`, pero el container siguió poleando con el token viejo (`getUpdates 401 Unauthorized`).
**Causa:** Docker inyecta variables de entorno solo al **CREAR** el container, no al reiniciarlo. `docker restart` reusa el env original.
**Fix:** recrear el container: `docker stop` + `docker rm` + `docker compose -f docker-compose.production.yml up -d <svc>`. NUNCA `--force-recreate` (KeyError ContainerConfig en este VPS).
**Verificación:** comparar secret env vs container con `docker exec <c> printenv VAR` antes de asumir que tomó el cambio.

## L2 — Revoke de token Telegram conserva el bot id
**Dato:** `@BotFather` revoke cambia solo el secret (parte tras `:`), el bot id (antes de `:`) permanece. Comparar tokens por el secret, no por el id.
