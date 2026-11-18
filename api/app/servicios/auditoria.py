"""RegistroAuditoria: toda acción administrativa queda registrada.

Nunca se registra el contenido de un voto ni datos personales del votante.
"""
import json

from ..db import ahora


def registrar(cur, accion, admin_id=None, detalle=None):
    if isinstance(detalle, (dict, list)):
        detalle = json.dumps(detalle, ensure_ascii=False, sort_keys=True)
    cur.execute(
        "INSERT INTO registro_auditoria (admin_id, accion, detalle, timestamp_accion) "
        "VALUES (%s, %s, %s, %s)",
        (admin_id, accion, detalle, ahora()),
    )
