#!/bin/sh
# Crea un certificado TLS autofirmado si no existe uno montado.
CERTS=${CERTS_DIR:-/etc/nginx/certs}
if [ ! -f "$CERTS/servidor.crt" ] || [ ! -f "$CERTS/servidor.key" ]; then
  mkdir -p "$CERTS"
  echo "[proxy] Generando certificado autofirmado para ${DOMINIO:-localhost}"
  openssl req -x509 -nodes -newkey rsa:2048 -days 365 \
    -keyout "$CERTS/servidor.key" -out "$CERTS/servidor.crt" \
    -subj "/CN=${DOMINIO:-localhost}/O=VotoSeguro Bogota" \
    -addext "subjectAltName=DNS:${DOMINIO:-localhost},DNS:localhost,IP:127.0.0.1" 2>/dev/null
  chmod 600 "$CERTS/servidor.key"
fi
