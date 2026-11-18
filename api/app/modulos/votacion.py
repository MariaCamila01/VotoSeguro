"""3.2 Votación — POST /votos.

Proceso (sección 3.2 del documento):
  1. Valida el JWT (middleware RBAC) y lo INVALIDA de inmediato, salga bien o mal.
  2. Parte CON identidad (transacción A): registra en emision_token que este
     votante ya recibió su token para esta elección. Es lo que impide el
     doble voto.
  3. Parte SIN identidad (transacción B): genera el TokenVoto de un solo uso,
     lo marca como usado, guarda el voto y lo encadena en el ledger. Esta
     función no recibe ningún dato del votante.
  4. Si la parte B falla, se deshace la parte A para que pueda reintentar.

A y B son transacciones separadas a propósito: si fueran una sola, las
filas de emision_token y de voto compartirían el mismo identificador de
transacción interno de PostgreSQL (xmin) y un DBA podría cruzarlas.
"""
from datetime import datetime, timezone

from flask import Blueprint, jsonify

from ..db import ahora, iso, transaccion
from ..errores import ErrorAPI, leer_json, leer_uuid
from ..seguridad.cripto import generar_secreto_token, sha256_hex
from ..seguridad.rbac import usuario_actual
from ..servicios import ledger, padron

bp = Blueprint("votacion", __name__)


@bp.post("/votos")
def emitir_voto():
    u = usuario_actual()
    votante_id = u["sub"]
    eleccion_id = u["eleccionId"]

    # 1. Invalidación inmediata del JWT (sección 5.3)
    expira = datetime.fromtimestamp(u["exp"], timezone.utc).replace(tzinfo=None)
    with transaccion() as cur:
        cur.execute(
            "INSERT INTO jwt_revocado (jti, expira, motivo) VALUES (%s, %s, 'CONSUMIDO') "
            "ON CONFLICT (jti) DO NOTHING RETURNING jti",
            (u["jti"], expira),
        )
        if cur.fetchone() is None:
            raise ErrorAPI(409, "TOKEN_YA_USADO", "Este token ya se usó para votar")

    datos = leer_json()
    opcion_id = leer_uuid(datos.get("opcionId"), "opcionId")

    # 2. Transacción A — identidad
    with transaccion() as cur:
        eleccion = padron.obtener_eleccion(cur, eleccion_id)
        padron.exigir_en_votacion(eleccion)
        cur.execute("SELECT 1 FROM opcion_voto WHERE id = %s AND eleccion_id = %s", (opcion_id, eleccion_id))
        if not cur.fetchone():
            raise ErrorAPI(422, "OPCION_INVALIDA", "La opción no pertenece a esta elección")
        cur.execute("SELECT 1 FROM votante WHERE id = %s", (votante_id,))
        if not cur.fetchone():
            raise ErrorAPI(403, "VOTANTE_NO_HABILITADO", "El votante ya no está en el padrón")
        cur.execute(
            "INSERT INTO emision_token (votante_id, eleccion_id) VALUES (%s, %s) "
            "ON CONFLICT (votante_id, eleccion_id) DO NOTHING RETURNING id",
            (votante_id, eleccion_id),
        )
        if cur.fetchone() is None:
            raise ErrorAPI(403, "YA_VOTO", "Usted ya emitió su voto en esta elección")

    # 3. Transacción B — anónima
    try:
        comprobante = registrar_voto_anonimo(eleccion_id, opcion_id)
    except Exception:
        # 4. Compensación: liberar la emisión para que el votante pueda reintentar
        with transaccion() as cur:
            cur.execute("DELETE FROM emision_token WHERE votante_id = %s AND eleccion_id = %s",
                        (votante_id, eleccion_id))
        raise

    return jsonify(comprobante), 201


def registrar_voto_anonimo(eleccion_id, opcion_id):
    """No recibe ni usa ningún dato del votante."""
    with transaccion() as cur:
        # FOR UPDATE: serializa los votos de una misma elección para que el
        # índice del ledger no se repita y para que el cierre espere.
        eleccion = padron.obtener_eleccion(cur, eleccion_id, bloquear=True)
        padron.exigir_en_votacion(eleccion)

        hash_token = sha256_hex(generar_secreto_token())
        t = ahora()
        cur.execute(
            "INSERT INTO token_voto (eleccion_id, hash, fecha_emision) VALUES (%s, %s, %s) RETURNING id",
            (eleccion_id, hash_token, t),
        )
        token_id = cur.fetchone()["id"]

        # Validar y consumir el token: solo pasa si nadie lo usó antes
        cur.execute("UPDATE token_voto SET usado = TRUE, fecha_uso = %s WHERE id = %s AND usado = FALSE",
                    (t, token_id))
        if cur.rowcount != 1:
            raise ErrorAPI(409, "TOKEN_YA_USADO", "El token de voto ya fue usado")

        hash_voto = ledger.calcular_hash_voto(hash_token, opcion_id, eleccion_id, t)
        cur.execute(
            "INSERT INTO voto (token_voto_id, opcion_id, timestamp_voto, hash_voto) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (token_id, opcion_id, t, hash_voto),
        )
        voto_id = cur.fetchone()["id"]
        bloque = ledger.agregar_bloque(cur, eleccion_id, voto_id, hash_voto)

    return {
        "confirmacion": bloque["id"],
        "hashBloque": bloque["hash_actual"],
        "indiceBloque": bloque["indice"],
        "timestamp": iso(t),
    }
