"""Envío de avisos por correo (SMTP) y WhatsApp (CallMeBot).

- Nunca bloquea ni rompe la petición: se envía en un hilo aparte y los errores solo se registran.
- Los mensajes de un cambio se envían SOLO si la transacción se confirma (evento after_commit).
- CallMeBot solo puede escribir al número que lo activó: se usa para avisar al personal, no a cada ciudadano.
"""
import logging
import smtplib
import ssl
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from email.message import EmailMessage

from sqlalchemy import event
from sqlalchemy.orm import Session

import config

logger = logging.getLogger(__name__)
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="avisos")

PIE_CORREO = f"\n\n— {config.MUNI_NOMBRE}\nEste es un aviso automático, no responda a este correo."


def _enviar_correo(destino: str, asunto: str, texto: str) -> None:
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = config.SMTP_FROM, destino, asunto
    msg.set_content(texto + PIE_CORREO)
    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=15) as smtp:
            if config.SMTP_STARTTLS:
                smtp.starttls(context=ssl.create_default_context())
            smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
            smtp.send_message(msg)
        logger.info("Correo enviado a %s", destino)
    except Exception as e:  # noqa: BLE001 - un aviso fallido no debe afectar al trámite
        logger.warning("No se pudo enviar el correo a %s: %s", destino, e)


def _enviar_whatsapp(texto: str) -> None:
    url = "https://api.callmebot.com/whatsapp.php?" + urllib.parse.urlencode(
        {"phone": config.CALLMEBOT_PHONE, "text": texto[:900], "apikey": config.CALLMEBOT_APIKEY}
    )
    try:
        with urllib.request.urlopen(url, timeout=15) as r:  # noqa: S310 - URL fija de CallMeBot
            logger.info("WhatsApp enviado (HTTP %s)", r.status)
    except Exception as e:  # noqa: BLE001
        logger.warning("No se pudo enviar el WhatsApp: %s", e)


def despachar(salida: list) -> None:
    for tipo, *datos in salida:
        if tipo == "correo" and config.EMAIL_ACTIVO:
            _pool.submit(_enviar_correo, *datos)
        elif tipo == "whatsapp" and config.WHATSAPP_ACTIVO:
            _pool.submit(_enviar_whatsapp, *datos)


def encolar(db, tipo: str, *datos) -> None:
    """Deja un mensaje pendiente en la sesión; sale cuando se confirma la transacción."""
    db.sync_session.info.setdefault("salida", []).append((tipo, *datos))


def correo_inmediato(destino: str, asunto: str, texto: str) -> None:
    """Para códigos de recuperación: no depende de ninguna transacción."""
    if config.EMAIL_ACTIVO:
        _pool.submit(_enviar_correo, destino, asunto, texto)


@event.listens_for(Session, "after_commit")
def _al_confirmar(session) -> None:
    salida = session.info.pop("salida", None)
    if salida:
        despachar(salida)


@event.listens_for(Session, "after_rollback")
def _al_revertir(session) -> None:
    session.info.pop("salida", None)
