# Reverse proxy con terminación TLS (sección 5.1 del documento)
FROM nginx:1.27-alpine

RUN apk add --no-cache openssl

# Genera un certificado autofirmado la primera vez (solo para desarrollo).
# En producción monte certificados reales en /etc/nginx/certs.
COPY 10-certificado.sh /docker-entrypoint.d/10-certificado.sh
RUN chmod +x /docker-entrypoint.d/10-certificado.sh

COPY default.conf.template /etc/nginx/templates/default.conf.template
COPY proxy_api.inc /etc/nginx/conf.d/proxy_api.inc
