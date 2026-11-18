"""Acceso a PostgreSQL con un pool de conexiones (psycopg 3)."""
import atexit
from contextlib import contextmanager
from datetime import datetime, timezone

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

_pool = None


def iniciar(dsn):
    global _pool
    if _pool is not None:
        return
    _pool = ConnectionPool(
        dsn,
        min_size=1,
        max_size=10,
        kwargs={"row_factory": dict_row, "options": "-c timezone=UTC"},
        open=True,
    )
    atexit.register(cerrar)


def cerrar():
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def transaccion():
    """Abre una transacción: commit si el bloque termina bien, rollback si lanza excepción."""
    with _pool.connection() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                yield cur


def ahora():
    """Fecha/hora actual en UTC sin zona (las columnas son TIMESTAMP en UTC)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso(dt):
    """Formato ISO 8601 con Z para respuestas JSON."""
    if dt is None:
        return None
    if hasattr(dt, "hour"):
        return dt.replace(tzinfo=None).isoformat(timespec="seconds") + "Z"
    return dt.isoformat()
