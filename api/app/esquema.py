"""Creación del esquema cuando la base de datos no lo trae.

Con docker-compose el esquema lo crea PostgreSQL al iniciar (db/initdb). En
servicios administrados (Railway, Render…) no hay initdb, así que
`flask --app wsgi inicializar` lo aplica con una conexión de superusuario
(DATABASE_ADMIN_URL) y crea el rol limitado que usa la API. La fuente es la
misma: db/initdb/01_schema.sql y el SQL de db/initdb/02_rol_aplicacion.sh.
"""
import os
import pathlib
import re

import psycopg


def _directorio():
    candidatos = [
        os.getenv("ESQUEMA_DIR"),
        "/app/db/initdb",
        pathlib.Path(__file__).resolve().parents[2] / "db" / "initdb",
    ]
    for c in candidatos:
        if c and (pathlib.Path(c) / "01_schema.sql").exists():
            return pathlib.Path(c)
    raise FileNotFoundError("No se encontró db/initdb/01_schema.sql")


def _literal(texto):
    return "'" + texto.replace("'", "''") + "'"


def _ident(texto):
    return '"' + texto.replace('"', '""') + '"'


def sql_schema():
    return (_directorio() / "01_schema.sql").read_text(encoding="utf-8")


def sql_roles(app_user, app_pass, dbname, crear_rol=True):
    texto = (_directorio() / "02_rol_aplicacion.sh").read_text(encoding="utf-8")
    sql = re.search(r"<<'SQL'\n(.*?)\nSQL", texto, re.S).group(1)
    if not crear_rol:
        sql = sql.replace('CREATE ROLE :"app_user" LOGIN PASSWORD', 'ALTER ROLE :"app_user" LOGIN PASSWORD')
    return (sql.replace(':"app_user"', _ident(app_user))
               .replace(":'app_pass'", _literal(app_pass))
               .replace(':"DBNAME"', _ident(dbname)))


def aplicar_si_falta(admin_url, app_user, app_pass, log=print):
    """Devuelve True si creó el esquema, False si ya existía."""
    with psycopg.connect(admin_url, autocommit=True) as c:
        existe = c.execute("SELECT to_regclass('public.administrador') IS NOT NULL").fetchone()[0]
        rol_existe = c.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (app_user,)).fetchone()
        dbname = c.execute("SELECT current_database()").fetchone()[0]
        if not existe:
            log("Creando el esquema de la base de datos…")
            c.execute(sql_schema())
        # Siempre se re-aplican rol y permisos: así la contraseña del rol
        # sigue a la variable de entorno si se cambia.
        c.execute(sql_roles(app_user, app_pass, dbname, crear_rol=not rol_existe))
        return not existe
