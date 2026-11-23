"""Verificación PÚBLICA (sin login) de comprobantes de pago: se llega escaneando el QR de la boleta."""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

import config
from database import get_db_session
from models import Ciudadano, EstadoPagoEnum, Pago
from services import verificacion
from services.rate_limit import RateLimiter

router = APIRouter(tags=["Verificación de comprobantes"])
templates = Jinja2Templates(directory="templates")
_limite = RateLimiter(max_events=30, window_seconds=60)


async def _buscar(db: AsyncSession, numero: str, h: str):
    pago_id = verificacion.id_desde_numero(numero)
    pago = None
    if pago_id is not None:
        pago = (
            await db.execute(
                select(Pago)
                .options(selectinload(Pago.deuda_asociada), selectinload(Pago.tramite_asociado))
                .where(Pago.id == pago_id)
            )
        ).scalar_one_or_none()
    # Misma respuesta para "no existe" y "firma incorrecta": no se puede enumerar comprobantes
    if not pago or pago.estado != EstadoPagoEnum.COMPLETADO or not verificacion.firma_valida(pago, h):
        return None
    item = pago.deuda_asociada or pago.tramite_asociado
    ciudadano = (await db.execute(select(Ciudadano).where(Ciudadano.id == item.ciudadano_id))).scalar_one()
    return {
        "valido": True,
        "numero_comprobante": pago.numero_comprobante,
        "fecha_pago": pago.fecha_pago,
        "concepto": pago.concepto,
        "monto": f"{pago.monto:.2f}",
        "metodo": pago.metodo.value,
        "contribuyente": verificacion.enmascarar_nombre(ciudadano.nombre),
        "emisor": config.MUNI_NOMBRE,
    }


def _controlar_ritmo(request: Request) -> None:
    ip = request.client.host if request.client else "?"
    if not _limite.check_and_hit(ip):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Demasiadas consultas. Intente en un minuto.")


@router.get("/api/v1/verificar/{numero}")
async def verificar_json(numero: str, request: Request, h: str = "", db: AsyncSession = Depends(get_db_session)):
    _controlar_ritmo(request)
    datos = await _buscar(db, numero, h)
    if not datos:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comprobante no encontrado o enlace inválido.")
    return datos


@router.get("/verificar/{numero}", response_class=HTMLResponse, include_in_schema=False)
async def verificar_html(numero: str, request: Request, h: str = "", db: AsyncSession = Depends(get_db_session)):
    _controlar_ritmo(request)
    datos = await _buscar(db, numero, h)
    return templates.TemplateResponse(
        request, "verificar.html",
        {"datos": datos, "numero": numero, "muni": config.MUNI_NOMBRE, "demo": config.MODO_DEMO},
        status_code=200 if datos else 404,
    )
