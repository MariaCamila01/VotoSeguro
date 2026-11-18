"""Pruebas de integración contra un PostgreSQL real.

Necesita un PostgreSQL 16 con un superusuario. Ejemplo con Docker:

  docker run -d --name pg-pruebas -p 5433:5432 \
      -e POSTGRES_USER=votoseguro_admin -e POSTGRES_PASSWORD=pruebas postgres:16-alpine
  PGPORT=5433 PGPASSWORD=pruebas pytest

Variables: TEST_DB_HOST (localhost), TEST_DB_SUPERUSER (votoseguro_admin) y las
estándar de PostgreSQL (PGPORT, PGPASSWORD).
"""
import os
from datetime import timedelta

import psycopg
import pytest
from psycopg.rows import dict_row


HOST = os.getenv("TEST_DB_HOST", "localhost")
SUPER = os.getenv("TEST_DB_SUPERUSER", "votoseguro_admin")
DB = "votoseguro_test"
APP_USER = "votoseguro_app_test"
APP_PASS = "clave_app_pruebas_123"

ADMIN_URL = f"postgresql://{SUPER}@/{DB}?host={HOST}"
APP_URL = f"postgresql://{APP_USER}:{APP_PASS}@/{DB}?host={HOST}"

SECRETOS = {
    "JWT_SECRET": "pruebas-jwt-secreto-de-al-menos-32-caracteres",
    "CLAVE_HMAC": "pruebas-hmac-secreto-de-al-menos-32-caracteres",
    "CLAVE_CIFRADO_DATOS": "pruebas-cifrado-de-al-menos-32-caracteres!!",
}


def _crear_bd():
    with psycopg.connect(f"postgresql://{SUPER}@/postgres?host={HOST}", autocommit=True) as c:
        c.execute(f"DROP DATABASE IF EXISTS {DB}")
        c.execute(f"DROP ROLE IF EXISTS {APP_USER}")
        c.execute(f"CREATE DATABASE {DB}")
    from app import esquema
    assert esquema.aplicar_si_falta(ADMIN_URL, APP_USER, APP_PASS, log=lambda *_: None) is True
    # Segunda vez: no rehace el esquema, solo reaplica el rol (idempotente)
    assert esquema.aplicar_si_falta(ADMIN_URL, APP_USER, APP_PASS, log=lambda *_: None) is False


@pytest.fixture(scope="session")
def app():
    _crear_bd()
    from app import create_app
    from app.config import Config
    cfg = Config({**SECRETOS, "DATABASE_URL": APP_URL, "TESTING": "true", "ENTORNO": "pruebas"})
    aplicacion = create_app(cfg)
    yield aplicacion
    from app import db
    db.cerrar()


@pytest.fixture()
def bd():
    """Conexión de SUPERUSUARIO: simula a un atacante con acceso total a la BD."""
    with psycopg.connect(ADMIN_URL, autocommit=True, row_factory=dict_row) as c:
        yield c


@pytest.fixture(autouse=True)
def limpiar(app, bd):
    bd.execute("TRUNCATE administrador, votante, eleccion, opcion_voto, codigo_otp, token_voto, "
               "emision_token, voto, bloque_ledger, registro_auditoria, jwt_revocado, limite_tasa CASCADE")
    app.config["OTP_ENVIADOS"] = []
    yield


_HASHES = {}


def _hash(pw):
    if pw not in _HASHES:
        import bcrypt
        _HASHES[pw] = bcrypt.hashpw(pw.encode(), bcrypt.gensalt(rounds=4)).decode()
    return _HASHES[pw]


@pytest.fixture()
def cuentas(bd):
    ids = {}
    for usuario, rol in (("admin", "admin"), ("auditor", "auditor")):
        fila = bd.execute(
            "INSERT INTO administrador (nombre, usuario, password_hash, rol) VALUES (%s,%s,%s,%s) RETURNING id",
            (usuario.title(), usuario, _hash("Clave-segura-123"), rol),
        ).fetchone()
        ids[usuario] = str(fila["id"])
    return ids


class Cliente:
    def __init__(self, app):
        self.app = app
        self.http = app.test_client()
        self.ip = "10.0.0.1"

    def _req(self, metodo, ruta, token=None, json=None, ip=None):
        cab = {"Authorization": f"Bearer {token}"} if token else {}
        r = self.http.open("/api/v1" + ruta, method=metodo, json=json, headers=cab,
                           environ_base={"REMOTE_ADDR": ip or self.ip})
        return r

    def get(self, ruta, token=None, **kw):
        return self._req("GET", ruta, token, **kw)

    def post(self, ruta, json=None, token=None, **kw):
        return self._req("POST", ruta, token, json=json if json is not None else {}, **kw)

    def put(self, ruta, json=None, token=None, **kw):
        return self._req("PUT", ruta, token, json=json, **kw)

    # ---- atajos
    def login(self, usuario="admin", password="Clave-segura-123"):
        r = self.post("/auth/admin/login", {"usuario": usuario, "password": password})
        assert r.status_code == 200, r.get_json()
        return r.get_json()["token"]

    def ultimo_otp(self):
        return self.app.config["OTP_ENVIADOS"][-1][1]

    def jwt_votante(self, documento, eleccion_id):
        r = self.post("/auth/otp/solicitar", {"documentoInstitucional": documento, "eleccionId": eleccion_id,
                                               "aceptaTratamientoDatos": True})
        assert r.status_code == 200, r.get_json()
        r = self.post("/auth/otp/verificar", {"documentoInstitucional": documento, "eleccionId": eleccion_id,
                                               "codigoOTP": self.ultimo_otp()})
        assert r.status_code == 200, r.get_json()
        return r.get_json()["token"]

    def votar(self, documento, eleccion_id, opcion_id):
        token = self.jwt_votante(documento, eleccion_id)
        return self.post("/votos", {"opcionId": opcion_id}, token=token)


@pytest.fixture()
def cliente(app):
    return Cliente(app)


@pytest.fixture()
def eleccion(cliente, cuentas):
    """Elección ABIERTA con 3 opciones y un padrón de 12 votantes."""
    admin = cliente.login()
    from app.db import ahora
    t = ahora()
    r = cliente.post("/elecciones", {
        "nombre": "Consejo Estudiantil 2026",
        "fechaInicio": (t - timedelta(hours=1)).isoformat() + "Z",
        "fechaFin": (t + timedelta(days=1)).isoformat() + "Z",
        "opciones": [{"nombre": "Lista A"}, {"nombre": "Lista B"}, {"nombre": "Voto en blanco"}],
    }, token=admin)
    assert r.status_code == 201, r.get_json()
    eid = r.get_json()["id"]
    votantes = [{"documentoInstitucional": f"EST{i:04d}", "correo": f"est{i}@umb.edu.co"} for i in range(1, 13)]
    assert cliente.post("/votantes", {"votantes": votantes}, token=admin).status_code == 200
    assert cliente.post(f"/elecciones/{eid}/abrir", token=admin).status_code == 200
    opciones = {o["nombre"]: o["id"] for o in cliente.get(f"/elecciones/{eid}/opciones").get_json()}
    return {"id": eid, "opciones": opciones, "admin": admin}
