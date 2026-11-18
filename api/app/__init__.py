"""VotoSeguro Bogotá — API REST (API Gateway / Controladores REST).

Cada módulo del diagrama de componentes es un Blueprint:
  Autenticación OTP ......... modulos/auth.py
  Tokens de un solo uso ..... modulos/votacion.py (registrar_voto_anonimo)
  Votación .................. modulos/votacion.py
  Ledger (hash-chain) ....... modulos/ledger.py + servicios/ledger.py
  Reportes y Auditoría ...... modulos/reportes.py, modulos/auditoria.py
"""
import logging

from flask import Blueprint, Flask, jsonify, request
from werkzeug.middleware.proxy_fix import ProxyFix

from . import db
from .config import Config
from .errores import registrar_manejadores
from .seguridad.rbac import verificar_acceso

PREFIJO = "/api/v1"


def create_app(config=None):
    cfg = config or Config()
    cfg.validar()

    app = Flask(__name__)
    app.config["APP"] = cfg
    app.config["JSON_AS_ASCII"] = False
    app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024
    app.json.ensure_ascii = False
    app.json.sort_keys = False
    logging.basicConfig(level=logging.INFO)

    # Detrás de proxies: confiar solo en los últimos N saltos de X-Forwarded-For
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=cfg.PROXY_SALTOS, x_proto=1)

    db.iniciar(cfg.DATABASE_URL)

    from .modulos import auditoria, auth, elecciones, ledger, reportes, votacion, votantes

    sistema = Blueprint("sistema", __name__)

    @sistema.get("/salud")
    def salud():
        with db.transaccion() as cur:
            cur.execute("SELECT 1")
        return jsonify({"estado": "ok", "servicio": "VotoSeguro Bogotá API", "version": "1.0"})

    api = Blueprint("api", __name__, url_prefix=PREFIJO)
    for bp in (sistema, auth.bp, votacion.bp, elecciones.bp, ledger.bp, reportes.bp, votantes.bp, auditoria.bp):
        api.register_blueprint(bp)
    app.register_blueprint(api)

    app.before_request(verificar_acceso)

    @app.after_request
    def _cabeceras(resp):
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        origen = request.headers.get("Origin")
        if origen and origen in cfg.CORS_ORIGENES:
            resp.headers["Access-Control-Allow-Origin"] = origen
            resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
            resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, OPTIONS"
            resp.headers["Vary"] = "Origin"
        return resp

    registrar_manejadores(app)

    from .cli import registrar_comandos
    registrar_comandos(app)
    return app
