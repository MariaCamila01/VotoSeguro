"""Consultas comunes sobre elecciones y el padrón de votantes."""
import re

from flask import current_app

from ..db import ahora
from ..errores import ErrorAPI, payload_invalido
from ..seguridad.cripto import hmac_hex, normalizar_documento

_RE_DOCUMENTO = re.compile(r"^[A-Z0-9-]{4,20}$")
_RE_CORREO = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")


def _clave():
    return current_app.config["APP"].CLAVE_CIFRADO_DATOS


# ---------------------------------------------------------------- elecciones
def obtener_eleccion(cur, eleccion_id, bloquear=False):
    sql = "SELECT * FROM eleccion WHERE id = %s" + (" FOR UPDATE" if bloquear else "")
    cur.execute(sql, (eleccion_id,))
    e = cur.fetchone()
    if not e:
        raise ErrorAPI(404, "ELECCION_NO_ENCONTRADA", "La elección no existe")
    return e


def exigir_en_votacion(e):
    """La elección debe estar ABIERTA y dentro de su rango de fechas."""
    if e["estado"] == "CERRADA":
        raise ErrorAPI(409, "ELECCION_CERRADA", "La elección ya está cerrada")
    if e["estado"] != "ABIERTA":
        raise ErrorAPI(409, "ELECCION_NO_ABIERTA", "La elección todavía no está abierta")
    t = ahora()
    if t < e["fecha_inicio"]:
        raise ErrorAPI(409, "ELECCION_NO_INICIADA", "La votación aún no ha comenzado")
    if t >= e["fecha_fin"]:
        raise ErrorAPI(409, "ELECCION_FINALIZADA", "El horario de votación terminó")


# ------------------------------------------------------------------- votantes
def leer_documento(valor, campo="documentoInstitucional"):
    if not isinstance(valor, (str, int)):
        raise payload_invalido(f"'{campo}' es obligatorio")
    doc = normalizar_documento(str(valor))
    if not _RE_DOCUMENTO.match(doc):
        raise payload_invalido(f"'{campo}' debe tener entre 4 y 20 letras, números o guiones")
    return doc


def leer_correo(valor):
    if not isinstance(valor, str) or not _RE_CORREO.match(valor.strip()) or len(valor.strip()) > 150:
        raise payload_invalido("Correo inválido")
    return valor.strip().lower()


def hash_documento(documento):
    return hmac_hex("doc:" + documento)


def buscar_votante(cur, documento, bloquear=False):
    sql = ("SELECT id, pgp_sym_decrypt(correo_cifrado, %s) AS correo "
           "FROM votante WHERE documento_hash = %s" + (" FOR UPDATE" if bloquear else ""))
    cur.execute(sql, (_clave(), hash_documento(documento)))
    return cur.fetchone()


def ya_voto(cur, votante_id, eleccion_id):
    cur.execute(
        "SELECT 1 FROM emision_token WHERE votante_id = %s AND eleccion_id = %s",
        (votante_id, eleccion_id),
    )
    return cur.fetchone() is not None


def guardar_votante(cur, documento, correo):
    """Inserta o actualiza (por documento). Devuelve True si fue creado."""
    cur.execute(
        """
        INSERT INTO votante (documento_hash, documento_cifrado, correo_cifrado)
        VALUES (%(h)s, pgp_sym_encrypt(%(d)s, %(k)s), pgp_sym_encrypt(%(c)s, %(k)s))
        ON CONFLICT (documento_hash)
        DO UPDATE SET correo_cifrado = EXCLUDED.correo_cifrado
        RETURNING (xmax = 0) AS creado
        """,
        {"h": hash_documento(documento), "d": documento, "c": correo, "k": _clave()},
    )
    return cur.fetchone()["creado"]
