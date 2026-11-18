"""Funciones criptográficas del sistema."""
import hashlib
import hmac
import secrets

import bcrypt
from flask import current_app


def sha256_hex(texto):
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def hmac_hex(texto):
    """HMAC-SHA256 con la clave del servidor.

    Se usa para el hash del documento (búsqueda sin texto plano) y para el
    hash del OTP: con SHA-256 simple, un código de 6 dígitos se revierte
    probando el millón de combinaciones; con HMAC hace falta además la clave.
    """
    clave = current_app.config["APP"].CLAVE_HMAC.encode("utf-8")
    return hmac.new(clave, texto.encode("utf-8"), hashlib.sha256).hexdigest()


def comparar_seguro(a, b):
    return hmac.compare_digest(a, b)


def generar_otp():
    """Código de 6 dígitos con generador criptográfico (no random)."""
    return f"{secrets.randbelow(10**6):06d}"


def generar_secreto_token():
    return secrets.token_urlsafe(32)


def hash_password(password):
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


# Hash válido de una contraseña aleatoria: se compara contra él cuando el
# usuario no existe, para que el tiempo de respuesta no revele si existe.
_HASH_SENUELO = bcrypt.hashpw(secrets.token_bytes(16), bcrypt.gensalt(rounds=12))


def verificar_password(password, password_hash):
    objetivo = password_hash.encode("utf-8") if password_hash else _HASH_SENUELO
    try:
        ok = bcrypt.checkpw(password.encode("utf-8"), objetivo)
    except ValueError:
        return False
    return ok and password_hash is not None


def normalizar_documento(documento):
    return documento.strip().upper()


def enmascarar_correo(correo):
    usuario, _, dominio = correo.partition("@")
    if len(usuario) <= 2:
        visible = usuario[:1]
    else:
        visible = usuario[0] + "***" + usuario[-1]
    return f"{visible}@{dominio}"
