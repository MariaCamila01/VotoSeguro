# Se construye desde la RAÍZ del repositorio (necesita db/initdb para crear el esquema):
#   docker build -f api/Dockerfile .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app
COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY api/app ./app
COPY api/wsgi.py .
COPY db/initdb ./db/initdb

# La API no corre como root dentro del contenedor
RUN useradd --system --uid 10001 votoseguro
USER votoseguro

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=30s --retries=5 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", 8000)}/api/v1/salud', timeout=2)"

# 1) crea el esquema si hace falta + cuentas iniciales / datos demo (idempotente)
# 2) arranca Gunicorn. Sin access log: el registro de accesos lo lleva el proxy,
#    que omite las rutas de voto.
CMD ["sh", "-c", "flask --app wsgi inicializar && exec gunicorn --workers 3 --bind 0.0.0.0:${PORT} wsgi:app"]
