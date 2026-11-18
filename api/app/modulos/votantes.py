"""Padrón institucional y derecho de supresión (habeas data, Ley 1581 de 2012)."""
from flask import Blueprint, jsonify

from ..db import transaccion
from ..errores import ErrorAPI, leer_json, payload_invalido
from ..seguridad.rbac import usuario_actual
from ..servicios import auditoria, padron

bp = Blueprint("votantes", __name__, url_prefix="/votantes")

MAX_LOTE = 5000


@bp.post("")
def cargar():
    """Carga o actualiza el padrón: {"votantes": [{documentoInstitucional, correo}, ...]}"""
    u = usuario_actual()
    lista = leer_json().get("votantes")
    if not isinstance(lista, list) or not lista:
        raise payload_invalido("'votantes' debe ser una lista no vacía")
    if len(lista) > MAX_LOTE:
        raise payload_invalido(f"Máximo {MAX_LOTE} votantes por carga")

    validos, rechazados = [], []
    for i, fila in enumerate(lista, start=1):
        try:
            if not isinstance(fila, dict):
                raise payload_invalido("fila inválida")
            validos.append((padron.leer_documento(fila.get("documentoInstitucional")),
                            padron.leer_correo(fila.get("correo"))))
        except ErrorAPI as e:
            rechazados.append({"fila": i, "motivo": e.mensaje})

    creados = actualizados = 0
    with transaccion() as cur:
        for documento, correo in validos:
            if padron.guardar_votante(cur, documento, correo):
                creados += 1
            else:
                actualizados += 1
        auditoria.registrar(cur, "CARGAR_PADRON", u["sub"],
                            {"creados": creados, "actualizados": actualizados, "rechazados": len(rechazados)})
    return jsonify({"creados": creados, "actualizados": actualizados, "rechazados": rechazados})


@bp.get("/resumen")
def resumen():
    with transaccion() as cur:
        cur.execute("SELECT count(*) AS total, count(fecha_autorizacion_datos) AS autorizaron FROM votante")
        fila = cur.fetchone()
    return jsonify({"total": fila["total"], "conAutorizacionDatos": fila["autorizaron"]})


@bp.post("/suprimir")
def suprimir():
    """Elimina los datos personales de un votante (documento, correo, OTP).

    El voto NO se toca: está en el ledger sin ningún vínculo con la persona.
    No se permite mientras el votante tenga participación en una elección
    ABIERTA, porque podría volver a inscribirse y votar dos veces.
    """
    u = usuario_actual()
    documento = padron.leer_documento(leer_json().get("documentoInstitucional"))
    with transaccion() as cur:
        votante = padron.buscar_votante(cur, documento, bloquear=True)
        if not votante:
            raise ErrorAPI(404, "VOTANTE_NO_ENCONTRADO", "El documento no está en el padrón")
        cur.execute(
            "SELECT 1 FROM emision_token et JOIN eleccion e ON e.id = et.eleccion_id "
            "WHERE et.votante_id = %s AND e.estado = 'ABIERTA'",
            (votante["id"],),
        )
        if cur.fetchone():
            raise ErrorAPI(409, "SUPRESION_NO_PERMITIDA",
                           "El votante participó en una elección que sigue abierta; intente después del cierre")
        cur.execute("DELETE FROM votante WHERE id = %s", (votante["id"],))
        auditoria.registrar(cur, "SUPRIMIR_DATOS_VOTANTE", u["sub"],
                            {"referencia": padron.hash_documento(documento)[:12]})
    return jsonify({"mensaje": "Datos personales eliminados. Los votos emitidos se conservan de forma anónima."})
