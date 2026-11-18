"""3.5 Reportes — conteo agregado por opción + estado de integridad."""
from flask import Blueprint, jsonify

from ..db import iso, transaccion
from ..errores import ErrorAPI, leer_uuid
from ..seguridad.rbac import usuario_actual
from ..servicios import auditoria, ledger, padron

bp = Blueprint("reportes", __name__, url_prefix="/reportes")


@bp.get("/<eleccion_id>")
def reporte(eleccion_id):
    u = usuario_actual()
    eid = leer_uuid(eleccion_id, "eleccionId")
    with transaccion() as cur:
        e = padron.obtener_eleccion(cur, eid)
        # No se publican resultados parciales mientras se vota.
        if e["estado"] != "CERRADA":
            raise ErrorAPI(409, "RESULTADOS_NO_DISPONIBLES",
                           "Los resultados solo están disponibles cuando la elección está CERRADA")
        cur.execute(
            """
            SELECT o.id, o.nombre, count(v.id) AS votos
              FROM opcion_voto o
              LEFT JOIN voto v ON v.opcion_id = o.id
             WHERE o.eleccion_id = %s
             GROUP BY o.id, o.nombre
             ORDER BY votos DESC, o.nombre
            """,
            (eid,),
        )
        filas = cur.fetchall()
        integridad = ledger.verificar(cur, eid)
        auditoria.registrar(cur, "GENERAR_REPORTE", u["sub"],
                            {"eleccionId": eid, "integro": integridad["integro"]})

    total = sum(f["votos"] for f in filas)
    return jsonify({
        "eleccionId": eid,
        "nombre": e["nombre"],
        "estado": e["estado"],
        "fechaInicio": iso(e["fecha_inicio"]),
        "fechaFin": iso(e["fecha_fin"]),
        "totalVotos": total,
        "resultados": [{
            "opcionId": str(f["id"]),
            "nombre": f["nombre"],
            "votos": f["votos"],
            "porcentaje": round(100 * f["votos"] / total, 2) if total else 0.0,
        } for f in filas],
        "integridad": integridad,
    })
