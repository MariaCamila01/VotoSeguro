#!/bin/sh
# Crea el usuario de base de datos que usa la API, con el mínimo de permisos.
# La API NO es superusuario: no puede desactivar triggers, ni borrar ni
# modificar votos o bloques del ledger.
# (Sin 'set -e': el entrypoint de postgres puede ejecutar este archivo con
#  'source', y ya trae su propio manejo de errores.)
: "${APP_DB_USER:?Falta APP_DB_USER}"
: "${APP_DB_PASSWORD:?Falta APP_DB_PASSWORD}"

psql -v ON_ERROR_STOP=1 \
     --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
     -v app_user="$APP_DB_USER" -v app_pass="$APP_DB_PASSWORD" <<'SQL'
CREATE ROLE :"app_user" LOGIN PASSWORD :'app_pass';

GRANT CONNECT ON DATABASE :"DBNAME" TO :"app_user";
GRANT USAGE ON SCHEMA public TO :"app_user";

-- Lectura de todo
GRANT SELECT ON ALL TABLES IN SCHEMA public TO :"app_user";

-- Escritura donde la lógica lo necesita
GRANT INSERT, UPDATE         ON administrador, eleccion             TO :"app_user";
GRANT INSERT, UPDATE, DELETE ON votante, opcion_voto, codigo_otp    TO :"app_user";
GRANT INSERT, DELETE         ON emision_token                       TO :"app_user";
GRANT INSERT, UPDATE         ON token_voto                          TO :"app_user";
GRANT INSERT                 ON voto, bloque_ledger, registro_auditoria TO :"app_user";
GRANT INSERT, UPDATE, DELETE ON jwt_revocado                        TO :"app_user";
GRANT INSERT, DELETE         ON limite_tasa                         TO :"app_user";
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO :"app_user";
SQL
