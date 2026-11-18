"""Errores de la API con el código HTTP de la sección 4 del documento."""
import uuid
from datetime import datetime, timezone

from flask import jsonify, request
from werkzeug.exceptions import HTTPException


class ErrorAPI(Exception):
    def __init__(self, status, codigo, mensaje, extra=None, cabeceras=None):
        super().__init__(mensaje)
        self.status = status
        self.codigo = codigo
        self.mensaje = mensaje
        self.extra = extra or {}
        self.cabeceras = cabeceras or {}


def payload_invalido(mensaje):
    return ErrorAPI(400, "PAYLOAD_INVALIDO", mensaje)


def leer_json():
    datos = request.get_json(silent=True)
    if not isinstance(datos, dict):
        raise payload_invalido("El cuerpo debe ser un objeto JSON")
    return datos


def leer_uuid(valor, campo):
    try:
        return str(uuid.UUID(str(valor)))
    except (ValueError, TypeError, AttributeError):
        raise payload_invalido(f"'{campo}' debe ser un UUID válido")


def leer_texto(datos, campo, max_len, min_len=1, obligatorio=True):
    valor = datos.get(campo)
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        if obligatorio:
            raise payload_invalido(f"'{campo}' es obligatorio")
        return None
    if not isinstance(valor, str):
        raise payload_invalido(f"'{campo}' debe ser texto")
    valor = valor.strip()
    if not (min_len <= len(valor) <= max_len):
        raise payload_invalido(f"'{campo}' debe tener entre {min_len} y {max_len} caracteres")
    return valor


def leer_fecha(datos, campo):
    valor = datos.get(campo)
    if not isinstance(valor, str):
        raise payload_invalido(f"'{campo}' es obligatorio (ISO 8601)")
    try:
        dt = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError:
        raise payload_invalido(f"'{campo}' no es una fecha ISO 8601 válida")
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def registrar_manejadores(app):
    @app.errorhandler(ErrorAPI)
    def _error_api(e):
        cuerpo = {"error": {"codigo": e.codigo, "mensaje": e.mensaje, **e.extra}}
        resp = jsonify(cuerpo)
        resp.status_code = e.status
        for k, v in e.cabeceras.items():
            resp.headers[k] = v
        return resp

    @app.errorhandler(404)
    def _no_encontrado(_):
        return jsonify({"error": {"codigo": "NO_ENCONTRADO", "mensaje": "Ruta no encontrada"}}), 404

    @app.errorhandler(405)
    def _metodo(_):
        return jsonify({"error": {"codigo": "METODO_NO_PERMITIDO", "mensaje": "Método no permitido"}}), 405

    @app.errorhandler(Exception)
    def _interno(e):
        if isinstance(e, HTTPException):
            return jsonify({"error": {"codigo": "HTTP_" + str(e.code), "mensaje": e.description}}), e.code
        app.logger.exception("Error interno")
        return jsonify({"error": {"codigo": "ERROR_INTERNO", "mensaje": "Error interno del servidor"}}), 500
