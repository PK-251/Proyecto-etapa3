import csv
import io
import logging
import secrets
from datetime import datetime, timedelta, timezone
from datetime import date
from typing import List, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

import config
from auth import get_admin_actual
from database import get_db_session
from catalogo import AREAS, area_de_tramite
from models import (
    ESTADOS_SOLICITUD_CERRADOS, NOMBRES_TRAMITE, Auditoria, Solicitud,
    Ciudadano, Deuda, EstadoPagoEnum, EstadoTramiteEnum, MetodoPagoEnum, Pago, Tramite,
)
from schemas import AuditoriaView, CiudadanoAdminView, CiudadanoCreateAdmin, PagoAdminView, PagoHistorial
from security import get_password_hash
from services.auditoria import registrar as auditar

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/api/v1/admin",
    tags=["Administrador"],
    dependencies=[Depends(get_admin_actual)],
)


@router.post("/ciudadanos", response_model=CiudadanoAdminView, status_code=status.HTTP_201_CREATED)
async def admin_crear_ciudadano(
    ciudadano_in: CiudadanoCreateAdmin,
    db: AsyncSession = Depends(get_db_session),
    admin: Ciudadano = Depends(get_admin_actual),
):
    """HU-010: crea un ciudadano (o admin)."""
    if (await db.execute(select(Ciudadano).where(Ciudadano.dni == ciudadano_in.dni))).scalar_one_or_none():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ya existe un ciudadano con este DNI.")
    if ciudadano_in.email and (
        await db.execute(select(Ciudadano).where(Ciudadano.email == ciudadano_in.email))
    ).scalar_one_or_none():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ya existe un ciudadano con este correo.")

    nuevo = Ciudadano(
        dni=ciudadano_in.dni,
        nombre=ciudadano_in.nombre,
        email=ciudadano_in.email,
        hashed_password=get_password_hash(ciudadano_in.password),
        role=ciudadano_in.role,
        area=ciudadano_in.area,
    )
    db.add(nuevo)
    try:
        await db.flush()
    except IntegrityError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "El DNI o el correo ya están registrados.")
    await db.refresh(nuevo)
    await auditar(db, admin, "USUARIO_CREADO", "usuario", nuevo.dni, f"rol={nuevo.role}" + (f", área={nuevo.area}" if nuevo.area else ""))
    logger.info("Admin %s creó al usuario %s (%s)", admin.dni, nuevo.dni, nuevo.role)
    return nuevo


@router.get("/ciudadanos", response_model=List[CiudadanoAdminView])
async def admin_listar_ciudadanos(db: AsyncSession = Depends(get_db_session)):
    result = await db.execute(select(Ciudadano).order_by(Ciudadano.nombre))
    return result.scalars().all()


@router.post("/usuarios/{dni}/reset-password")
async def admin_reset_password(
    dni: str,
    db: AsyncSession = Depends(get_db_session),
    admin: Ciudadano = Depends(get_admin_actual),
):
    """HU-010: asigna una contraseña temporal (se muestra una sola vez)."""
    ciudadano = (await db.execute(select(Ciudadano).where(Ciudadano.dni == dni))).scalar_one_or_none()
    if not ciudadano:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Usuario con DNI {dni} no encontrado.")

    nueva = secrets.token_urlsafe(9)
    ciudadano.hashed_password = get_password_hash(nueva)
    await auditar(db, admin, "CLAVE_RESETEADA", "usuario", dni)
    logger.info("Admin %s reseteó la contraseña de %s", admin.dni, dni)
    return {"message": "Contraseña reseteada exitosamente", "password": nueva, "dni": dni}


def _sql(valor) -> str:
    if valor is None:
        return "NULL"
    return "'" + str(valor).replace("'", "''") + "'"


@router.get("/export/ciudadanos.sql")
async def admin_exportar_ciudadanos_sql(db: AsyncSession = Depends(get_db_session)):
    """HU-010: respaldo de la tabla ciudadano en SQL (incluye hashes: guárdalo de forma segura)."""
    ciudadanos = (await db.execute(select(Ciudadano).order_by(Ciudadano.id))).scalars().all()

    out = io.StringIO()
    out.write("-- Backup de la tabla 'ciudadano' --\n")
    out.write(f"-- Generado: {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} UTC --\n\n")
    for c in ciudadanos:
        out.write(
            "INSERT INTO ciudadano (dni, nombre, email, telefono, direccion, hashed_password, role) VALUES "
            f"({_sql(c.dni)}, {_sql(c.nombre)}, {_sql(c.email)}, {_sql(c.telefono)}, "
            f"{_sql(c.direccion)}, {_sql(c.hashed_password)}, {_sql(c.role)});\n"
        )
    return Response(
        content=out.getvalue(),
        media_type="application/sql",
        headers={"Content-Disposition": "attachment; filename=backup_ciudadanos.sql"},
    )


@router.get("/stats")
async def admin_estadisticas(db: AsyncSession = Depends(get_db_session)):
    """HU-004: trámites de hoy, trámites en curso y recaudación del día (según APP_TIMEZONE)."""
    tz = ZoneInfo(config.APP_TIMEZONE)
    inicio_local = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    fin_local = inicio_local + timedelta(days=1)
    # La BD guarda UTC: se convierten los límites del día local a UTC
    inicio = inicio_local.astimezone(timezone.utc).replace(tzinfo=None)
    fin = fin_local.astimezone(timezone.utc).replace(tzinfo=None)

    tramites_hoy = (
        await db.execute(
            select(func.count(Tramite.id)).where(Tramite.fecha_creacion >= inicio, Tramite.fecha_creacion < fin)
        )
    ).scalar() or 0

    # "En curso": esperando pago o resolución (APROBADO/RECHAZADO ya están resueltos)
    pendientes = (
        await db.execute(
            select(func.count(Tramite.id)).where(
                Tramite.estado.in_(
                    [EstadoTramiteEnum.PENDIENTE_PAGO, EstadoTramiteEnum.EN_EVALUACION, EstadoTramiteEnum.OBSERVADO]
                )
            )
        )
    ).scalar() or 0

    recaudacion = (
        await db.execute(
            select(func.sum(Pago.monto)).where(
                Pago.fecha_pago >= inicio, Pago.fecha_pago < fin, Pago.estado == EstadoPagoEnum.COMPLETADO
            )
        )
    ).scalar() or 0

    return {
        "tramitesHoy": tramites_hoy,
        "tramitesPendientes": pendientes,
        "recaudacionHoy": float(recaudacion),
    }


# ===== Recaudación (pagos) =====
def _rango_utc(desde: Optional[date], hasta: Optional[date]):
    """Convierte fechas locales (APP_TIMEZONE, ambas inclusive) a límites UTC naive, como guarda la BD."""
    tz = ZoneInfo(config.APP_TIMEZONE)
    hoy = datetime.now(tz).date()
    hasta = hasta or hoy
    desde = desde or (hasta - timedelta(days=29))
    if desde > hasta:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "La fecha 'desde' no puede ser posterior a 'hasta'.")
    ini = datetime(desde.year, desde.month, desde.day, tzinfo=tz).astimezone(timezone.utc).replace(tzinfo=None)
    fin_local = datetime(hasta.year, hasta.month, hasta.day, tzinfo=tz) + timedelta(days=1)
    return ini, fin_local.astimezone(timezone.utc).replace(tzinfo=None), desde, hasta


async def _consultar_pagos(db, desde, hasta, metodo, estado):
    ini, fin, desde, hasta = _rango_utc(desde, hasta)
    q = (
        select(Pago, Ciudadano)
        .outerjoin(Tramite, Pago.tramite_id == Tramite.id)
        .outerjoin(Deuda, Pago.deuda_id == Deuda.id)
        .join(Ciudadano, Ciudadano.id == func.coalesce(Tramite.ciudadano_id, Deuda.ciudadano_id))
        .where(Pago.fecha_pago >= ini, Pago.fecha_pago < fin)
        .order_by(Pago.fecha_pago.desc(), Pago.id.desc())
        .limit(1000)
    )
    if metodo:
        q = q.where(Pago.metodo == metodo)
    if estado:
        q = q.where(Pago.estado == estado)
    return (await db.execute(q)).all(), desde, hasta


def _vista_pago(p: Pago, c: Ciudadano) -> PagoAdminView:
    datos = PagoHistorial.model_validate(p).model_dump()
    datos.update(
        numero_comprobante=p.numero_comprobante if p.estado == EstadoPagoEnum.COMPLETADO else None,
        ciudadano_nombre=c.nombre,
        ciudadano_dni=c.dni,
    )
    return PagoAdminView(**datos)


@router.get("/pagos")
async def admin_listar_pagos(
    desde: Optional[date] = None,
    hasta: Optional[date] = None,
    metodo: Optional[MetodoPagoEnum] = None,
    estado: Optional[EstadoPagoEnum] = None,
    db: AsyncSession = Depends(get_db_session),
):
    """Pagos del periodo (por defecto, últimos 30 días) con totales por medio de pago."""
    filas, desde, hasta = await _consultar_pagos(db, desde, hasta, metodo, estado)
    pagos = [_vista_pago(p, c) for p, c in filas]
    completados = [p for p in pagos if p.estado == EstadoPagoEnum.COMPLETADO]
    por_metodo = {m.value: 0.0 for m in MetodoPagoEnum}
    for p in completados:
        por_metodo[p.metodo.value] += float(p.monto)
    return {
        "desde": desde, "hasta": hasta,
        "totalRecaudado": round(sum(float(p.monto) for p in completados), 2),
        "cantidadCompletados": len(completados),
        "cantidadRechazados": sum(1 for p in pagos if p.estado == EstadoPagoEnum.FALLIDO),
        "porMetodo": {k: round(v, 2) for k, v in por_metodo.items()},
        "pagos": pagos,
    }


def _celda_csv(valor) -> str:
    """Evita 'inyección de fórmulas' al abrir el CSV en Excel."""
    texto = "" if valor is None else str(valor)
    return "'" + texto if texto[:1] in ("=", "+", "-", "@", "\t", "\r") else texto


@router.get("/pagos/export.csv")
async def admin_exportar_pagos_csv(
    desde: Optional[date] = None,
    hasta: Optional[date] = None,
    metodo: Optional[MetodoPagoEnum] = None,
    estado: Optional[EstadoPagoEnum] = None,
    db: AsyncSession = Depends(get_db_session),
):
    filas, desde, hasta = await _consultar_pagos(db, desde, hasta, metodo, estado)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Comprobante", "Fecha (UTC)", "DNI", "Contribuyente", "Concepto", "Monto S/", "Medio", "Detalle", "Estado", "Transaccion", "Motivo rechazo"])
    for p, c in filas:
        w.writerow([_celda_csv(x) for x in [
            p.numero_comprobante if p.estado == EstadoPagoEnum.COMPLETADO else "",
            p.fecha_pago.strftime("%Y-%m-%d %H:%M:%S"), c.dni, c.nombre, p.concepto, f"{p.monto:.2f}",
            p.metodo.value, p.detalle_metodo, p.estado.value, p.transaccion_id, p.motivo_rechazo,
        ]])
    return Response(
        content="\ufeff" + out.getvalue(),  # BOM: Excel respeta las tildes
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="recaudacion_{desde}_{hasta}.csv"'},
    )


# ===== Reportes de gestión y auditoría =====
def _promedio(valores):
    return round(sum(valores) / len(valores), 1) if valores else None


@router.get("/reportes")
async def reportes(db: AsyncSession = Depends(get_db_session)):
    """Indicadores de gestión: volumen, plazos y tiempos de atención por área."""
    tz = ZoneInfo(config.APP_TIMEZONE)
    hoy = datetime.now(tz).date()
    solicitudes = (await db.execute(select(Solicitud))).scalars().all()
    tramites = (await db.execute(select(Tramite))).scalars().all()

    def resumen_solicitudes(lista):
        cerradas = [s for s in lista if s.estado in ESTADOS_SOLICITUD_CERRADOS and s.fecha_respuesta]
        en_plazo = [s for s in cerradas if s.fecha_respuesta.replace(tzinfo=timezone.utc).astimezone(tz).date() <= s.fecha_limite]
        abiertas = [s for s in lista if s.estado not in ESTADOS_SOLICITUD_CERRADOS]
        return {
            "total": len(lista), "abiertas": len(abiertas), "atendidas": len(cerradas),
            "vencidas": sum(1 for s in abiertas if s.fecha_limite < hoy),
            "en_plazo_pct": round(100 * len(en_plazo) / len(cerradas), 1) if cerradas else None,
            "tiempo_promedio_dias": _promedio([(s.fecha_respuesta - s.fecha_creacion).total_seconds() / 86400 for s in cerradas]),
        }

    por_area = []
    for codigo, nombre in AREAS.items():
        r = resumen_solicitudes([s for s in solicitudes if s.area == codigo])
        tr = [t for t in tramites if area_de_tramite(t.tipo) == codigo]
        por_area.append({
            "area": codigo, "nombre": nombre, **r, "tramites": len(tr),
            "tramites_en_evaluacion": sum(1 for t in tr if t.estado in (EstadoTramiteEnum.EN_EVALUACION, EstadoTramiteEnum.OBSERVADO)),
        })

    def contar(items, clave):
        out = {}
        for i in items:
            k = clave(i)
            out[k] = out.get(k, 0) + 1
        return out

    por_tipo = contar(tramites, lambda t: t.tipo)
    return {
        "solicitudes": {
            **resumen_solicitudes(solicitudes),
            "por_clase": contar(solicitudes, lambda s: s.clase.value),
            "por_estado": contar(solicitudes, lambda s: s.estado.value),
        },
        "tramites": {
            "total": len(tramites),
            "por_estado": contar(tramites, lambda t: t.estado.value),
            "por_tipo": [{"tipo": t.value, "nombre": NOMBRES_TRAMITE[t], "total": n} for t, n in sorted(por_tipo.items(), key=lambda x: -x[1])],
        },
        "por_area": por_area,
    }


@router.get("/auditoria", response_model=List[AuditoriaView])
async def auditoria(
    accion: Optional[str] = Query(default=None, max_length=40),
    q: Optional[str] = Query(default=None, max_length=60),
    limite: int = Query(default=200, ge=1, le=500),
    db: AsyncSession = Depends(get_db_session),
):
    """Quién hizo qué y cuándo (lo más reciente primero)."""
    consulta = select(Auditoria).order_by(Auditoria.id.desc()).limit(limite)
    if accion:
        consulta = consulta.where(Auditoria.accion == accion)
    if q and q.strip():
        like = f"%{q.strip()}%"
        consulta = consulta.where(
            Auditoria.usuario_dni.ilike(like) | Auditoria.usuario_nombre.ilike(like)
            | Auditoria.entidad_id.ilike(like) | Auditoria.detalle.ilike(like)
        )
    return (await db.execute(consulta)).scalars().all()
