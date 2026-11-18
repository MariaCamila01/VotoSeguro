"""Consulta del RegistroAuditoria (solo lectura)."""
import json

from flask import Blueprint, jsonify, request

from ..db import iso, transaccion
from ..errores import ErrorAPI

bp = Blueprint("auditoria", __name__, url_prefix="/auditoria")


@bp.get("")
def listar():
    try:
        limite = min(max(int(request.args.get("limite", 100)), 1), 500)
    except ValueError:
        raise ErrorAPI(400, "PAYLOAD_INVALIDO", "'limite' debe ser un entero")
    accion = request.args.get("accion")
    sql = ("SELECT r.id, r.accion, r.detalle, r.timestamp_accion, a.usuario "
           "FROM registro_auditoria r LEFT JOIN administrador a ON a.id = r.admin_id ")
    params = []
    if accion:
        sql += "WHERE r.accion = %s "
        params.append(accion[:100])
    sql += "ORDER BY r.timestamp_accion DESC LIMIT %s"
    params.append(limite)
    with transaccion() as cur:
        cur.execute(sql, params)
        filas = cur.fetchall()

    def _detalle(texto):
        try:
            return json.loads(texto) if texto else None
        except ValueError:
            return texto

    return jsonify([{
        "id": str(f["id"]),
        "accion": f["accion"],
        "responsable": f["usuario"] or "sistema",
        "detalle": _detalle(f["detalle"]),
        "timestamp": iso(f["timestamp_accion"]),
    } for f in filas])
