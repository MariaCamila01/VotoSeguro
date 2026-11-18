"""3.1 Autenticación — OTP para votantes, usuario/contraseña para administradores."""
import re
from datetime import datetime, timedelta, timezone

from flask import Blueprint, current_app, jsonify, request

from ..db import ahora, transaccion
from ..errores import ErrorAPI, leer_json, leer_texto, leer_uuid, payload_invalido
from ..seguridad import jwt_utils, limite_tasa
from ..seguridad.cripto import (comparar_seguro, enmascarar_correo, generar_otp, hmac_hex,
                                verificar_password)
from ..seguridad.rbac import usuario_actual
from ..servicios import auditoria, padron
from ..servicios.correo import ErrorCorreo, enviar_otp

bp = Blueprint("auth", __name__, url_prefix="/auth")

_RE_OTP = re.compile(r"^\d{6}$")


def _cfg():
    return current_app.config["APP"]


def _hash_otp(votante_id, eleccion_id, codigo):
    # El código queda ligado al votante y a la elección: el mismo número en
    # otra fila produce otro hash.
    return hmac_hex(f"otp:{votante_id}:{eleccion_id}:{codigo}")


@bp.post("/otp/solicitar")
def solicitar_otp():
    cfg = _cfg()
    datos = leer_json()
    documento = padron.leer_documento(datos.get("documentoInstitucional"))
    eleccion_id = leer_uuid(datos.get("eleccionId"), "eleccionId")

    # Ley 1581 de 2012: autorización previa, expresa e informada.
    if datos.get("aceptaTratamientoDatos") is not True:
        raise ErrorAPI(400, "AUTORIZACION_DATOS_REQUERIDA",
                       "Debe aceptar la política de tratamiento de datos personales para continuar")

    codigo = generar_otp()
    with transaccion() as cur:
        # Límite por IP: frena la enumeración del padrón probando documentos.
        clave_ip = f"otp:ip:{request.remote_addr}"
        limite_tasa.verificar(cur, clave_ip, cfg.OTP_MAX_POR_IP, cfg.OTP_VENTANA_MIN)
        limite_tasa.registrar(cur, clave_ip)
    with transaccion() as cur:
        eleccion = padron.obtener_eleccion(cur, eleccion_id)
        padron.exigir_en_votacion(eleccion)

        votante = padron.buscar_votante(cur, documento, bloquear=True)
        if not votante:
            raise ErrorAPI(404, "VOTANTE_NO_ENCONTRADO", "El documento no está en el padrón institucional")
        if padron.ya_voto(cur, votante["id"], eleccion_id):
            raise ErrorAPI(403, "YA_VOTO", "Usted ya emitió su voto en esta elección")

        # Rate limiting de la sección 5.3: N solicitudes cada M minutos por documento
        t = ahora()
        cur.execute(
            "SELECT count(*) AS n, min(fecha_generacion) AS primero FROM codigo_otp "
            "WHERE votante_id = %s AND fecha_generacion > %s",
            (votante["id"], t - timedelta(minutes=cfg.OTP_VENTANA_MIN)),
        )
        uso = cur.fetchone()
        if uso["n"] >= cfg.OTP_MAX_SOLICITUDES:
            raise limite_tasa.error_429(
                uso["primero"], cfg.OTP_VENTANA_MIN,
                f"Máximo {cfg.OTP_MAX_SOLICITUDES} códigos cada {cfg.OTP_VENTANA_MIN} minutos",
            )

        # Un código nuevo invalida los anteriores que no se usaron
        cur.execute("UPDATE codigo_otp SET usado = TRUE WHERE votante_id = %s AND usado = FALSE",
                    (votante["id"],))
        cur.execute(
            "INSERT INTO codigo_otp (votante_id, eleccion_id, codigo_hash, fecha_generacion, fecha_expiracion) "
            "VALUES (%s, %s, %s, %s, %s)",
            (votante["id"], eleccion_id, _hash_otp(votante["id"], eleccion_id, codigo),
             t, t + timedelta(seconds=cfg.OTP_EXPIRA_SEG)),
        )
        cur.execute(
            "UPDATE votante SET fecha_autorizacion_datos = %s, version_politica_datos = %s WHERE id = %s",
            (t, cfg.VERSION_POLITICA_DATOS, votante["id"]),
        )
        correo = votante["correo"]
        nombre_eleccion = eleccion["nombre"]

    try:
        enviar_otp(correo, codigo, nombre_eleccion, cfg.OTP_EXPIRA_SEG // 60)
    except ErrorCorreo:
        raise ErrorAPI(503, "CORREO_NO_ENVIADO", "No fue posible enviar el código. Intente de nuevo.")

    return jsonify({
        "mensaje": "OTP enviado",
        "expiraEn": cfg.OTP_EXPIRA_SEG,
        "destino": enmascarar_correo(correo),
    })


@bp.post("/otp/verificar")
def verificar_otp():
    cfg = _cfg()
    datos = leer_json()
    documento = padron.leer_documento(datos.get("documentoInstitucional"))
    eleccion_id = leer_uuid(datos.get("eleccionId"), "eleccionId")
    codigo = str(datos.get("codigoOTP", "")).strip()
    if not _RE_OTP.match(codigo):
        raise payload_invalido("'codigoOTP' debe tener 6 dígitos")

    error = None
    respuesta = None
    with transaccion() as cur:
        eleccion = padron.obtener_eleccion(cur, eleccion_id)
        padron.exigir_en_votacion(eleccion)
        votante = padron.buscar_votante(cur, documento)
        otp = None
        if votante:
            if padron.ya_voto(cur, votante["id"], eleccion_id):
                raise ErrorAPI(403, "YA_VOTO", "Usted ya emitió su voto en esta elección")
            cur.execute(
                "SELECT * FROM codigo_otp WHERE votante_id = %s AND eleccion_id = %s AND usado = FALSE "
                "ORDER BY fecha_generacion DESC LIMIT 1 FOR UPDATE",
                (votante["id"], eleccion_id),
            )
            otp = cur.fetchone()

        if not otp:
            error = ErrorAPI(401, "OTP_INVALIDO", "Código inválido. Solicite uno nuevo.")
        elif otp["fecha_expiracion"] <= ahora():
            cur.execute("UPDATE codigo_otp SET usado = TRUE WHERE id = %s", (otp["id"],))
            error = ErrorAPI(401, "OTP_EXPIRADO", "El código expiró. Solicite uno nuevo.")
        elif not comparar_seguro(_hash_otp(votante["id"], eleccion_id, codigo), otp["codigo_hash"]):
            intentos = otp["intentos"] + 1
            restantes = max(cfg.OTP_MAX_INTENTOS - intentos, 0)
            cur.execute("UPDATE codigo_otp SET intentos = %s, usado = %s WHERE id = %s",
                        (intentos, restantes == 0, otp["id"]))
            if restantes == 0:
                error = ErrorAPI(401, "OTP_BLOQUEADO",
                                 "Demasiados intentos fallidos. Solicite un código nuevo.")
            else:
                error = ErrorAPI(401, "OTP_INVALIDO", "Código incorrecto",
                                 extra={"intentosRestantes": restantes})
        else:
            cur.execute("UPDATE codigo_otp SET usado = TRUE WHERE id = %s", (otp["id"],))
            token, _ = jwt_utils.emitir(votante["id"], "votante", cfg.JWT_VOTANTE_SEG, eleccion_id)
            respuesta = {"token": token, "expiraEn": cfg.JWT_VOTANTE_SEG}

    if error:
        raise error
    return jsonify(respuesta)


@bp.post("/admin/login")
def login_admin():
    cfg = _cfg()
    datos = leer_json()
    usuario = leer_texto(datos, "usuario", 50)
    password = datos.get("password")
    if not isinstance(password, str) or not (1 <= len(password) <= 200):
        raise payload_invalido("'password' es obligatorio")

    clave_u = f"login:u:{usuario.lower()}"
    clave_ip = f"login:ip:{request.remote_addr}"
    with transaccion() as cur:
        limite_tasa.verificar(cur, clave_u, cfg.LOGIN_MAX_INTENTOS, cfg.LOGIN_VENTANA_MIN)
        limite_tasa.verificar(cur, clave_ip, cfg.LOGIN_MAX_INTENTOS * 4, cfg.LOGIN_VENTANA_MIN)
        cur.execute("SELECT id, nombre, rol, password_hash FROM administrador WHERE usuario = %s",
                    (usuario,))
        cuenta = cur.fetchone()

    # bcrypt fuera de la transacción (es lento a propósito)
    ok = verificar_password(password, cuenta["password_hash"] if cuenta else None)

    with transaccion() as cur:
        if ok:
            limite_tasa.limpiar(cur, clave_u)
            auditoria.registrar(cur, "LOGIN_EXITOSO", cuenta["id"])
        else:
            limite_tasa.registrar(cur, clave_u)
            limite_tasa.registrar(cur, clave_ip)
            auditoria.registrar(cur, "LOGIN_FALLIDO", cuenta["id"] if cuenta else None,
                                {"usuario": usuario[:50]})
    if not ok:
        raise ErrorAPI(401, "CREDENCIALES_INVALIDAS", "Usuario o contraseña incorrectos")

    token, _ = jwt_utils.emitir(cuenta["id"], cuenta["rol"], cfg.JWT_ADMIN_SEG)
    return jsonify({"token": token, "expiraEn": cfg.JWT_ADMIN_SEG,
                    "rol": cuenta["rol"], "nombre": cuenta["nombre"]})


@bp.post("/logout")
def logout():
    u = usuario_actual()
    expira = datetime.fromtimestamp(u["exp"], timezone.utc).replace(tzinfo=None)
    with transaccion() as cur:
        cur.execute(
            "INSERT INTO jwt_revocado (jti, expira, motivo) VALUES (%s, %s, 'LOGOUT') "
            "ON CONFLICT (jti) DO UPDATE SET motivo = 'LOGOUT'",
            (u["jti"], expira),
        )
        if u["role"] != "votante":
            auditoria.registrar(cur, "LOGOUT", u["sub"])
    return jsonify({"mensaje": "Sesión cerrada"})
