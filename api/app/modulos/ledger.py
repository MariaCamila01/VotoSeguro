"""3.4 Ledger y auditoría."""
from flask import Blueprint, jsonify, request

from ..db import iso, transaccion
from ..errores import ErrorAPI, leer_uuid
from ..seguridad.rbac import usuario_actual
from ..servicios import auditoria, ledger, padron

bp = Blueprint("ledger", __name__, url_prefix="/ledger")


@bp.get("/<eleccion_id>/verificar")
def verificar(eleccion_id):
    u = usuario_actual()
    eid = leer_uuid(eleccion_id, "eleccionId")
    with transaccion() as cur:
        padron.obtener_eleccion(cur, eid)
        resultado = ledger.verificar(cur, eid)
        auditoria.registrar(cur, "VERIFICAR_LEDGER", u["sub"],
                            {"eleccionId": eid, "integro": resultado["integro"],
                             "totalBloques": resultado["totalBloques"]})
        if not resultado["integro"]:
            auditoria.registrar(cur, "INTEGRIDAD_COMPROMETIDA", None,
                                {"eleccionId": eid, "indiceFalla": resultado["indiceFalla"],
                                 "motivo": resultado["motivo"]})
    return jsonify(resultado)


@bp.get("/<eleccion_id>/cadena")
def cadena(eleccion_id):
    """Cadena completa de hashes. Sin datos de identidad ni la opción votada."""
    eid = leer_uuid(eleccion_id, "eleccionId")
    try:
        desde = max(int(request.args.get("desde", 0)), 0)
        limite = min(max(int(request.args.get("limite", 500)), 1), 1000)
    except ValueError:
        raise ErrorAPI(400, "PAYLOAD_INVALIDO", "'desde' y 'limite' deben ser enteros")
    with transaccion() as cur:
        padron.obtener_eleccion(cur, eid)
        cur.execute(
            "SELECT b.indice, b.hash_anterior, b.hash_actual, b.timestamp_bloque, v.hash_voto "
            "FROM bloque_ledger b JOIN voto v ON v.id = b.voto_id "
            "WHERE b.eleccion_id = %s AND b.indice >= %s ORDER BY b.indice LIMIT %s",
            (eid, desde, limite),
        )
        bloques = [{
            "indice": b["indice"],
            "hashAnterior": b["hash_anterior"],
            "hashActual": b["hash_actual"],
            "hashVoto": b["hash_voto"],
            "timestamp": iso(b["timestamp_bloque"]),
        } for b in cur.fetchall()]
        cur.execute("SELECT count(*) AS n FROM bloque_ledger WHERE eleccion_id = %s", (eid,))
        total = cur.fetchone()["n"]
    return jsonify({"eleccionId": eid, "totalBloques": total, "desde": desde, "bloques": bloques})


@bp.get("/comprobante/<confirmacion>")
def comprobante(confirmacion):
    """El votante comprueba que su voto está en la cadena con el número de
    confirmación que recibió. No revela por quién votó."""
    cid = leer_uuid(confirmacion, "confirmacion")
    with transaccion() as cur:
        cur.execute(
            "SELECT b.eleccion_id, b.indice, b.hash_actual, b.timestamp_bloque, e.nombre "
            "FROM bloque_ledger b JOIN eleccion e ON e.id = b.eleccion_id WHERE b.id = %s",
            (cid,),
        )
        b = cur.fetchone()
    if not b:
        raise ErrorAPI(404, "COMPROBANTE_NO_ENCONTRADO", "No hay ningún voto con esa confirmación")
    return jsonify({
        "encontrado": True,
        "eleccionId": str(b["eleccion_id"]),
        "eleccion": b["nombre"],
        "indiceBloque": b["indice"],
        "hashBloque": b["hash_actual"],
        "timestamp": iso(b["timestamp_bloque"]),
    })
