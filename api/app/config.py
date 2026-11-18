"""Configuración leída de variables de entorno (nunca secretos en el código)."""
import os


class ErrorConfiguracion(RuntimeError):
    pass


def _bool(valor, defecto=False):
    if valor is None:
        return defecto
    return valor.strip().lower() in ("1", "true", "si", "sí", "yes")


class Config:
    def __init__(self, entorno=None):
        env = entorno if entorno is not None else os.environ

        self.ENTORNO = env.get("ENTORNO", "desarrollo")
        self.DATABASE_URL = env.get("DATABASE_URL", "")

        # Secretos
        self.JWT_SECRET = env.get("JWT_SECRET", "")
        self.CLAVE_HMAC = env.get("CLAVE_HMAC", "")
        self.CLAVE_CIFRADO_DATOS = env.get("CLAVE_CIFRADO_DATOS", "")

        # OTP (sección 3.1 y 5.3 del documento)
        self.OTP_EXPIRA_SEG = int(env.get("OTP_EXPIRA_SEG", 300))
        self.OTP_MAX_SOLICITUDES = int(env.get("OTP_MAX_SOLICITUDES", 3))
        self.OTP_VENTANA_MIN = int(env.get("OTP_VENTANA_MIN", 10))
        self.OTP_MAX_INTENTOS = int(env.get("OTP_MAX_INTENTOS", 5))
        # Por IP: alto a propósito, porque en un campus muchos votantes salen por la misma IP pública
        self.OTP_MAX_POR_IP = int(env.get("OTP_MAX_POR_IP", 300))

        # JWT (sección 2)
        self.JWT_VOTANTE_SEG = int(env.get("JWT_VOTANTE_SEG", 600))
        self.JWT_ADMIN_SEG = int(env.get("JWT_ADMIN_SEG", 8 * 3600))

        # Login administrador
        self.LOGIN_MAX_INTENTOS = int(env.get("LOGIN_MAX_INTENTOS", 5))
        self.LOGIN_VENTANA_MIN = int(env.get("LOGIN_VENTANA_MIN", 15))

        # Correo
        self.SMTP_HOST = env.get("SMTP_HOST", "")
        self.SMTP_PORT = int(env.get("SMTP_PORT", 587))
        self.SMTP_USUARIO = env.get("SMTP_USUARIO", "")
        self.SMTP_PASSWORD = env.get("SMTP_PASSWORD", "")
        self.SMTP_STARTTLS = _bool(env.get("SMTP_STARTTLS"), True)
        self.SMTP_REMITENTE = env.get("SMTP_REMITENTE", "VotoSeguro Bogotá <no-responder@votoseguro.local>")

        # Ley 1581 de 2012
        self.VERSION_POLITICA_DATOS = env.get("VERSION_POLITICA_DATOS", "1.0")

        # CORS: solo necesario si el frontend se sirve desde otro origen
        self.CORS_ORIGENES = [o.strip() for o in env.get("CORS_ORIGENES", "").split(",") if o.strip()]

        # Cuántos proxies hay delante de la API (nginx = 1; Netlify + Railway = 2)
        self.PROXY_SALTOS = int(env.get("PROXY_SALTOS", 1))

        self.TESTING = _bool(env.get("TESTING"), False)

    def validar(self):
        faltan = [n for n in ("DATABASE_URL", "JWT_SECRET", "CLAVE_HMAC", "CLAVE_CIFRADO_DATOS")
                  if not getattr(self, n)]
        if faltan:
            raise ErrorConfiguracion("Faltan variables de entorno: " + ", ".join(faltan))
        for nombre in ("JWT_SECRET", "CLAVE_HMAC", "CLAVE_CIFRADO_DATOS"):
            valor = getattr(self, nombre)
            if len(valor) < 32:
                raise ErrorConfiguracion(f"{nombre} debe tener al menos 32 caracteres")
            if self.ENTORNO == "produccion" and "cambiar" in valor.lower():
                raise ErrorConfiguracion(f"{nombre} conserva el valor de ejemplo; genere uno propio")
        if self.ENTORNO == "produccion" and not self.SMTP_HOST:
            raise ErrorConfiguracion("En producción SMTP_HOST es obligatorio (los OTP se envían por correo)")
