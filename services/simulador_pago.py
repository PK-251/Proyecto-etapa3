"""Pasarela de pagos SIMULADA con reglas de aprobación/rechazo realistas.

Tarjetas de prueba (Luhn válido):
  4111 1111 1111 1111  -> aprobada (Visa)        5555 5555 5555 4444 -> aprobada (Mastercard)
  4000 0000 0000 0002  -> rechazada: fondos insuficientes
  4000 0000 0000 0127  -> rechazada: transacción no permitida
  4000 0000 0000 0069  -> rechazada: tarjeta vencida o bloqueada
Yape / Plin: celular de 9 dígitos que empiece con 9 + código de aprobación de 6 dígitos
  (el código 000000 se rechaza como inválido o vencido).

Para producción: reemplazar `procesar_pago` por la llamada real (httpx) a Culqi, Niubiz, Izipay, etc.
Los datos de la tarjeta NUNCA se guardan: solo marca y últimos 4 dígitos.
"""
import asyncio
import logging
import secrets
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

import config
from models import MetodoPagoEnum

logger = logging.getLogger(__name__)

RECHAZOS_TARJETA = {
    "0002": "Fondos insuficientes.",
    "0127": "Transacción no permitida por el banco emisor.",
    "0069": "Tarjeta vencida o bloqueada.",
}


@dataclass
class ResultadoPasarela:
    aprobado: bool
    transaccion_id: str
    detalle_metodo: str
    codigo_autorizacion: Optional[str] = None
    motivo: Optional[str] = None


def marca_tarjeta(numero: str) -> str:
    if numero.startswith("4"):
        return "VISA"
    if numero[:2] in {"51", "52", "53", "54", "55"} or 2221 <= int(numero[:4] or 0) <= 2720:
        return "MASTERCARD"
    if numero[:2] in {"34", "37"}:
        return "AMEX"
    if numero[:2] in {"36", "38"} or numero[:3] in {"300", "301", "302", "303", "304", "305"}:
        return "DINERS"
    return "TARJETA"


def luhn_valido(numero: str) -> bool:
    digitos = [int(d) for d in numero][::-1]
    total = sum(digitos[0::2]) + sum(sum(divmod(d * 2, 10)) for d in digitos[1::2])
    return total % 10 == 0


async def procesar_pago(monto: Decimal, req) -> ResultadoPasarela:
    """Procesa el cobro. `req` es un PagoRequest ya validado."""
    await asyncio.sleep(config.GATEWAY_LATENCY_S)  # latencia de red simulada
    tx = "TX" + uuid.uuid4().hex[:12].upper()

    if req.metodo == MetodoPagoEnum.TARJETA:
        numero = req.tarjeta.numero
        detalle = f"{marca_tarjeta(numero)} ****{numero[-4:]}"
        motivo = RECHAZOS_TARJETA.get(numero[-4:])
    else:
        nombre = "Yape" if req.metodo == MetodoPagoEnum.YAPE else "Plin"
        detalle = f"{nombre} {req.celular[:1]}•••••{req.celular[-3:]}"
        motivo = "Código de aprobación inválido o vencido." if req.codigo_aprobacion == "000000" else None

    if motivo:
        logger.info("Pasarela simulada: RECHAZADO %s (%s)", tx, detalle)
        return ResultadoPasarela(False, tx, detalle, motivo=motivo)

    logger.info("Pasarela simulada: APROBADO %s S/ %s (%s)", tx, monto, detalle)
    return ResultadoPasarela(True, tx, detalle, codigo_autorizacion=f"{secrets.randbelow(10**6):06d}")
