-- =====================================================================
-- VotoSeguro Bogotá — Modelo físico (PostgreSQL 16)
-- Basado en "Modelado de la Base de Datos" del documento del proyecto.
-- Las diferencias con el documento están marcadas con  [CAMBIO]  y
-- explicadas en docs/CAMBIOS_RESPECTO_AL_DOCUMENTO.md
-- Todas las fechas se guardan en UTC.
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- =====================================================================
-- ADMINISTRACIÓN
-- =====================================================================
CREATE TABLE administrador (
    id             UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre         VARCHAR(150) NOT NULL,
    usuario        VARCHAR(50)  NOT NULL UNIQUE,
    password_hash  VARCHAR(255) NOT NULL,                 -- bcrypt
    rol            VARCHAR(20)  NOT NULL DEFAULT 'admin'
                   CHECK (rol IN ('admin', 'auditor'))
);

-- =====================================================================
-- VOTANTES Y AUTENTICACIÓN
-- =====================================================================
-- [CAMBIO] documento y correo se cifran a nivel de columna (sección 5.1).
--          La búsqueda se hace por documento_hash (HMAC-SHA256 con clave
--          del servidor), así nunca se compara texto plano en SQL.
-- [CAMBIO] ha_votado se elimina: "ya votó" depende de la elección y se
--          obtiene de emision_token (votante_id, eleccion_id).
-- [CAMBIO] Se agregan los campos de autorización previa (Ley 1581/2012).
CREATE TABLE votante (
    id                        UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    documento_hash            VARCHAR(64) NOT NULL UNIQUE,
    documento_cifrado         BYTEA       NOT NULL,
    correo_cifrado            BYTEA       NOT NULL,
    fecha_registro            TIMESTAMP   NOT NULL DEFAULT timezone('utc', now()),
    fecha_autorizacion_datos  TIMESTAMP,
    version_politica_datos    VARCHAR(20)
);

-- =====================================================================
-- ELECCIONES
-- =====================================================================
CREATE TABLE eleccion (
    id            UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre        VARCHAR(150) NOT NULL,
    fecha_inicio  TIMESTAMP    NOT NULL,
    fecha_fin     TIMESTAMP    NOT NULL,
    estado        VARCHAR(20)  NOT NULL DEFAULT 'BORRADOR'
                  CHECK (estado IN ('BORRADOR', 'ABIERTA', 'CERRADA')),
    admin_id      UUID         NOT NULL REFERENCES administrador(id),
    CONSTRAINT ck_eleccion_fechas CHECK (fecha_fin > fecha_inicio)
);

CREATE TABLE opcion_voto (
    id           UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    eleccion_id  UUID         NOT NULL REFERENCES eleccion(id) ON DELETE CASCADE,
    nombre       VARCHAR(150) NOT NULL,
    descripcion  TEXT,
    CONSTRAINT uq_opcion_nombre UNIQUE (eleccion_id, nombre)
);

-- [CAMBIO] eleccion_id: el OTP se emite para una elección concreta.
-- [CAMBIO] intentos: bloquea el código tras 5 intentos fallidos
--          (un código de 6 dígitos sin límite se adivina por fuerza bruta).
-- codigo_hash = HMAC-SHA256(código, clave del servidor); nunca en claro.
CREATE TABLE codigo_otp (
    id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    votante_id        UUID        NOT NULL REFERENCES votante(id) ON DELETE CASCADE,
    eleccion_id       UUID        NOT NULL REFERENCES eleccion(id) ON DELETE CASCADE,
    codigo_hash       VARCHAR(64) NOT NULL,
    fecha_generacion  TIMESTAMP   NOT NULL DEFAULT timezone('utc', now()),
    fecha_expiracion  TIMESTAMP   NOT NULL,
    usado             BOOLEAN     NOT NULL DEFAULT FALSE,
    intentos          SMALLINT    NOT NULL DEFAULT 0,
    CONSTRAINT ck_otp_expiracion CHECK (fecha_expiracion > fecha_generacion)
);
CREATE INDEX idx_otp_votante_fecha ON codigo_otp (votante_id, fecha_generacion);

-- =====================================================================
-- SEPARACIÓN IDENTIDAD–VOTO
-- =====================================================================
-- token_voto NO tiene ninguna referencia a votante.
CREATE TABLE token_voto (
    id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    eleccion_id    UUID        NOT NULL REFERENCES eleccion(id),
    hash           VARCHAR(64) NOT NULL UNIQUE,
    usado          BOOLEAN     NOT NULL DEFAULT FALSE,
    fecha_emision  TIMESTAMP   NOT NULL DEFAULT timezone('utc', now()),
    fecha_uso      TIMESTAMP
);

-- [CAMBIO] Clave para el anonimato: emision_token YA NO guarda token_voto_id.
--   En el documento: votante → emision_token → token_voto → voto
--   permitía re-identificar cualquier voto con un JOIN (justo lo que la
--   sección 5.1 dice que hay que evitar). Ahora emision_token solo dice
--   "a este votante ya se le emitió su token para esta elección".
-- [CAMBIO] UNIQUE (votante_id, eleccion_id) en vez de UNIQUE (votante_id):
--   un votante puede participar en varias elecciones.
-- [CAMBIO] fecha_emision es DATE (no TIMESTAMP) para que la hora exacta no
--   sirva para cruzar la emisión con el voto.
-- votante_id pasa a NULL si el votante ejerce su derecho de supresión: el
--   registro se conserva para que el conteo de emisiones siga cuadrando.
CREATE TABLE emision_token (
    id             UUID  PRIMARY KEY DEFAULT gen_random_uuid(),
    votante_id     UUID  REFERENCES votante(id) ON DELETE SET NULL,
    eleccion_id    UUID  NOT NULL REFERENCES eleccion(id),
    fecha_emision  DATE  NOT NULL DEFAULT (timezone('utc', now()))::date,
    CONSTRAINT uq_emision_votante_eleccion UNIQUE (votante_id, eleccion_id)
);

-- =====================================================================
-- VOTO
-- =====================================================================
CREATE TABLE voto (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    token_voto_id   UUID        NOT NULL UNIQUE REFERENCES token_voto(id),
    opcion_id       UUID        NOT NULL REFERENCES opcion_voto(id),
    timestamp_voto  TIMESTAMP   NOT NULL DEFAULT timezone('utc', now()),
    hash_voto       VARCHAR(64) NOT NULL
);

-- =====================================================================
-- LEDGER — CADENA DE HASHES
-- =====================================================================
CREATE TABLE bloque_ledger (
    id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    eleccion_id       UUID        NOT NULL REFERENCES eleccion(id),
    voto_id           UUID        NOT NULL UNIQUE REFERENCES voto(id),
    hash_anterior     VARCHAR(64) NOT NULL,
    hash_actual       VARCHAR(64) NOT NULL UNIQUE,
    timestamp_bloque  TIMESTAMP   NOT NULL DEFAULT timezone('utc', now()),
    indice            BIGINT      NOT NULL CHECK (indice >= 0)
);
CREATE UNIQUE INDEX idx_bloque_eleccion_indice ON bloque_ledger (eleccion_id, indice);

-- =====================================================================
-- AUDITORÍA
-- =====================================================================
CREATE TABLE registro_auditoria (
    id                UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    admin_id          UUID         REFERENCES administrador(id) ON DELETE SET NULL,
    accion            VARCHAR(100) NOT NULL,
    detalle           TEXT,
    timestamp_accion  TIMESTAMP    NOT NULL DEFAULT timezone('utc', now())
);
CREATE INDEX idx_auditoria_fecha ON registro_auditoria (timestamp_accion DESC);

-- =====================================================================
-- [CAMBIO] SOPORTE DE SEGURIDAD (sección 5.3 del documento)
-- =====================================================================
-- JWT consumidos/revocados: un JWT de votante sirve para UN solo POST /votos.
CREATE TABLE jwt_revocado (
    jti     UUID       PRIMARY KEY,
    expira  TIMESTAMP  NOT NULL,
    motivo  VARCHAR(30) NOT NULL
);

-- Contador genérico para limitar intentos (login de administrador, etc.).
CREATE TABLE limite_tasa (
    id     BIGSERIAL    PRIMARY KEY,
    clave  VARCHAR(128) NOT NULL,
    ts     TIMESTAMP    NOT NULL DEFAULT timezone('utc', now())
);
CREATE INDEX idx_limite_tasa_clave_ts ON limite_tasa (clave, ts);

-- =====================================================================
-- INMUTABILIDAD (defensa en profundidad)
-- =====================================================================
-- Ni la aplicación ni nadie sin desactivar triggers puede modificar o
-- borrar votos y bloques. Si alguien con privilegios de superusuario lo
-- hace igualmente, GET /ledger/{id}/verificar lo detecta.
CREATE OR REPLACE FUNCTION fn_bloquear_modificacion() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'La tabla % es de solo inserción (registro inmutable)', TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_voto_inmutable
    BEFORE UPDATE OR DELETE ON voto
    FOR EACH ROW EXECUTE FUNCTION fn_bloquear_modificacion();

CREATE TRIGGER trg_bloque_inmutable
    BEFORE UPDATE OR DELETE ON bloque_ledger
    FOR EACH ROW EXECUTE FUNCTION fn_bloquear_modificacion();

CREATE TRIGGER trg_auditoria_inmutable
    BEFORE UPDATE OR DELETE ON registro_auditoria
    FOR EACH ROW EXECUTE FUNCTION fn_bloquear_modificacion();

-- Un token usado no puede volver a "no usado".
CREATE OR REPLACE FUNCTION fn_token_un_solo_uso() RETURNS trigger AS $$
BEGIN
    IF OLD.usado AND NOT NEW.usado THEN
        RAISE EXCEPTION 'Un token de voto usado no puede reactivarse';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Los tokens de voto no se pueden borrar';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_token_un_solo_uso
    BEFORE UPDATE OR DELETE ON token_voto
    FOR EACH ROW EXECUTE FUNCTION fn_token_un_solo_uso();
