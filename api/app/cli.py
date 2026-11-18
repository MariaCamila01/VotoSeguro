"""Comandos de administración:  flask --app wsgi <comando>

  inicializar   Espera la BD, crea las cuentas iniciales (admin y auditor) y,
                si SEMBRAR_DEMO=true, una elección y un padrón de prueba.
  purgar        Borra OTP vencidos, JWT revocados ya expirados y contadores
                de límite de tasa viejos (política de retención).
"""
import os
import time
from datetime import timedelta

import click
import psycopg

from . import db, esquema
from .seguridad.cripto import hash_password
from .servicios import auditoria, padron

ELECCION_DEMO = "Elección de Representante Estudiantil 2026"
OPCIONES_DEMO = [
    ("Lista 1 — Unidos por la UMB", "Bienestar estudiantil y más horarios de biblioteca."),
    ("Lista 2 — Campus Sostenible", "Reciclaje, movilidad en bicicleta y zonas verdes."),
    ("Lista 3 — Innovación Estudiantil", "Semilleros de investigación y laboratorios abiertos."),
    ("Voto en blanco", "Opción válida: ninguna de las anteriores."),
]


def _esperar_bd(intentos=30):
    for i in range(intentos):
        try:
            with db.transaccion() as cur:
                cur.execute("SELECT 1 FROM administrador LIMIT 1")
            return
        except psycopg.Error as e:
            click.echo(f"Esperando la base de datos ({i + 1}/{intentos}): {e.__class__.__name__}")
            time.sleep(2)
    raise click.ClickException("La base de datos no respondió")


def _asegurar_cuenta(cur, usuario, password, nombre, rol):
    if not usuario or not password:
        return None
    cur.execute("SELECT id FROM administrador WHERE usuario = %s", (usuario,))
    fila = cur.fetchone()
    if fila:
        return fila["id"]
    if len(password) < 10:
        raise click.ClickException(f"La contraseña de '{usuario}' debe tener al menos 10 caracteres")
    cur.execute(
        "INSERT INTO administrador (nombre, usuario, password_hash, rol) VALUES (%s, %s, %s, %s) RETURNING id",
        (nombre, usuario, hash_password(password), rol),
    )
    click.echo(f"Cuenta '{usuario}' ({rol}) creada")
    return cur.fetchone()["id"]


def _sembrar_demo(cur, admin_id):
    cur.execute("SELECT 1 FROM eleccion LIMIT 1")
    if cur.fetchone():
        return
    t = db.ahora()
    cur.execute(
        "INSERT INTO eleccion (nombre, fecha_inicio, fecha_fin, estado, admin_id) "
        "VALUES (%s, %s, %s, 'ABIERTA', %s) RETURNING id",
        (ELECCION_DEMO, t - timedelta(hours=1), t + timedelta(days=30), admin_id),
    )
    eid = cur.fetchone()["id"]
    for nombre, desc in OPCIONES_DEMO:
        cur.execute("INSERT INTO opcion_voto (eleccion_id, nombre, descripcion) VALUES (%s, %s, %s)",
                    (eid, nombre, desc))
    for i in range(1, 11):
        padron.guardar_votante(cur, f"UMB2026{i:03d}", f"estudiante{i:02d}@umb.edu.co")
    auditoria.registrar(cur, "SEMBRAR_DEMO", admin_id, {"eleccionId": str(eid), "votantes": 10})
    click.echo(f"Elección demo creada y ABIERTA: {eid} — padrón UMB2026001 … UMB2026010")


def registrar_comandos(app):
    @app.cli.command("inicializar")
    def inicializar():
        admin_url = os.getenv("DATABASE_ADMIN_URL")
        if admin_url:
            # Servicios administrados: no hay initdb, el esquema se crea aquí.
            for i in range(30):
                try:
                    esquema.aplicar_si_falta(admin_url, os.environ["APP_DB_USER"],
                                             os.environ["APP_DB_PASSWORD"], log=click.echo)
                    break
                except psycopg.OperationalError as e:
                    click.echo(f"Esperando la base de datos ({i + 1}/30): {e.__class__.__name__}")
                    time.sleep(2)
            else:
                raise click.ClickException("La base de datos no respondió")
        _esperar_bd()
        with db.transaccion() as cur:
            admin_id = _asegurar_cuenta(cur, os.getenv("ADMIN_USUARIO"), os.getenv("ADMIN_PASSWORD"),
                                        os.getenv("ADMIN_NOMBRE", "Administrador electoral"), "admin")
            _asegurar_cuenta(cur, os.getenv("AUDITOR_USUARIO"), os.getenv("AUDITOR_PASSWORD"),
                             os.getenv("AUDITOR_NOMBRE", "Auditor"), "auditor")
            if os.getenv("SEMBRAR_DEMO", "").lower() in ("1", "true", "si", "sí") and admin_id:
                _sembrar_demo(cur, admin_id)
        click.echo("Inicialización completa")

    @app.cli.command("purgar")
    def purgar():
        t = db.ahora()
        with db.transaccion() as cur:
            cur.execute("DELETE FROM codigo_otp WHERE fecha_expiracion < %s", (t - timedelta(days=1),))
            otp = cur.rowcount
            cur.execute("DELETE FROM jwt_revocado WHERE expira < %s", (t,))
            jwt = cur.rowcount
            cur.execute("DELETE FROM limite_tasa WHERE ts < %s", (t - timedelta(days=1),))
            tasa = cur.rowcount
            auditoria.registrar(cur, "PURGA_RETENCION", None, {"otp": otp, "jwt": jwt, "limiteTasa": tasa})
        click.echo(f"Purgados: {otp} OTP, {jwt} JWT revocados, {tasa} registros de límite de tasa")
