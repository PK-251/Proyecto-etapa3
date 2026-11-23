import logging
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

import config
from auth import area_permitida, es_admin, es_personal, get_personal_actual, get_usuario_actual
from database import get_db_session
from catalogo import CATALOGO_TRAMITES, area_de_tramite, catalogo_publico, validar_detalles
from models import (
    NOMBRES_TRAMITE, Ciudadano, Deuda, EstadoDeudaEnum, EstadoPagoEnum, EstadoTramiteEnum, Pago, Tramite, utc_now,
)
from services.auditoria import registrar as auditar
from services.notificaciones import notificar
from schemas import (
    ActualizarEstadoRequest, EventoSeguimiento, Tramite as TramiteSchema, TramiteAdminResponse, TramiteCreate,
)
from services import upload_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/tramites", tags=["Trámites"])


# ===== Utilidades =====
def _url_documento(tramite_id: int, archivo: str) -> str:
    return f"/api/v1/tramites/{tramite_id}/documentos/{archivo}"


def serializar(tramite: Tramite, admin: bool = False):
    """Convierte el modelo a schema; los documentos se exponen como enlaces autenticados."""
    datos = {
        "id": tramite.id,
        "expediente": tramite.expediente,
        "tipo": tramite.tipo,
        "estado": tramite.estado,
        "costo_total": tramite.costo_total,
        "ciudadano_id": tramite.ciudadano_id,
        "detalles": tramite.detalles,
        "observaciones": tramite.observaciones or [],
        "documentos": [
            {"nombre": d["nombre"], "url": _url_documento(tramite.id, d["archivo"])}
            for d in (tramite.documentos or [])
        ],
        "fecha_creacion": tramite.fecha_creacion,
        "fecha_actualizacion": tramite.fecha_actualizacion,
    }
    if admin:
        datos["ciudadano_nombre"] = tramite.ciudadano.nombre
        datos["ciudadano_dni"] = tramite.ciudadano.dni
        return TramiteAdminResponse.model_validate(datos)
    return TramiteSchema.model_validate(datos)


def _personal_ve(usuario: Ciudadano, tramite: Tramite) -> bool:
    """Personal municipal con permiso sobre el área del trámite (el administrador ve todos)."""
    return es_personal(usuario) and area_permitida(usuario, area_de_tramite(tramite.tipo))


async def _tramite_accesible(db: AsyncSession, tramite_id: int, usuario: Ciudadano) -> Tramite:
    tramite = (await db.execute(select(Tramite).where(Tramite.id == tramite_id))).scalar_one_or_none()
    # 404 para ajenos: no se revela qué trámites existen
    if not tramite or (tramite.ciudadano_id != usuario.id and not _personal_ve(usuario, tramite)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trámite no encontrado.")
    return tramite


async def _deudas_pendientes(db: AsyncSession, ciudadano_id: int) -> int:
    from sqlalchemy import func
    return (
        await db.execute(
            select(func.count()).select_from(Deuda).where(
                Deuda.ciudadano_id == ciudadano_id,
                Deuda.estado.in_([EstadoDeudaEnum.PENDIENTE, EstadoDeudaEnum.VENCIDO]),
            )
        )
    ).scalar()


# ===== Catálogo =====
@router.get("/catalogo")
async def catalogo(_: Ciudadano = Depends(get_usuario_actual)):
    """Trámites disponibles con requisitos, costo, plazo de atención y campos a completar."""
    return catalogo_publico()


# ===== Ciudadano =====
@router.post("/", response_model=TramiteSchema, status_code=status.HTTP_201_CREATED)
async def crear_tramite(
    tramite_in: TramiteCreate,
    db: AsyncSession = Depends(get_db_session),
    usuario: Ciudadano = Depends(get_usuario_actual),
):
    """Paso 1: crea el expediente. El costo y el nº de expediente los asigna el servidor."""
    titular = usuario
    if tramite_in.dni_ciudadano and tramite_in.dni_ciudadano != usuario.dni:
        if not es_admin(usuario):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo puede crear trámites a su propio nombre.")
        titular = (
            await db.execute(select(Ciudadano).where(Ciudadano.dni == tramite_in.dni_ciudadano))
        ).scalar_one_or_none()
        if not titular:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Ciudadano no encontrado.")

    try:
        detalles = validar_detalles(tramite_in.tipo, tramite_in.detalles)
    except ValueError as e:
        raise HTTPException(422, str(e))
    if CATALOGO_TRAMITES.get(tramite_in.tipo, {}).get("valida_deudas") and await _deudas_pendientes(db, titular.id):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Tiene deudas pendientes con la municipalidad. Cancélelas en 'Mis deudas' para solicitar este documento.",
        )

    tramite = Tramite(
        ciudadano_id=titular.id,
        tipo=tramite_in.tipo,
        estado=EstadoTramiteEnum.PENDIENTE_PAGO,
        detalles=detalles or None,
        observaciones=[],
        documentos=[],
    )
    db.add(tramite)
    await db.flush()
    await db.refresh(tramite)
    await notificar(
        db, titular.id, "TRAMITE", "Trámite registrado",
        f"Expediente {tramite.expediente} ({NOMBRES_TRAMITE[tramite.tipo]}). Complete el pago para iniciar la evaluación.",
        f"tramite:{tramite.id}",
    )
    logger.info("Trámite %s creado", tramite.expediente)
    return serializar(tramite)


@router.post("/{tramite_id}/upload-documentos", response_model=TramiteSchema)
async def upload_documentos(
    tramite_id: int,
    files: List[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db_session),
    usuario: Ciudadano = Depends(get_usuario_actual),
):
    """Paso 2: adjunta documentos (PDF/JPG/PNG, máx. configurable). Solo el titular, y antes del pago."""
    tramite = (await db.execute(select(Tramite).where(Tramite.id == tramite_id))).scalar_one_or_none()
    if not tramite or tramite.ciudadano_id != usuario.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trámite no encontrado.")
    if tramite.estado != EstadoTramiteEnum.PENDIENTE_PAGO:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Este trámite está en estado {tramite.estado.value} y no puede recibir documentos.",
        )

    existentes = list(tramite.documentos or [])
    if len(existentes) + len(files) > config.MAX_FILES_PER_TRAMITE:
        raise HTTPException(400, f"Un trámite admite como máximo {config.MAX_FILES_PER_TRAMITE} documentos.")

    guardados = []
    try:
        for f in files:
            guardados.append(await upload_service.guardar_documento(f))
    except BaseException:
        upload_service.borrar_documentos(guardados)  # todo o nada
        raise

    # Lista NUEVA (no mutar la existente): así SQLAlchemy detecta el cambio en la columna JSON
    tramite.documentos = existentes + guardados
    await db.flush()
    await db.refresh(tramite)
    return serializar(tramite)


@router.get("/{tramite_id}/documentos/{archivo}")
async def descargar_documento(
    tramite_id: int,
    archivo: str,
    db: AsyncSession = Depends(get_db_session),
    usuario: Ciudadano = Depends(get_usuario_actual),
):
    """Descarga autenticada de un documento adjunto (titular o admin)."""
    tramite = await _tramite_accesible(db, tramite_id, usuario)
    doc = next((d for d in (tramite.documentos or []) if d["archivo"] == archivo), None)
    ruta = upload_service.ruta_documento(archivo)
    if not doc or not upload_service.nombre_archivo_valido(archivo) or not ruta.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Documento no encontrado.")
    return FileResponse(
        ruta,
        media_type=upload_service.content_type_de(archivo),
        filename=doc["nombre"],
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.get("/expediente/{expediente_nro}", response_model=TramiteSchema)
async def consultar_por_expediente(
    expediente_nro: str,
    db: AsyncSession = Depends(get_db_session),
    usuario: Ciudadano = Depends(get_usuario_actual),
):
    tramite = (
        await db.execute(select(Tramite).where(Tramite.expediente == expediente_nro))
    ).scalar_one_or_none()
    if not tramite or (tramite.ciudadano_id != usuario.id and not _personal_ve(usuario, tramite)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Expediente {expediente_nro} no encontrado.")
    return serializar(tramite)


@router.get("/usuario/{dni}", response_model=List[TramiteSchema])
async def tramites_por_usuario(
    dni: str,
    db: AsyncSession = Depends(get_db_session),
    usuario: Ciudadano = Depends(get_usuario_actual),
):
    if dni != usuario.dni and not es_admin(usuario):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo puede ver sus propios trámites.")
    ciudadano = (await db.execute(select(Ciudadano).where(Ciudadano.dni == dni))).scalar_one_or_none()
    if not ciudadano:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Ciudadano con DNI {dni} no encontrado.")
    tramites = (
        await db.execute(
            select(Tramite).where(Tramite.ciudadano_id == ciudadano.id).order_by(Tramite.fecha_creacion.desc())
        )
    ).scalars().all()
    return [serializar(t) for t in tramites]


@router.get("/{tramite_id}/seguimiento", response_model=List[EventoSeguimiento])
async def seguimiento(
    tramite_id: int,
    db: AsyncSession = Depends(get_db_session),
    usuario: Ciudadano = Depends(get_usuario_actual),
):
    """Línea de tiempo del expediente: registro, pagos y cambios de estado."""
    tramite = await _tramite_accesible(db, tramite_id, usuario)
    pagos = (
        await db.execute(select(Pago).where(Pago.tramite_id == tramite.id, Pago.estado == EstadoPagoEnum.COMPLETADO))
    ).scalars().all()
    eventos = [{"fecha": tramite.fecha_creacion, "titulo": "Trámite registrado", "detalle": f"Expediente {tramite.expediente}", "tipo": "creacion"}]
    for p in pagos:
        eventos.append({
            "fecha": p.fecha_pago, "titulo": "Pago recibido", "tipo": "pago",
            "detalle": f"S/ {p.monto:.2f} - Boleta {p.numero_comprobante}. El trámite pasó a evaluación.",
        })
    for o in tramite.observaciones or []:
        try:
            fecha = datetime.strptime(o["fecha"], "%Y-%m-%d %H:%M UTC")
        except (KeyError, ValueError):
            fecha = tramite.fecha_actualizacion
        eventos.append({"fecha": fecha, "titulo": f"Estado: {o['estado'].replace('_', ' ').title()}", "detalle": o.get("texto"), "tipo": "observacion"})
    # Las observaciones guardan la hora al minuto: se ordena al minuto y, en empate, por orden lógico del proceso
    orden = {"creacion": 0, "pago": 1, "observacion": 2}
    eventos.sort(key=lambda e: (e["fecha"].replace(second=0, microsecond=0), orden[e["tipo"]], e["fecha"]))
    return eventos


# ===== Administrador =====
@router.get("/admin/all", response_model=List[TramiteAdminResponse])
async def todos_los_tramites(
    db: AsyncSession = Depends(get_db_session), usuario: Ciudadano = Depends(get_personal_actual)
):
    """HU-005: trámites (el funcionario solo ve los de su área)."""
    tramites = (
        await db.execute(
            select(Tramite).options(selectinload(Tramite.ciudadano)).order_by(Tramite.fecha_creacion.desc())
        )
    ).scalars().all()
    return [serializar(t, admin=True) for t in tramites if _personal_ve(usuario, t)]


@router.get("/{tramite_id}", response_model=TramiteAdminResponse)
async def tramite_por_id(
    tramite_id: int, db: AsyncSession = Depends(get_db_session), usuario: Ciudadano = Depends(get_personal_actual)
):
    tramite = (
        await db.execute(
            select(Tramite).options(selectinload(Tramite.ciudadano)).where(Tramite.id == tramite_id)
        )
    ).scalar_one_or_none()
    if not tramite or not _personal_ve(usuario, tramite):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Trámite con ID {tramite_id} no encontrado.")
    return serializar(tramite, admin=True)


@router.put("/{tramite_id}/estado", response_model=TramiteAdminResponse)
async def actualizar_estado(
    tramite_id: int,
    req: ActualizarEstadoRequest,
    db: AsyncSession = Depends(get_db_session),
    admin: Ciudadano = Depends(get_personal_actual),
):
    """HU-005: cambia el estado y registra la observación en el historial."""
    tramite = (
        await db.execute(
            select(Tramite).options(selectinload(Tramite.ciudadano)).where(Tramite.id == tramite_id)
        )
    ).scalar_one_or_none()
    if not tramite or not _personal_ve(admin, tramite):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Trámite con ID {tramite_id} no encontrado.")

    if tramite.estado == EstadoTramiteEnum.PENDIENTE_PAGO:
        raise HTTPException(status.HTTP_409_CONFLICT, "El trámite aún no fue pagado: no se puede evaluar.")
    if req.estado == EstadoTramiteEnum.PENDIENTE_PAGO:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No se puede regresar un trámite a 'pendiente de pago'.")

    texto = (req.observaciones or "").strip()
    if req.estado in (EstadoTramiteEnum.OBSERVADO, EstadoTramiteEnum.RECHAZADO) and not texto:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Debe indicar el motivo para observar o rechazar el trámite.")

    if (
        req.estado == EstadoTramiteEnum.APROBADO
        and CATALOGO_TRAMITES.get(tramite.tipo, {}).get("valida_deudas")
        and await _deudas_pendientes(db, tramite.ciudadano_id)
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "El ciudadano registra deudas pendientes: no se puede emitir la constancia de no adeudo.",
        )

    estado_anterior = tramite.estado
    tramite.estado = req.estado
    await auditar(db, admin, "TRAMITE_ESTADO", "tramite", tramite.expediente, f"{estado_anterior.value} -> {req.estado.value}" + (f": {texto}" if texto else ""))
    if estado_anterior != req.estado or texto:
        await notificar(
            db, tramite.ciudadano_id, "TRAMITE",
            f"Trámite {req.estado.value.replace('_', ' ').lower()}",
            f"Expediente {tramite.expediente}." + (f" {texto}" if texto else ""),
            f"tramite:{tramite.id}",
        )
    if texto:
        tramite.observaciones = [
            *(tramite.observaciones or []),
            {
                "fecha": utc_now().strftime("%Y-%m-%d %H:%M UTC"),
                "autor": admin.nombre,
                "estado": req.estado.value,
                "texto": texto,
            },
        ]
    await db.flush()
    logger.info("Trámite %s -> %s (por %s)", tramite.expediente, req.estado.value, admin.dni)
    return serializar(tramite, admin=True)
