"""Firma y verificación pública de comprobantes (el QR de la boleta apunta a /verificar/...)."""
import hashlib
import hmac
import re
from decimal import Decimal
from typing import Optional

import config
from models import Pago

_NUM_RE = re.compile(rf"^{re.escape(config.COMPROBANTE_SERIE)}-(\d{{8}})$")


def firmar(pago: Pago) -> str:
    """Firma corta (HMAC con SECRET_KEY): impide fabricar o adivinar enlaces de verificación."""
    msg = f"{pago.id}|{Decimal(pago.monto):.2f}|{pago.transaccion_id or ''}".encode()
    return hmac.new(config.SECRET_KEY.encode(), msg, hashlib.sha256).hexdigest()[:16]


def url_verificacion(pago: Pago) -> str:
    return f"{config.PUBLIC_BASE_URL}/verificar/{pago.numero_comprobante}?h={firmar(pago)}"


def id_desde_numero(numero: str) -> Optional[int]:
    m = _NUM_RE.match(numero or "")
    return int(m.group(1)) if m else None


def firma_valida(pago: Pago, h: str) -> bool:
    return hmac.compare_digest(firmar(pago), h or "")


def enmascarar_nombre(nombre: str) -> str:
    """JUAN CARLOS DELGADO -> JUAN C*** D***  (el verificador es público: no exponer el nombre completo)."""
    partes = (nombre or "").split()
    if not partes:
        return "—"
    return " ".join([partes[0]] + [p[0] + "***" for p in partes[1:]])
