"""Autorización por rol (RBAC) — sección 2.3 del documento.

Un middleware revisa, en cada petición, el claim `role` del JWT contra la
tabla de permisos por endpoint. Cualquier endpoint que no esté en la tabla
queda DENEGADO por defecto (así una ruta nueva olvidada no queda abierta).
"""
import jwt as pyjwt
from flask import g, request

from ..db import transaccion
from ..errores import ErrorAPI
from . import jwt_utils

PUBLICO = "publico"      # no requiere token
OPCIONAL = "opcional"    # funciona sin token; si llega uno válido se usa

VOTANTE, ADMIN, AUDITOR = "votante", "admin", "auditor"

# endpoint de Flask  →  roles permitidos
PERMISOS = {
    "sistema.salud":                PUBLICO,

    # 3.1 Autenticación
    "auth.solicitar_otp":           PUBLICO,
    "auth.verificar_otp":           PUBLICO,
    "auth.login_admin":             PUBLICO,
    "auth.logout":                  {VOTANTE, ADMIN, AUDITOR},

    # 3.2 Votación
    "votacion.emitir_voto":         {VOTANTE},
    "elecciones.estado":            {VOTANTE, ADMIN, AUDITOR},

    # 3.3 Administración de elecciones
    "elecciones.listar":            OPCIONAL,
    "elecciones.listar_opciones":   OPCIONAL,
    "elecciones.detalle":           {ADMIN, AUDITOR},
    "elecciones.crear":             {ADMIN},
    "elecciones.actualizar":        {ADMIN},
    "elecciones.definir_opciones":  {ADMIN},
    "elecciones.abrir":             {ADMIN},
    "elecciones.cerrar":            {ADMIN},

    # 3.4 Ledger y auditoría
    "ledger.verificar":             {ADMIN, AUDITOR},
    "ledger.cadena":                {AUDITOR},
    "ledger.comprobante":           PUBLICO,
    "auditoria.listar":             {ADMIN, AUDITOR},

    # 3.5 Reportes
    "reportes.reporte":             {ADMIN},

    # Padrón institucional y habeas data
    "votantes.cargar":              {ADMIN},
    "votantes.resumen":             {ADMIN},
    "votantes.suprimir":            {ADMIN},
}


def _extraer_token():
    cabecera = request.headers.get("Authorization", "")
    if cabecera.startswith("Bearer "):
        return cabecera[7:].strip() or None
    return None


def _validar(token, endpoint):
    try:
        claims = jwt_utils.decodificar(token)
    except pyjwt.ExpiredSignatureError:
        raise ErrorAPI(401, "TOKEN_EXPIRADO", "La sesión expiró. Inicie de nuevo.")
    except pyjwt.InvalidTokenError:
        raise ErrorAPI(401, "TOKEN_INVALIDO", "Token inválido")

    rol = claims.get("role")
    if rol not in (VOTANTE, ADMIN, AUDITOR):
        raise ErrorAPI(401, "TOKEN_INVALIDO", "Token inválido")
    if rol == VOTANTE and not claims.get("eleccionId"):
        raise ErrorAPI(401, "TOKEN_INVALIDO", "Token inválido")

    with transaccion() as cur:
        cur.execute("SELECT motivo FROM jwt_revocado WHERE jti = %s", (claims["jti"],))
        revocado = cur.fetchone()
        if rol in (ADMIN, AUDITOR):
            # El rol se toma de la BD, no solo del token: si se cambia o se
            # elimina la cuenta, el cambio aplica de inmediato.
            cur.execute("SELECT rol, nombre FROM administrador WHERE id = %s", (claims["sub"],))
            cuenta = cur.fetchone()
            if not cuenta:
                raise ErrorAPI(401, "TOKEN_INVALIDO", "La cuenta ya no existe")
            claims["role"] = cuenta["rol"]
            claims["nombre"] = cuenta["nombre"]

    if revocado:
        if revocado["motivo"] == "CONSUMIDO":
            # El JWT de votante autoriza UNA llamada a POST /votos. Después
            # solo sirve para consultas de lectura hasta que expire.
            if endpoint == "votacion.emitir_voto":
                raise ErrorAPI(409, "TOKEN_YA_USADO", "Este token ya se usó para votar")
        else:
            raise ErrorAPI(401, "TOKEN_REVOCADO", "La sesión fue cerrada")
    return claims


def verificar_acceso():
    g.usuario = None
    if request.method == "OPTIONS":
        return
    endpoint = request.endpoint
    if endpoint is None:          # ruta inexistente: Flask responde 404
        return
    # Los blueprints cuelgan de "api" (/api/v1): "api.auth.solicitar_otp" → "auth.solicitar_otp"
    if endpoint.startswith("api."):
        endpoint = endpoint[4:]

    regla = PERMISOS.get(endpoint)
    if regla is None:
        raise ErrorAPI(403, "SIN_PERMISO", "Acceso denegado")

    token = _extraer_token()
    if regla == PUBLICO:
        return
    if regla == OPCIONAL:
        if token:
            try:
                g.usuario = _validar(token, endpoint)
            except ErrorAPI:
                g.usuario = None
        return

    if not token:
        raise ErrorAPI(401, "NO_AUTENTICADO", "Se requiere autenticación (Authorization: Bearer <token>)")
    claims = _validar(token, endpoint)
    if claims["role"] not in regla:
        raise ErrorAPI(403, "SIN_PERMISO", "Su rol no tiene permiso para esta acción")
    g.usuario = claims


def usuario_actual():
    return g.get("usuario")


def es_rol(*roles):
    u = usuario_actual()
    return bool(u) and u["role"] in roles
