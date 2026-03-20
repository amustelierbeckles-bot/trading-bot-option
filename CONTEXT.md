 # CONTEXT.md — Estado actual del proyecto
## Última actualización: 20/03/2026 — 02:30 UTC-4

---

## PROBLEMA ACTIVO — SIN SEÑALES 24H
- Causa confirmada: IP del VPS (DigitalOcean datacenter) bloqueada por PO
- PO conecta y suscribe 20 pares pero NO envía ticks de precio
- Solución en curso: proxy residencial via Webshare.io

## SOLUCIÓN EN PROGRESO
- Código listo: po_websocket.py soporta PO_PROXY_URL (commit df516c5)
- Webshare.io: cuenta creada, configurando plan Static Residential
- Configuración elegida: Shared, 20 IPs, 250 GB, $6/mes
- Ubicación: United Kingdom o Random Europa
- Falta: completar pago → obtener credenciales → añadir PO_PROXY_URL al .env del VPS → rebuild

## PRÓXIMOS PASOS
1. Completar compra en Webshare
2. Ir a Proxy List → obtener host, port, user, password
3. En VPS: nano /opt/trading-bot/backend/.env
   Añadir: PO_PROXY_URL=socks5://user:pass@proxy.host:port
4. Rebuild completo:
   docker build -t trading-bot-api-img:latest -f backend/Dockerfile backend/
   docker stop trading-bot-api && docker rm trading-bot-api
   docker-compose -f docker-compose.production.yml up -d api
5. Verificar ticks en logs

## PENDIENTES RESTANTES
✅ Todos los pendientes anteriores resueltos
🔴 Bot sin señales — proxy residencial en curso
🟢 AUTO_EXECUTE — WR 50% → umbral 55%