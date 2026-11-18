"""Envío del código OTP por correo institucional."""
import smtplib
from email.message import EmailMessage

from flask import current_app


class ErrorCorreo(Exception):
    pass


def enviar_otp(destino, codigo, nombre_eleccion, minutos):
    cfg = current_app.config["APP"]

    if not cfg.SMTP_HOST:
        if cfg.ENTORNO == "produccion":
            raise ErrorCorreo("SMTP no configurado")
        # Solo en desarrollo/pruebas: el código se escribe en el log del servidor.
        if cfg.TESTING:
            current_app.config.setdefault("OTP_ENVIADOS", []).append((destino, codigo))
        else:
            current_app.logger.warning("[DESARROLLO sin SMTP] OTP para %s: %s", destino, codigo)
        return

    msg = EmailMessage()
    msg["Subject"] = f"Su código de verificación: {codigo}"
    msg["From"] = cfg.SMTP_REMITENTE
    msg["To"] = destino
    msg.set_content(
        f"Hola,\n\n"
        f"Su código para votar en \"{nombre_eleccion}\" es:\n\n"
        f"    {codigo}\n\n"
        f"Vence en {minutos} minutos y sirve una sola vez.\n"
        f"Si usted no lo solicitó, ignore este mensaje.\n\n"
        f"VotoSeguro Bogotá"
    )
    try:
        with smtplib.SMTP(cfg.SMTP_HOST, cfg.SMTP_PORT, timeout=10) as smtp:
            if cfg.SMTP_STARTTLS:
                smtp.starttls()
            if cfg.SMTP_USUARIO:
                smtp.login(cfg.SMTP_USUARIO, cfg.SMTP_PASSWORD)
            smtp.send_message(msg)
    except (smtplib.SMTPException, OSError) as e:
        current_app.logger.error("No se pudo enviar el OTP: %s", e)
        raise ErrorCorreo(str(e))
