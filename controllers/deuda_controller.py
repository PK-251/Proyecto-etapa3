import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from auth import es_admin, get_usuario_actual
from database import get_db_session
from models import Ciudadano, Cuota, Deuda, EstadoDeudaEnum
from schemas import (
    ConsultaDeudaRequest, ConsultaDeudaResponse, Cuota as CuotaSchema,
    Deuda as DeudaSchema, PlanPagosRequest, PlanPagosResponse,
)
from services.deuda_service import ESTADOS_PAGABLES, DeudaService
from services.integrations import IntegracionSunat

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/deudas", tags=["Deudas"])


@router.post("/consultar", response_model=ConsultaDeudaResponse)
async def consultar_deudas(
    req: ConsultaDeudaRequest,
    db: AsyncSession = Depends(get_db_session),
    usuario: Ciudadano = Depends(get_usuario_actual),
):
    """HU-008: estado de cuenta (municipal + SUNAT). Un ciudadano solo consulta su propio DNI."""
    dni = req.dni or usuario.dni
    if dni != usuario.dni and not es_admin(usuario):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo puede consultar sus propias deudas.")

    ciudadano = (
        await db.execute(
            select(Ciudadano).where(Ciudadano.dni == dni).options(selectinload(Ciudadano.deudas))
        )
    ).scalar_one_or_none()
    if not ciudadano:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ciudadano no encontrado.")

    # HU-007: intereses al día de hoy (solo deudas impagas); se guardan para que el cobro use el mismo monto
    for deuda in ciudadano.deudas:
        DeudaService.actualizar_deuda(deuda)

    deudas_sunat = await IntegracionSunat.consultar_deudas(dni)
    total = DeudaService.calcular_total_deudas(ciudadano.deudas, deudas_sunat)

    return ConsultaDeudaResponse(
        deudasMunicipales=[DeudaSchema.model_validate(d) for d in ciudadano.deudas],
        deudasTributarias=deudas_sunat,
        totalGeneral=total,
    )


@router.post("/{deuda_id}/fraccionar", response_model=PlanPagosResponse, status_code=status.HTTP_201_CREATED)
async def crear_plan_pagos(
    deuda_id: int,
    req: PlanPagosRequest,
    db: AsyncSession = Depends(get_db_session),
    usuario: Ciudadano = Depends(get_usuario_actual),
):
    """HU-009: fracciona una deuda impaga en 3–12 cuotas mensuales."""
    deuda = (await db.execute(select(Deuda).where(Deuda.id == deuda_id))).scalar_one_or_none()
    if not deuda or deuda.ciudadano_id != usuario.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deuda no encontrada.")
    if deuda.estado not in ESTADOS_PAGABLES:
        raise HTTPException(status.HTTP_409_CONFLICT, f"La deuda está {deuda.estado.value} y no puede fraccionarse.")

    DeudaService.actualizar_deuda(deuda)
    cuotas = DeudaService.generar_cuotas(deuda, req.numero_cuotas)
    for c in cuotas:
        c.deuda_id = deuda.id
    db.add_all(cuotas)
    deuda.estado = EstadoDeudaEnum.FRACCIONADO
    await db.flush()

    logger.info("Plan de %s cuotas creado para deuda %s", req.numero_cuotas, deuda.id)
    return PlanPagosResponse(
        message="Plan de pagos creado exitosamente",
        deuda_id=deuda.id,
        cuotas=[CuotaSchema.model_validate(c) for c in cuotas],
    )
