"""Emisión y validación de JWT (sección 2.2 del documento).

Se usa HS256: un solo servicio emite y valida el token, así que una clave
simétrica es suficiente. RS256 solo aporta si varios servicios
independientes tuvieran que verificar tokens.
"""
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from flask import current_app

ALGORITMO = "HS256"
EMISOR = "votoseguro-bogota"


def emitir(sub, rol, duracion_seg, eleccion_id=None):
    cfg = current_app.config["APP"]
    ahora = datetime.now(timezone.utc)
    exp = ahora + timedelta(seconds=duracion_seg)
    jti = str(uuid.uuid4())
    claims = {
        "sub": str(sub),
        "role": rol,
        "jti": jti,
        "iat": int(ahora.timestamp()),
        "exp": int(exp.timestamp()),
        "iss": EMISOR,
    }
    if eleccion_id:
        claims["eleccionId"] = str(eleccion_id)
    token = jwt.encode(claims, cfg.JWT_SECRET, algorithm=ALGORITMO)
    return token, claims


def decodificar(token):
    """Lanza jwt.InvalidTokenError (o subclases) si el token no es válido."""
    cfg = current_app.config["APP"]
    return jwt.decode(
        token,
        cfg.JWT_SECRET,
        algorithms=[ALGORITMO],          # lista cerrada: evita el ataque "alg: none"
        issuer=EMISOR,
        options={"require": ["sub", "role", "jti", "exp", "iat"]},
    )
