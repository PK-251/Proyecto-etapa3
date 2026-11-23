import logging
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import or_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from auth import es_admin, get_usuario_actual
from database import get_db_session
from models import (
    NOMBRES_DEUDA, NOMBRES_TRAMITE, Ciudadano, Deuda, EstadoDeudaEnum, EstadoPagoEnum,
    EstadoTramiteEnum, Pago, Tramite,
)
from schemas import PagoHistorial, PagoRequest, PagoResponse
import config
from services import pdf_service, simulador_pago
from services.deuda_service import ESTADOS_PAGABLES, DeudaService
from services.rate_limit import RateLimiter
from services.notificaciones import notificar  # noqa: E402

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/api/v1/pagos",
    tags=["Pagos"],
    dependencies=[Depends(get_usuario_actual)],
)

CENTAVO = Decimal("0.01")
# Anti "card testing": máx. N pagos rechazados por usuario cada 10 minutos
_rechazos = RateLimiter(max_events=config.MAX_PAGOS_FALLIDOS, window_seconds=600)


def _importe(valor) -> Decimal:
    return Decimal(str(valor)).quantize(CENTAVO)


def _respuesta(pago: Pago, mensaje: str, **extra) -> PagoResponse:
    return PagoResponse(
        id=pago.id, estado=pago.estado, monto=pago.monto, metodo=pago.metodo, mensaje=mensaje,
        numero_comprobante=pago.numero_comprobante if pago.estado == EstadoPagoEnum.COMPLETADO else None,
        transaccion_id=pago.transaccion_id, codigo_autorizacion=pago.codigo_autorizacion,
        detalle_metodo=pago.detalle_metodo, concepto=pago.concepto, fecha_pago=pago.fecha_pago, **extra,
    )


def _chequear_bloqueo(usuario: Ciudadano) -> None:
    if _rechazos.is_blocked(usuario.dni):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Demasiados pagos rechazados. Por seguridad, espere unos minutos antes de intentar de nuevo.",
        )


async def _cobrar(db: AsyncSession, usuario: Ciudadano, req: PagoRequest, *, monto: Decimal, concepto: str,
                  destino: dict, revertir, monto_base=None, intereses=None):
    """Llama a la pasarela y registra el pago. Si es rechazado: revierte la reserva y guarda el intento
    como FALLIDO (así queda historial y el usuario puede reintentar). Devuelve (pago, resultado)."""
    resultado = await simulador_pago.procesar_pago(monto, req)
    pago = Pago(
        monto=monto, metodo=req.metodo, concepto=concepto, monto_base=monto_base, intereses=intereses,
        transaccion_id=resultado.transaccion_id, detalle_metodo=resultado.detalle_metodo, **destino,
    )
    if resultado.aprobado:
        pago.estado = EstadoPagoEnum.COMPLETADO
        pago.codigo_autorizacion = resultado.codigo_autorizacion
    else:
        await revertir()
        pago.estado = EstadoPagoEnum.FALLIDO
        pago.motivo_rechazo = resultado.motivo
        _rechazos.hit(usuario.dni)
    db.add(pago)
    await db.flush()
    return pago, resultado


def _rechazo_http(pago: Pago, motivo: str) -> JSONResponse:
    # Se devuelve (no se lanza) para que la sesión haga COMMIT y quede registrado el intento fallido
    return JSONResponse(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        content={"detail": f"Pago rechazado: {motivo}", "pago_id": pago.id, "motivo": motivo},
    )


@router.post("/tramite/{tramite_id}", response_model=PagoResponse)
async def pagar_tramite(
    tramite_id: int,
    pago_request: PagoRequest,
    db: AsyncSession = Depends(get_db_session),
    usuario: Ciudadano = Depends(get_usuario_actual),
):
    """HU-006: paga un trámite que está pendiente de pago."""
    _chequear_bloqueo(usuario)
    tramite = (await db.execute(select(Tramite).where(Tramite.id == tramite_id))).scalar_one_or_none()
    if not tramite or tramite.ciudadano_id != usuario.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trámite no encontrado.")
    if tramite.estado != EstadoTramiteEnum.PENDIENTE_PAGO:
        raise HTTPException(status.HTTP_409_CONFLICT, "Este trámite ya fue pagado.")

    costo = _importe(tramite.costo_total)
    if _importe(pago_request.monto) != costo:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"El monto (S/ {_importe(pago_request.monto)}) no coincide con el costo del trámite (S/ {costo}).",
        )

    # Reserva atómica antes de cobrar: evita doble pago por doble clic o peticiones paralelas
    reserva = await db.execute(
        update(Tramite)
        .where(Tramite.id == tramite_id, Tramite.estado == EstadoTramiteEnum.PENDIENTE_PAGO)
        .values(estado=EstadoTramiteEnum.EN_EVALUACION)
    )
    if reserva.rowcount != 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "Este trámite ya fue pagado.")

    async def revertir():
        await db.execute(
            update(Tramite).where(Tramite.id == tramite_id).values(estado=EstadoTramiteEnum.PENDIENTE_PAGO)
        )

    pago, res = await _cobrar(
        db, usuario, pago_request, monto=costo, destino={"tramite_id": tramite.id}, revertir=revertir,
        concepto=f"{NOMBRES_TRAMITE.get(tramite.tipo, tramite.tipo.value)} - Exp. {tramite.expediente}",
        monto_base=costo, intereses=Decimal("0.00"),
    )
    if not res.aprobado:
        return _rechazo_http(pago, res.motivo)
    await notificar(
        db, usuario.id, "PAGO", "Pago recibido",
        f"Boleta {pago.numero_comprobante} por S/ {costo}. Su trámite {tramite.expediente} pasó a evaluación.",
        f"tramite:{tramite.id}",
    )
    logger.info("Pago %s completado (trámite %s)", pago.id, tramite.expediente)
    return _respuesta(pago, "Pago procesado exitosamente.", tramite_expediente=tramite.expediente)


@router.post("/deuda/{deuda_id}", response_model=PagoResponse)
async def pagar_deuda(
    deuda_id: int,
    pago_request: PagoRequest,
    db: AsyncSession = Depends(get_db_session),
    usuario: Ciudadano = Depends(get_usuario_actual),
):
    """HU-008: paga una deuda por su monto total actualizado (con intereses a hoy)."""
    _chequear_bloqueo(usuario)
    deuda = (await db.execute(select(Deuda).where(Deuda.id == deuda_id))).scalar_one_or_none()
    if not deuda or deuda.ciudadano_id != usuario.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deuda no encontrada.")
    if deuda.estado not in ESTADOS_PAGABLES:
        raise HTTPException(status.HTTP_409_CONFLICT, f"La deuda no se puede pagar: está {deuda.estado.value}.")

    DeudaService.actualizar_deuda(deuda)
    await db.flush()
    total = _importe(deuda.monto_total)
    if _importe(pago_request.monto) != total:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"El importe de la deuda cambió: ahora es S/ {total}. Vuelva a consultar sus deudas.",
        )

    estado_previo = deuda.estado
    reserva = await db.execute(
        update(Deuda).where(Deuda.id == deuda_id, Deuda.estado == estado_previo).values(estado=EstadoDeudaEnum.PAGADO)
    )
    if reserva.rowcount != 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "Esta deuda ya fue pagada.")

    async def revertir():
        await db.execute(update(Deuda).where(Deuda.id == deuda_id).values(estado=estado_previo))

    pago, res = await _cobrar(
        db, usuario, pago_request, monto=total, destino={"deuda_id": deuda.id}, revertir=revertir,
        concepto=f"{NOMBRES_DEUDA.get(deuda.tipo, deuda.tipo.value)} - Periodo {deuda.periodo or '-'}",
        monto_base=_importe(deuda.monto_base), intereses=_importe(deuda.intereses_moratorios),
    )
    if not res.aprobado:
        return _rechazo_http(pago, res.motivo)
    await notificar(
        db, usuario.id, "PAGO", "Pago recibido",
        f"Boleta {pago.numero_comprobante} por S/ {total}. Su deuda quedó cancelada.", "deuda:%d" % deuda.id,
    )
    logger.info("Pago %s completado (deuda %s)", pago.id, deuda.id)
    return _respuesta(pago, "El pago de su deuda se procesó correctamente.", deuda_id=deuda.id)


@router.get("/mis-pagos", response_model=list[PagoHistorial])
async def mis_pagos(db: AsyncSession = Depends(get_db_session), usuario: Ciudadano = Depends(get_usuario_actual)):
    """Historial de pagos del usuario (incluye los intentos rechazados)."""
    filas = (
        await db.execute(
            select(Pago)
            .outerjoin(Tramite, Pago.tramite_id == Tramite.id)
            .outerjoin(Deuda, Pago.deuda_id == Deuda.id)
            .where(or_(Tramite.ciudadano_id == usuario.id, Deuda.ciudadano_id == usuario.id))
            .order_by(Pago.fecha_pago.desc(), Pago.id.desc())
            .limit(200)
        )
    ).scalars().all()
    return [
        PagoHistorial.model_validate(p).model_copy(
            update={"numero_comprobante": p.numero_comprobante if p.estado == EstadoPagoEnum.COMPLETADO else None}
        )
        for p in filas
    ]


@router.get("/comprobante/{pago_id}", response_class=Response)
async def descargar_comprobante_pdf(
    pago_id: int,
    db: AsyncSession = Depends(get_db_session),
    usuario: Ciudadano = Depends(get_usuario_actual),
):
    """HU-007: boleta/comprobante de pago en PDF (solo el dueño del pago o un admin; solo pagos completados)."""
    pago = (
        await db.execute(
            select(Pago)
            .options(selectinload(Pago.deuda_asociada), selectinload(Pago.tramite_asociado))
            .where(Pago.id == pago_id)
        )
    ).scalar_one_or_none()

    item = (pago.deuda_asociada or pago.tramite_asociado) if pago else None
    if not pago or not item or (item.ciudadano_id != usuario.id and not es_admin(usuario)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pago no encontrado.")
    if pago.estado != EstadoPagoEnum.COMPLETADO:
        raise HTTPException(status.HTTP_409_CONFLICT, "Solo los pagos completados tienen comprobante.")

    ciudadano = (await db.execute(select(Ciudadano).where(Ciudadano.id == item.ciudadano_id))).scalar_one()
    try:
        buffer = pdf_service.generar_comprobante_pdf(pago=pago, ciudadano=ciudadano, item_pagado=item)
        pdf_bytes = buffer.getvalue()
        buffer.close()
    except Exception:
        logger.exception("Error generando comprobante del pago %s", pago_id)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "No se pudo generar el comprobante.")

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="boleta_{pago.numero_comprobante}.pdf"'},
    )
