# ============================================================================
# DOCKERFILE - Trading Bot API (backend context)
# ============================================================================

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# Instalación explícita: SOCKS para PO WebSocket (websockets 16+); evita deploy sin el paquete si requirements quedó desincronizado en el VPS
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir "python-socks[asyncio]>=1.7.1"

COPY . .

RUN mkdir -p /var/log/trading-bot && chmod 777 /var/log/trading-bot

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health', timeout=5)"

CMD ["python", "server.py"]
