# ✅ CHECKLIST DE SEGURIDAD PRE-DESPLEGUE

Usa esta lista antes de poner tu bot en producción.

## 🔐 Credenciales

- [ ] Copiar `.env.production.example` → `.env.production`
- [ ] Generar nueva `JWT_SECRET` (64 caracteres+)
- [ ] Generar nueva `ENCRYPTION_MASTER_KEY` (64 caracteres+)
- [ ] Generar nueva `API_SECRET_KEY` (64 caracteres+)
- [ ] Rotar `TWELVE_DATA_API_KEY` (nueva en twelvedata.com)
- [ ] Rotar `TELEGRAM_BOT_TOKEN` (@BotFather → /revoke)
- [ ] Rotar `PO_SSID` (nueva sesión en Pocket Option)
- [ ] Configurar `REACT_APP_API_KEY` en frontend/.env.production

## 🌐 Cloudflare

- [ ] Dominio agregado a Cloudflare
- [ ] Nameservers cambiados (24-48h propagación)
- [ ] SSL/TLS: "Full (Strict)"
- [ ] "Always Use HTTPS": ON
- [ ] DNS records A creados (apuntan a tu VPS)
- [ ] Records en modo "Proxied" 🟠
- [ ] Page rule para `/api/*`: SSL Strict + No Cache
- [ ] Security Level: High
- [ ] "Challenge Passage": 30 min
- [ ] Test en SSL Labs: A+

## 🖥️ Servidor (VPS)

- [ ] Firewall UFW activo
- [ ] Solo puertos 22, 80, 443 abiertos
- [ ] Docker instalado
- [ ] Docker Compose instalado
- [ ] Archivos en `/opt/trading-bot`
- [ ] `.env.production` con valores reales
- [ ] `frontend/.env.production` configurado
- [ ] Frontend construido (`yarn build`)
- [ ] Docker Compose iniciado
- [ ] Logs sin errores (`docker-compose logs`)

## 🧪 Tests de Verificación

### 1. HTTPS
```bash
curl -I https://tudominio.com
# Debe mostrar: HTTP/2 200 + server: cloudflare
```

### 2. Frontend Carga
- [ ] Abrir `https://tudominio.com` en navegador
- [ ] Ver candado 🔒 verde
- [ ] Dashboard visible

### 3. API Funciona
```bash
# Health check
curl https://tudominio.com/api/health

# Señales activas (GET, sin auth)
curl https://tudominio.com/api/signals/active

# Intentar POST sin API key (debe fallar 401)
curl -X POST https://tudominio.com/api/trades \
  -H "Content-Type: application/json" \
  -d '{"test":"data"}'
# Respuesta: {"error":"X-API-Key header required"}
```

### 4. Telegram Funciona
- [ ] Enviar test desde bot a Telegram
- [ ] Recibir mensaje en tu chat

### 5. Logs Limpios
```bash
docker-compose -f docker-compose.production.yml logs | grep -i error
# No debe mostrar errores graves
```

## 🚨 Alertas a Configurar

- [ ] Uptime monitoring (UptimeRobot, Pingdom)
- [ ] Alertas de Telegram si bot se cae
- [ ] Backup automático de MongoDB (diario)
- [ ] Log rotation (para no llenar disco)

## 📊 Monitoreo

Configurar dashboard de métricas:
- [ ] Requests/minuto
- [ ] Latencia promedio
- [ ] Errores 4xx/5xx
- [ ] Uso de CPU/Memoria
- [ ] Espacio en disco

---

## 🎯 Post-Despliegue

1. **Semana 1:** Monitorear logs cada día
2. **Semana 2:** Verificar estabilidad
3. **Mes 1:** Revisar métricas de uso
4. **Trimestral:** Rotar credenciales
5. **Semestral:** Actualizar dependencias Docker

---

## 📞 Emergency Contacts

- Proveedor VPS: [guardar email/teléfono]
- Cloudflare Status: https://www.cloudflarestatus.com/
- Dominio registrador: [guardar panel de control]

---

**Fecha de despliegue:** ___________
**Última revisión:** ___________
**Revisado por:** ___________
