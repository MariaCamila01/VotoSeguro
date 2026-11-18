"""3.3 Administración de elecciones (+ consulta de estado de la sección 3.2)."""
from flask import Blueprint, jsonify

from ..db import ahora, iso, transaccion
from ..errores import ErrorAPI, leer_fecha, leer_json, leer_texto, leer_uuid, payload_invalido
from ..seguridad.rbac import es_rol, usuario_actual
from ..servicios import auditoria, ledger, padron

bp = Blueprint("elecciones", __name__, url_prefix="/elecciones")

MIN_OPCIONES, MAX_OPCIONES = 2, 50


def _json(e):
    return {
        "id": str(e["id"]),
        "nombre": e["nombre"],
        "fechaInicio": iso(e["fecha_inicio"]),
        "fechaFin": iso(e["fecha_fin"]),
        "estado": e["estado"],
    }


def _leer_fechas(datos):
    inicio = leer_fecha(datos, "fechaInicio")
    fin = leer_fecha(datos, "fechaFin")
    if fin <= inicio:
        raise ErrorAPI(422, "FECHAS_INVALIDAS", "fechaFin debe ser posterior a fechaInicio")
    return inicio, fin


def _leer_opciones(datos):
    opciones = datos.get("opciones")
    if not isinstance(opciones, list):
        raise payload_invalido("'opciones' debe ser una lista")
    if not (MIN_OPCIONES <= len(opciones) <= MAX_OPCIONES):
        raise ErrorAPI(422, "OPCIONES_INVALIDAS", f"Defina entre {MIN_OPCIONES} y {MAX_OPCIONES} opciones")
    limpias, vistos = [], set()
    for o in opciones:
        if not isinstance(o, dict):
            raise payload_invalido("Cada opción debe ser un objeto {nombre, descripcion}")
        nombre = leer_texto(o, "nombre", 150)
        descripcion = leer_texto(o, "descripcion", 1000, obligatorio=False)
        if nombre.lower() in vistos:
            raise ErrorAPI(422, "OPCIONES_INVALIDAS", f"Opción repetida: {nombre}")
        vistos.add(nombre.lower())
        limpias.append((nombre, descripcion))
    return limpias


def _guardar_opciones(cur, eleccion_id, opciones):
    cur.execute("DELETE FROM opcion_voto WHERE eleccion_id = %s", (eleccion_id,))
    for nombre, descripcion in opciones:
        cur.execute("INSERT INTO opcion_voto (eleccion_id, nombre, descripcion) VALUES (%s, %s, %s)",
                    (eleccion_id, nombre, descripcion))


def _exigir_borrador(e):
    if e["estado"] != "BORRADOR":
        raise ErrorAPI(409, "ELECCION_NO_EDITABLE", "Solo se puede modificar una elección en BORRADOR")


@bp.get("")
def listar():
    with transaccion() as cur:
        if es_rol("admin", "auditor"):
            cur.execute("SELECT * FROM eleccion ORDER BY fecha_inicio DESC")
        else:
            cur.execute("SELECT * FROM eleccion WHERE estado = 'ABIERTA' AND fecha_fin > %s "
                        "ORDER BY fecha_fin", (ahora(),))
        return jsonify([_json(e) for e in cur.fetchall()])


@bp.post("")
def crear():
    u = usuario_actual()
    datos = leer_json()
    nombre = leer_texto(datos, "nombre", 150, min_len=3)
    inicio, fin = _leer_fechas(datos)
    opciones = _leer_opciones(datos) if "opciones" in datos else []
    with transaccion() as cur:
        cur.execute(
            "INSERT INTO eleccion (nombre, fecha_inicio, fecha_fin, admin_id) VALUES (%s, %s, %s, %s) RETURNING *",
            (nombre, inicio, fin, u["sub"]),
        )
        e = cur.fetchone()
        if opciones:
            _guardar_opciones(cur, e["id"], opciones)
        auditoria.registrar(cur, "CREAR_ELECCION", u["sub"], {"eleccionId": str(e["id"]), "nombre": nombre})
    return jsonify(_json(e)), 201


@bp.get("/<eleccion_id>")
def detalle(eleccion_id):
    eid = leer_uuid(eleccion_id, "id")
    with transaccion() as cur:
        e = padron.obtener_eleccion(cur, eid)
        cur.execute("SELECT id, nombre, descripcion FROM opcion_voto WHERE eleccion_id = %s ORDER BY nombre",
                    (eid,))
        opciones = [{"id": str(o["id"]), "nombre": o["nombre"], "descripcion": o["descripcion"]}
                    for o in cur.fetchall()]
        cur.execute("SELECT count(*) AS n FROM bloque_ledger WHERE eleccion_id = %s", (eid,))
        total = cur.fetchone()["n"]
    return jsonify({**_json(e), "opciones": opciones, "totalVotosEmitidos": total})


@bp.put("/<eleccion_id>")
def actualizar(eleccion_id):
    u = usuario_actual()
    eid = leer_uuid(eleccion_id, "id")
    datos = leer_json()
    nombre = leer_texto(datos, "nombre", 150, min_len=3)
    inicio, fin = _leer_fechas(datos)
    with transaccion() as cur:
        _exigir_borrador(padron.obtener_eleccion(cur, eid, bloquear=True))
        cur.execute("UPDATE eleccion SET nombre = %s, fecha_inicio = %s, fecha_fin = %s WHERE id = %s RETURNING *",
                    (nombre, inicio, fin, eid))
        e = cur.fetchone()
        auditoria.registrar(cur, "EDITAR_ELECCION", u["sub"], {"eleccionId": eid})
    return jsonify(_json(e))


@bp.put("/<eleccion_id>/opciones")
def definir_opciones(eleccion_id):
    u = usuario_actual()
    eid = leer_uuid(eleccion_id, "id")
    opciones = _leer_opciones(leer_json())
    with transaccion() as cur:
        _exigir_borrador(padron.obtener_eleccion(cur, eid, bloquear=True))
        _guardar_opciones(cur, eid, opciones)
        auditoria.registrar(cur, "DEFINIR_OPCIONES", u["sub"], {"eleccionId": eid, "total": len(opciones)})
    return listar_opciones(eleccion_id)


@bp.get("/<eleccion_id>/opciones")
def listar_opciones(eleccion_id):
    eid = leer_uuid(eleccion_id, "id")
    with transaccion() as cur:
        e = padron.obtener_eleccion(cur, eid)
        if e["estado"] == "BORRADOR" and not es_rol("admin", "auditor"):
            raise ErrorAPI(404, "ELECCION_NO_ENCONTRADA", "La elección no existe")
        cur.execute("SELECT id, nombre, descripcion FROM opcion_voto WHERE eleccion_id = %s ORDER BY nombre",
                    (eid,))
        return jsonify([{"id": str(o["id"]), "nombre": o["nombre"], "descripcion": o["descripcion"]}
                        for o in cur.fetchall()])


@bp.post("/<eleccion_id>/abrir")
def abrir(eleccion_id):
    u = usuario_actual()
    eid = leer_uuid(eleccion_id, "id")
    with transaccion() as cur:
        e = padron.obtener_eleccion(cur, eid, bloquear=True)
        if e["estado"] != "BORRADOR":
            raise ErrorAPI(409, "TRANSICION_INVALIDA", f"No se puede abrir una elección {e['estado']}")
        cur.execute("SELECT count(*) AS n FROM opcion_voto WHERE eleccion_id = %s", (eid,))
        if cur.fetchone()["n"] < MIN_OPCIONES:
            raise ErrorAPI(422, "OPCIONES_INSUFICIENTES", f"Defina al menos {MIN_OPCIONES} opciones antes de abrir")
        if e["fecha_fin"] <= ahora():
            raise ErrorAPI(422, "FECHAS_INVALIDAS", "La fecha de fin ya pasó; edite las fechas antes de abrir")
        cur.execute("UPDATE eleccion SET estado = 'ABIERTA' WHERE id = %s RETURNING *", (eid,))
        e = cur.fetchone()
        auditoria.registrar(cur, "ABRIR_ELECCION", u["sub"], {"eleccionId": eid})
    return jsonify(_json(e))


@bp.post("/<eleccion_id>/cerrar")
def cerrar(eleccion_id):
    """Al cerrar se dispara la verificación de integridad del ledger y se
    guarda un 'ancla' (hash final + total de bloques) en la auditoría."""
    u = usuario_actual()
    eid = leer_uuid(eleccion_id, "id")
    with transaccion() as cur:
        e = padron.obtener_eleccion(cur, eid, bloquear=True)
        if e["estado"] != "ABIERTA":
            raise ErrorAPI(409, "TRANSICION_INVALIDA", f"No se puede cerrar una elección {e['estado']}")
        cur.execute("UPDATE eleccion SET estado = 'CERRADA' WHERE id = %s RETURNING *", (eid,))
        e = cur.fetchone()
        verificacion = ledger.verificar(cur, eid)
        auditoria.registrar(cur, "CERRAR_ELECCION", u["sub"],
                            {"eleccionId": eid, "integro": verificacion["integro"],
                             "totalBloques": verificacion["totalBloques"]})
        auditoria.registrar(cur, "ANCLA_LEDGER", u["sub"],
                            {"eleccionId": eid, "hashFinal": verificacion["hashFinal"],
                             "totalBloques": verificacion["totalBloques"]})
        if not verificacion["integro"]:
            auditoria.registrar(cur, "INTEGRIDAD_COMPROMETIDA", None,
                                {"eleccionId": eid, "indiceFalla": verificacion["indiceFalla"],
                                 "motivo": verificacion["motivo"]})
    return jsonify({**_json(e), "verificacion": verificacion})


@bp.get("/<eleccion_id>/estado")
def estado(eleccion_id):
    eid = leer_uuid(eleccion_id, "id")
    u = usuario_actual()
    with transaccion() as cur:
        e = padron.obtener_eleccion(cur, eid)
        cur.execute("SELECT count(*) AS n FROM bloque_ledger WHERE eleccion_id = %s", (eid,))
        total = cur.fetchone()["n"]
        respuesta = {
            "estado": e["estado"],
            "nombre": e["nombre"],
            "totalVotosEmitidos": total,
            "fechaInicio": iso(e["fecha_inicio"]),
            "fechaFin": iso(e["fecha_fin"]),
        }
        if u["role"] == "votante":
            respuesta["yaVoto"] = padron.ya_voto(cur, u["sub"], eid)
    return jsonify(respuesta)
