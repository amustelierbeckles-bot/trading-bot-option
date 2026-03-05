# 🚀 GUÍA COMPLETA: Despliegue con Cloudflare + HTTPS

## 📋 Índice
1. [Paso 1: Comprar Dominio](#paso-1-comprar-dominio)
2. [Paso 2: Crear Cuenta Cloudflare](#paso-2-crear-cuenta-cloudflare)
3. [Paso 3: Configurar Cloudflare](#paso-3-configurar-cloudflare)
4. [Paso 4: Preparar el Servidor](#paso-4-preparar-el-servidor)
5. [Paso 5: Desplegar el Bot](#paso-5-desplegar-el-bot)
6. [Paso 6: Verificar HTTPS](#paso-6-verificar-https)
7. [Solución de Problemas](#solución-de-problemas)

---

## Paso 1: Comprar Dominio

### Opción A: Namecheap (Recomendado, ~$10/año)
1. Ve a [namecheap.com](https://namecheap.com)
2. Busca tu dominio (ej: `mitradingbot.com`)
3. Añade al carrito y compra
4. Guarda tus credenciales de Namecheap

### Opción B: Cloudflare Registrar (~$8/año)
1. Ve a [cloudflare.com](https://cloudflare.com)
2. Dashboard → Domain Registration → Register Domain
3. Busca y compra tu dominio

### ✅ Checklist Paso 1
- [ ] Dominio comprado
- [ ] Acceso al panel de administración del dominio

---

## Paso 2: Crear Cuenta Cloudflare

1. Ve a [cloudflare.com](https://cloudflare.com)
2. Click **"Sign Up"** (es gratis)
3. Usa tu email: `mbeckles88@gmail.com`
4. Verifica tu email
5. Completa el onboarding básico

### ✅ Checklist Paso 2
- [ ] Cuenta Cloudflare creada
- [ ] Email verificado

---

## Paso 3: Configurar Cloudflare

### 3.1 Agregar tu Sitio a Cloudflare

1. En el Dashboard de Cloudflare, click **"+ Add Site"**
2. Introduce tu dominio: `mitradingbot.com`
3. Selecciona el plan: **"Free"** (suficiente para empezar)
4. Click **"Continue"**

### 3.2 Cambiar Nameservers (IMPORTANTE)

Cloudflare te dará 2 nameservers. Debes cambiarlos en tu registrador:

**Ejemplo (Cloudflare te dará algo como):**
```
alan.ns.cloudflare.com
rita.ns.cloudflare.com
```

**En Namecheap:**
1. Login en Namecheap → Domain List
2. Click **"Manage"** en tu dominio
3. Sección **"Nameservers"**
4. Selecciona **"Custom DNS"**
5. Pega los 2 nameservers de Cloudflare
6. Guarda cambios (puede tardar 24-48 horas)

**Verificación:**
- En Cloudflare, click **"Done, check nameservers"**
- Espera el email de confirmación (~30 min a 24 horas)
- Status cambiará a **"Active"**

### 3.3 Configurar SSL/TLS (HTTPS)

1. En Cloudflare Dashboard → tu sitio
2. Ve a la pestaña **"SSL/TLS"**
3. Selecciona modo: **"Full (Strict)"** ⭐
   - Esto encripta entre Cloudflare y tu servidor
4. En **"Edge Certificates"**, verifica que esté **"Active"**
5. En **"Always Use HTTPS"**: **ON** ✅

### 3.4 Configurar DNS Records

1. Ve a la pestaña **"DNS"**
2. Añade estos registros:

| Type | Name | Content | TTL | Proxy Status |
|------|------|---------|-----|--------------|
| A | `@` | IP_DE_TU_SERVIDOR | Auto | Proxied 🟠 |
| A | `www` | IP_DE_TU_SERVIDOR | Auto | Proxied 🟠 |
| A | `api` | IP_DE_TU_SERVIDOR | Auto | Proxied 🟠 |

**Nota:** 🟠 "Proxied" significa que Cloudflare protege la IP real

**Obtener tu IP de servidor:**
```bash
# Si usas DigitalOcean, AWS, etc., es la IP pública de tu droplet/instancia
# Ejemplo: 123.456.789.012
```

### 3.5 Configurar Seguridad Adicional

1. **"Security"** → **"Security Level"**: **"High"**
2. **"Security"** → **"Challenge Passage"**: **30 minutes**
3. **"Speed"** → **"Auto Minify"**: ON para JS, CSS, HTML
4. **"Caching"** → **"Caching Level"**: **"Standard"**

### 3.6 Configurar Page Rules (Opcional pero recomendado)

1. Ve a **"Page Rules"**
2. Click **"Create Page Rule"**
3. **URL pattern**: `*tudominio.com/api/*`
4. **Settings**:
   - SSL: Full (Strict)
   - Security Level: High
   - Cache Level: Bypass (APIs no deben cachearse)
5. Save and Deploy

### ✅ Checklist Paso 3
- [ ] Sitio agregado a Cloudflare
- [ ] Nameservers cambiados
- [ ] SSL/TLS en modo "Full (Strict)"
- [ ] "Always Use HTTPS" activado
- [ ] DNS records A creados y proxied
- [ ] Page rule para /api/* creada

---

## Paso 4: Preparar el Servidor

### 4.1 Crear un VPS (Servidor Virtual)

**Opciones recomendadas:**

| Proveedor | Plan | Precio | Link |
|-----------|------|--------|------|
| DigitalOcean | Basic Droplet 2GB | $12/mes | [digitalocean.com](https://digitalocean.com) |
| Hetzner | CPX11 | €4.51/mes | [hetzner.com](https://hetzner.com) |
| Vultr | Cloud Compute 2GB | $10/mes | [vultr.com](https://vultr.com) |

**Requisitos mínimos:**
- 2 GB RAM
- 1 vCPU
- 25 GB SSD
- Ubuntu 22.04 LTS

### 4.2 Conectarte al Servidor

```bash
# En Windows (PowerShell o Git Bash)
ssh root@IP_DE_TU_SERVIDOR

# Ejemplo
ssh root@123.456.789.012
```

**Contraseña:** La que te envió el proveedor por email

### 4.3 Instalar Dependencias

```bash
# Actualizar sistema
apt update && apt upgrade -y

# Instalar Docker
apt install -y docker.io docker-compose git curl

# Iniciar Docker
systemctl enable docker
systemctl start docker

# Verificar instalación
docker --version
docker-compose --version
```

### 4.4 Configurar Firewall (IMPORTANTE)

```bash
# Instalar UFW (Uncomplicated Firewall)
apt install -y ufw

# Permitir solo puertos necesarios
ufw allow 22/tcp    # SSH
ufw allow 80/tcp   # HTTP (Cloudflare)
ufw allow 443/tcp  # HTTPS (Cloudflare)

# Bloquear todo lo demás
ufw default deny incoming
ufw default allow outgoing

# Activar
ufw enable

# Verificar estado
ufw status
```

### ✅ Checklist Paso 4
- [ ] VPS creado y accesible
- [ ] Docker instalado
- [ ] Firewall UFW configurado
- [ ] Tienes IP pública del servidor

---

## Paso 5: Desplegar el Bot

### 5.1 Clonar el Repositorio

```bash
# En el servidor
mkdir -p /opt/trading-bot
cd /opt/trading-bot

# Copiar tus archivos (si no usas git, usa SCP o FTP)
# Si usas git:
git clone https://github.com/tuusuario/tu-repo.git .
```

### 5.2 Configurar Variables de Entorno

```bash
# Crear archivo de producción
cd /opt/trading-bot
nano .env.production
```

**Pega esto (reemplaza con tus valores reales):**

```bash
# =============================================================================
# PRODUCCIÓN - Variables de Entorno
# =============================================================================

# MongoDB
MONGO_URL=mongodb://mongo:27017
DB_NAME=trading_bot

# Redis
REDIS_URL=redis://redis:6379

# Seguridad (generar con: openssl rand -hex 32)
JWT_SECRET=TU_JWT_SECRET_AQUI
ENCRYPTION_MASTER_KEY=TU_ENCRYPTION_KEY_AQUI
API_SECRET_KEY=TU_API_SECRET_KEY_AQUI

# APIs Externas
TWELVE_DATA_API_KEY=TU_API_KEY_DE_TWELVEDATA
TWELVE_DATA_CACHE_TTL=300

# Telegram
TELEGRAM_BOT_TOKEN=TU_BOT_TOKEN
TELEGRAM_CHAT_ID=TU_CHAT_ID
TELEGRAM_ENABLED=true
TELEGRAM_ONLY_FIRE=false

# Email
SENDER_EMAIL=noreply@tudominio.com
REPORT_EMAIL=mbeckles88@gmail.com

# Configuración
ENVIRONMENT=production
LOG_LEVEL=WARNING

# CORS - Solo tu dominio
CORS_ORIGINS=https://tudominio.com

# Rate Limiting
MAX_LOGIN_ATTEMPTS=5
LOGIN_ATTEMPT_WINDOW=300
ACCOUNT_LOCKOUT_DURATION=900

# Twelve Data
TWELVE_DATA_DAILY_LIMIT=5000
ACCOUNT_MODE=demo
```

**Guardar:** Ctrl+O, Enter, Ctrl+X

### 5.3 Configurar Frontend para Producción

```bash
cd /opt/trading-bot/frontend

# Crear .env.production
nano .env.production
```

**Contenido:**
```bash
REACT_APP_BACKEND_URL=https://tudominio.com
REACT_APP_API_KEY=TU_API_SECRET_KEY_AQUI
GENERATE_SOURCEMAP=false
```

**Guardar y salir**

### 5.4 Construir el Frontend

```bash
cd /opt/trading-bot/frontend

# Instalar dependencias
yarn install

# Construir para producción
yarn build

# Verificar que se creó la carpeta build
ls -la build/
```

### 5.5 Iniciar los Servicios

```bash
cd /opt/trading-bot

# Descargar imágenes y construir
docker-compose -f docker-compose.production.yml pull
docker-compose -f docker-compose.production.yml build

# Iniciar en modo detached (background)
docker-compose -f docker-compose.production.yml up -d

# Verificar estado
docker-compose -f docker-compose.production.yml ps

# Ver logs
docker-compose -f docker-compose.production.yml logs -f
```

### 5.6 Verificar que Funciona

```bash
# Test API
curl http://localhost:8000/api/health

# Ver logs de Nginx
docker-compose -f docker-compose.production.yml logs nginx
```

### ✅ Checklist Paso 5
- [ ] Archivos en /opt/trading-bot
- [ ] .env.production configurado
- [ ] Frontend construido (carpeta build/)
- [ ] Docker Compose iniciado
- [ ] Logs sin errores

---

## Paso 6: Verificar HTTPS

### 6.1 Test desde Navegador

1. Abre: `https://tudominio.com`
2. Deberías ver: 🔒 **"Conexión segura"** o **"Secure"**
3. Click en el candado → "Certificate is valid"

### 6.2 Test con curl

```bash
# Desde tu computadora local
curl -I https://tudominio.com

# Debería mostrar:
# HTTP/2 200
# server: cloudflare
# cf-ray: ...
```

### 6.3 Verificar Seguridad Online

Ve a estos sitios y escanea tu dominio:

1. **SSL Labs**: https://www.ssllabs.com/ssltest/
   - Debería obtener: **A+**

2. **Security Headers**: https://securityheaders.com/
   - Debería obtener: **A** o **A+**

### 6.4 Verificar API Protegida

```bash
# Sin API key (debe fallar)
curl -X POST https://tudominio.com/api/trades \
  -H "Content-Type: application/json" \
  -d '{"test":"data"}'

# Respuesta esperada: {"error":"X-API-Key header required"}

# Con API key (debe funcionar)
curl -X POST https://tudominio.com/api/trades \
  -H "Content-Type: application/json" \
  -H "X-API-Key: TU_API_SECRET_KEY" \
  -d '{"signal_id":"test","symbol":"OTC_EURUSD","result":"win"}'
```

### ✅ Checklist Paso 6
- [ ] Sitio carga con HTTPS
- [ ] Candado verde en navegador
- [ ] SSL Labs da A+
- [ ] API protegida funciona con key

---

## 🎉 ¡LISTO! Tu Bot está en Producción

Tu trading bot ahora está:
- ✅ Protegido con HTTPS/SSL
- ✅ Detrás de Cloudflare (DDoS, firewall)
- ✅ Con API protegida por clave
- ✅ Listo para operar desde cualquier lugar

---

## 🔧 Solución de Problemas

### Problema 1: "DNS_PROBE_FINISHED_NXDOMAIN"
**Causa:** DNS no propagado
**Solución:** Esperar 24-48 horas o limpiar caché DNS
```bash
# Windows
ipconfig /flushdns

# Linux
sudo systemd-resolve --flush-caches
```

### Problema 2: "ERR_SSL_PROTOCOL_ERROR"
**Causa:** Configuración SSL incorrecta
**Solución:** Verificar en Cloudflare que está en modo "Full (Strict)"

### Problema 3: "Too Many Redirects"
**Causa:** Loop entre HTTP/HTTPS
**Solución:** En Cloudflare poner "Always Use HTTPS: ON" y en Nginx no forzar HTTPS

### Problema 4: API no responde
```bash
# Verificar logs
docker-compose -f docker-compose.production.yml logs api

# Reiniciar servicios
docker-compose -f docker-compose.production.yml restart
```

### Problema 5: Frontend muestra "Cannot connect to backend"
**Causa:** CORS incorrecto o URL mal configurada
**Solución:** Verificar `REACT_APP_BACKEND_URL` y `CORS_ORIGINS` coincidan con tu dominio HTTPS

---

## 📞 Soporte

Si tienes problemas:
1. Revisa los logs: `docker-compose -f docker-compose.production.yml logs`
2. Verifica Cloudflare Status: https://www.cloudflarestatus.com/
3. Contacta tu proveedor VPS para problemas de servidor

---

**Tiempo estimado total:** 2-3 horas (incluyendo espera de DNS)
**Costo mensual aproximado:** $10-15 (VPS + Dominio)
