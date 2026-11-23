"""Prueba tus datos de correo y WhatsApp (CallMeBot) sin abrir el portal.

    python probar_avisos.py tu_correo@ejemplo.com

Lee el .env, envía un correo de prueba a la dirección indicada y un WhatsApp al número de CALLMEBOT_PHONE,
y muestra el resultado de cada uno con el motivo exacto si falla.
"""
import sys
import urllib.parse
import urllib.request

import config


def probar_correo(destino: str) -> None:
    import smtplib, ssl
    from email.message import EmailMessage
    if not config.EMAIL_ACTIVO:
        print("CORREO: sin configurar. Completa SMTP_HOST, SMTP_USER y SMTP_PASSWORD en el .env.")
        return
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = config.SMTP_FROM, destino, "Prueba de avisos - Portal Municipal"
    msg.set_content("Si lees esto, el envío de correos del portal funciona.")
    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as s:
            if config.SMTP_STARTTLS:
                s.starttls(context=ssl.create_default_context())
            s.login(config.SMTP_USER, config.SMTP_PASSWORD)
            s.send_message(msg)
        print(f"CORREO: enviado a {destino}. Revisa la bandeja (y spam).")
    except smtplib.SMTPAuthenticationError as e:
        print(f"CORREO: usuario o contraseña rechazados ({e.smtp_code}). Con Gmail/Outlook se usa una 'contraseña de aplicación'; "
              "algunas cuentas institucionales tienen el SMTP desactivado por el administrador.")
    except Exception as e:  # noqa: BLE001
        print(f"CORREO: falló -> {type(e).__name__}: {e}")


def probar_whatsapp() -> None:
    if not config.WHATSAPP_ACTIVO:
        print("WHATSAPP: sin configurar. Completa CALLMEBOT_PHONE y CALLMEBOT_APIKEY en el .env.")
        return
    url = "https://api.callmebot.com/whatsapp.php?" + urllib.parse.urlencode(
        {"phone": config.CALLMEBOT_PHONE, "text": "Prueba de avisos - Portal Municipal", "apikey": config.CALLMEBOT_APIKEY})
    try:
        with urllib.request.urlopen(url, timeout=20) as r:  # noqa: S310
            print(f"WHATSAPP: CallMeBot respondió HTTP {r.status}. Si no llega el mensaje, revisa teléfono y apikey.")
    except Exception as e:  # noqa: BLE001
        print(f"WHATSAPP: falló -> {type(e).__name__}: {e}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Uso: python probar_avisos.py tu_correo@ejemplo.com")
    probar_correo(sys.argv[1])
    probar_whatsapp()
