"""Límite de tasa persistido en PostgreSQL.

Se guarda en la base de datos (y no en memoria) para que funcione igual con
varios procesos de Gunicorn o varias réplicas del contenedor de la API.
"""
from datetime import timedelta

from ..db import ahora
from ..errores import ErrorAPI


def _error_429(primero, ventana_min, mensaje):
    restante = int((primero + timedelta(minutes=ventana_min) - ahora()).total_seconds()) + 1
    restante = max(restante, 1)
    return ErrorAPI(429, "LIMITE_EXCEDIDO", mensaje,
                    extra={"reintentarEnSeg": restante},
                    cabeceras={"Retry-After": str(restante)})


def verificar(cur, clave, maximo, ventana_min, mensaje="Demasiados intentos. Intente más tarde."):
    desde = ahora() - timedelta(minutes=ventana_min)
    cur.execute(
        "SELECT count(*) AS n, min(ts) AS primero FROM limite_tasa WHERE clave = %s AND ts > %s",
        (clave, desde),
    )
    fila = cur.fetchone()
    if fila["n"] >= maximo:
        raise _error_429(fila["primero"], ventana_min, mensaje)


def registrar(cur, clave):
    cur.execute("INSERT INTO limite_tasa (clave, ts) VALUES (%s, %s)", (clave, ahora()))


def limpiar(cur, clave):
    cur.execute("DELETE FROM limite_tasa WHERE clave = %s", (clave,))


def error_429(primero, ventana_min, mensaje):
    return _error_429(primero, ventana_min, mensaje)
