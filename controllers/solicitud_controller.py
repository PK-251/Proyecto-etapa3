"""Quejas, reclamos y peticiones: registro, seguimiento, respuesta oficial y plazos."""
import logging
from datetime import datetime, timezone
from typing import List, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

import config
from auth import area_permitida, es_personal, get_personal_actual, get_usuario_actual
from catalogo import (
    AREAS, CATEGORIAS_SOLICITUD, NOMBRES_CLASE, area_de_solicitud, plazo_dias_solicitud, sumar_dias_habiles,
)
from database import get_db_session
from models import (
    ESTADOS_SOLICITUD_CERRADOS, Ciudadano, ClaseSolicitudEnum, EstadoSolicitudEnum, Solicitud, utc_now,
)
from schemas import (
    ComentarioRequest, DerivarRequest, GestionSolicitudRequest, SolicitudAdminResponse, SolicitudCreate, SolicitudResponse,
)
from services import upload_service
from services.auditoria import registrar as auditar
from services.notificaciones import notificar, notificar_admins
from services.rate_limit import RateLimiter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/solicitudes", tags=["Quejas, reclamos y peticiones"])

_limite_registro = RateLimiter(max_events=config.SOLICITUDES_POR_HORA, window_seconds=3600)  # anti-spam por usuario
_limite_comentarios = RateLimiter(max_events=20, window_seconds=3600)


# ===== Utilidades =====
def _hoy():
    return datetime.now(ZoneInfo(config.APP_TIMEZONE)).date()


def _o(clase: ClaseSolicitudEnum) -> str:
    """Terminación de género para los avisos: el reclamo, la queja, la petición."""
    return "o" if clase == ClaseSolicitudEnum.RECLAMO else "a"


def _evento(autor: str, evento: str, texto: Optional[str] = None, visible: bool = True) -> dict:
    return {
        "fecha": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "autor": autor, "evento": evento, "texto": texto, "visible": visible,
    }


def serializar(s: Solicitud, admin: bool = False):
    abierta = s.estado not in ESTADOS_SOLICITUD_CERRADOS
    dias = (s.fecha_limite - _hoy()).days if abierta else None
    historial = [e for e in (s.historial or []) if admin or e.get("visible", True)]
    datos = {
        "id": s.id, "codigo": s.codigo, "clase": s.clase, "clase_nombre": NOMBRES_CLASE[s.clase],
        "area": s.area, "area_nombre": AREAS.get(s.area or "", None),
        "categoria": s.categoria, "categoria_nombre": CATEGORIAS_SOLICITUD[s.clase].get(s.categoria, s.categoria),
        "asunto": s.asunto, "descripcion": s.descripcion, "ubicacion": s.ubicacion, "estado": s.estado,
        "fecha_limite": s.fecha_limite, "dias_restantes": dias, "vencida": abierta and dias is not None and dias < 0,
        "respuesta": s.respuesta, "respondido_por": s.respondido_por, "fecha_respuesta": s.fecha_respuesta,
        "historial": historial,
        "documentos": [
            {"nombre": d["nombre"], "url": f"/api/v1/solicitudes/{s.id}/documentos/{d['archivo']}"}
            for d in (s.documentos or [])
        ],
        "fecha_creacion": s.fecha_creacion, "fecha_actualizacion": s.fecha_actualizacion,
    }
    if admin:
        datos.update(
            ciudadano_nombre=s.ciudadano.nombre, ciudadano_dni=s.ciudadano.dni,
            ciudadano_telefono=s.ciudadano.telefono, ciudadano_email=s.ciudadano.email,
        )
        return SolicitudAdminResponse.model_validate(datos)
    return SolicitudResponse.model_validate(datos)


async def _cargar(db: AsyncSession, solicitud_id: int, usuario: Ciudadano) -> Solicitud:
    s = (
        await db.execute(select(Solicitud).options(selectinload(Solicitud.ciudadano)).where(Solicitud.id == solicitud_id))
    ).scalar_one_or_none()
    # 404 también para ajenos: no se revela qué solicitudes existen
    if not s or (s.ciudadano_id != usuario.id and not (es_personal(usuario) and area_permitida(usuario, s.area))):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Solicitud no encontrada.")
    return s


# ===== Información pública =====
@router.get("/categorias")
async def categorias(_: Ciudadano = Depends(get_usuario_actual)):
    """Tipos de solicitud, categorías y plazos de atención (días hábiles)."""
    return [
        {
            "clase": clase.value,
            "nombre": NOMBRES_CLASE[clase],
            "categorias": [
                {"id": cid, "nombre": nombre, "plazo_dias": plazo_dias_solicitud(clase, cid)}
                for cid, nombre in cats.items()
            ],
        }
        for clase, cats in CATEGORIAS_SOLICITUD.items()
    ]


# ===== Ciudadano =====
@router.post("/", response_model=SolicitudResponse, status_code=status.HTTP_201_CREATED)
async def registrar(
    datos: SolicitudCreate,
    db: AsyncSession = Depends(get_db_session),
    usuario: Ciudadano = Depends(get_usuario_actual),
):
    if not _limite_registro.check_and_hit(str(usuario.id)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Ha registrado demasiadas solicitudes. Intente más tarde.")
    limite = sumar_dias_habiles(_hoy(), plazo_dias_solicitud(datos.clase, datos.categoria))
    s = Solicitud(
        ciudadano_id=usuario.id, clase=datos.clase, categoria=datos.categoria, asunto=datos.asunto,
        descripcion=datos.descripcion, ubicacion=datos.ubicacion or None, estado=EstadoSolicitudEnum.RECIBIDA,
        area=area_de_solicitud(datos.categoria), fecha_limite=limite, historial=[_evento(usuario.nombre, "Registrada", "Su solicitud fue recibida.")], documentos=[],
    )
    db.add(s)
    await db.flush()
    nombre = NOMBRES_CLASE[s.clase]
    await notificar(
        db, usuario.id, s.clase.value, f"{nombre} registrad{_o(s.clase)}",
        f"Su código de seguimiento es {s.codigo}. Plazo de atención: hasta el {limite:%d/%m/%Y}.", f"solicitud:{s.id}",
    )
    await notificar_admins(db, s.clase.value, f"Nuev{_o(s.clase)} {nombre.lower()}: {s.codigo}", s.asunto, f"solicitud:{s.id}", excepto_id=usuario.id, area=s.area)
    await db.refresh(s)
    logger.info("%s %s registrada por %s", nombre, s.codigo, usuario.dni)
    return serializar(s)


@router.get("/mias", response_model=List[SolicitudResponse])
async def mis_solicitudes(
    clase: Optional[ClaseSolicitudEnum] = None,
    db: AsyncSession = Depends(get_db_session),
    usuario: Ciudadano = Depends(get_usuario_actual),
):
    q = select(Solicitud).where(Solicitud.ciudadano_id == usuario.id).order_by(Solicitud.fecha_creacion.desc(), Solicitud.id.desc())
    if clase:
        q = q.where(Solicitud.clase == clase)
    return [serializar(s) for s in (await db.execute(q.limit(200))).scalars().all()]


# ===== Administración (van antes de /{id}) =====
@router.get("/admin/all", response_model=List[SolicitudAdminResponse])
async def todas(
    clase: Optional[ClaseSolicitudEnum] = None,
    estado: Optional[EstadoSolicitudEnum] = None,
    vencidas: bool = False,
    q: Optional[str] = Query(default=None, max_length=60),
    area: Optional[str] = Query(default=None, max_length=30),
    db: AsyncSession = Depends(get_db_session),
    usuario: Ciudadano = Depends(get_personal_actual),
):
    consulta = select(Solicitud).options(selectinload(Solicitud.ciudadano)).join(Ciudadano, Solicitud.ciudadano_id == Ciudadano.id)
    if usuario.role != "admin":
        consulta = consulta.where(Solicitud.area == usuario.area)  # el funcionario solo ve su área
    elif area:
        consulta = consulta.where(Solicitud.area == area)
    if clase:
        consulta = consulta.where(Solicitud.clase == clase)
    if estado:
        consulta = consulta.where(Solicitud.estado == estado)
    if vencidas:
        consulta = consulta.where(Solicitud.estado.notin_(ESTADOS_SOLICITUD_CERRADOS), Solicitud.fecha_limite < _hoy())
    if q and q.strip():
        like = f"%{q.strip()}%"
        consulta = consulta.where(or_(Solicitud.codigo.ilike(like), Solicitud.asunto.ilike(like), Ciudadano.dni.ilike(like), Ciudadano.nombre.ilike(like)))
    # Las más urgentes primero: abiertas por fecha límite, luego cerradas
    consulta = consulta.order_by(Solicitud.estado.in_(ESTADOS_SOLICITUD_CERRADOS), Solicitud.fecha_limite, Solicitud.id.desc())
    return [serializar(s, admin=True) for s in (await db.execute(consulta.limit(300))).scalars().all()]


@router.get("/admin/resumen")
async def resumen(db: AsyncSession = Depends(get_db_session), usuario: Ciudadano = Depends(get_personal_actual)):
    solo_area = [] if usuario.role == "admin" else [Solicitud.area == usuario.area]
    por_estado = dict((await db.execute(select(Solicitud.estado, func.count()).where(*solo_area).group_by(Solicitud.estado))).all())
    vencidas = (
        await db.execute(
            select(func.count()).select_from(Solicitud).where(
                Solicitud.estado.notin_(ESTADOS_SOLICITUD_CERRADOS), Solicitud.fecha_limite < _hoy(), *solo_area
            )
        )
    ).scalar()
    return {
        "recibidas": por_estado.get(EstadoSolicitudEnum.RECIBIDA, 0),
        "en_atencion": por_estado.get(EstadoSolicitudEnum.EN_ATENCION, 0),
        "atendidas": por_estado.get(EstadoSolicitudEnum.ATENDIDA, 0),
        "improcedentes": por_estado.get(EstadoSolicitudEnum.IMPROCEDENTE, 0),
        "vencidas": vencidas,
    }


@router.put("/{solicitud_id}/gestionar", response_model=SolicitudAdminResponse)
async def gestionar(
    solicitud_id: int,
    req: GestionSolicitudRequest,
    db: AsyncSession = Depends(get_db_session),
    admin: Ciudadano = Depends(get_personal_actual),
):
    s = await _cargar(db, solicitud_id, admin)
    if s.estado in ESTADOS_SOLICITUD_CERRADOS:
        raise HTTPException(status.HTTP_409_CONFLICT, "La solicitud ya fue cerrada con una respuesta oficial.")
    if req.estado == EstadoSolicitudEnum.RECIBIDA:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No se puede regresar una solicitud a 'recibida'.")

    respuesta = (req.respuesta or "").strip()
    nota = (req.nota_interna or "").strip()
    cierra = req.estado in ESTADOS_SOLICITUD_CERRADOS
    if cierra and len(respuesta) < 10:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Debe redactar la respuesta oficial (mín. 10 caracteres) para cerrar la solicitud.")

    nombre = NOMBRES_CLASE[s.clase]
    historial = list(s.historial or [])
    if nota:
        historial.append(_evento(admin.nombre, "Nota interna", nota, visible=False))

    if cierra:
        s.respuesta, s.respondido_por, s.fecha_respuesta = respuesta, admin.nombre, utc_now()
        evento = "Respuesta oficial" if req.estado == EstadoSolicitudEnum.ATENDIDA else "Declarada improcedente"
        historial.append(_evento(admin.nombre, evento, respuesta))
        titulo = f"{nombre} {'atendid' + _o(s.clase) if req.estado == EstadoSolicitudEnum.ATENDIDA else 'improcedente'}: {s.codigo}"
        mensaje = "Ya tiene respuesta oficial. Ábrala para leerla."
    else:
        if s.estado != req.estado:
            historial.append(_evento(admin.nombre, "En atención", respuesta or "Su solicitud está siendo atendida por el área responsable."))
        elif respuesta:
            historial.append(_evento(admin.nombre, "Actualización", respuesta))
        titulo, mensaje = f"{nombre} en atención: {s.codigo}", respuesta or "Su solicitud está siendo atendida."

    await auditar(db, admin, "SOLICITUD_" + req.estado.value, "solicitud", s.codigo, (respuesta or nota)[:200] or None)
    s.estado = req.estado
    s.historial = historial  # lista nueva: SQLAlchemy detecta el cambio del JSON
    if cierra or respuesta or req.estado != EstadoSolicitudEnum.RECIBIDA:
        await notificar(db, s.ciudadano_id, s.clase.value, titulo, mensaje, f"solicitud:{s.id}")
    await db.flush()
    logger.info("%s %s -> %s (por %s)", nombre, s.codigo, req.estado.value, admin.dni)
    return serializar(s, admin=True)


@router.put("/{solicitud_id}/derivar", response_model=SolicitudAdminResponse)
async def derivar(
    solicitud_id: int,
    req: DerivarRequest,
    db: AsyncSession = Depends(get_db_session),
    admin: Ciudadano = Depends(get_personal_actual),
):
    """Deriva el caso a otra área (el ciudadano ve en su seguimiento que fue derivado)."""
    s = await _cargar(db, solicitud_id, admin)
    if s.estado in ESTADOS_SOLICITUD_CERRADOS:
        raise HTTPException(status.HTTP_409_CONFLICT, "La solicitud ya fue cerrada: no se puede derivar.")
    if req.area not in AREAS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Área no válida.")
    if req.area == s.area:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "La solicitud ya está en esa área.")
    anterior = AREAS.get(s.area or "", "—")
    s.area = req.area
    s.historial = [*(s.historial or []), _evento(admin.nombre, "Derivada", f"Su caso fue derivado a {AREAS[req.area]}.")]
    s.historial.append(_evento(admin.nombre, "Motivo de derivación", req.motivo, visible=False))
    await auditar(db, admin, "SOLICITUD_DERIVADA", "solicitud", s.codigo, f"{anterior} -> {AREAS[req.area]}: {req.motivo}")
    await notificar(db, s.ciudadano_id, s.clase.value, f"Caso derivado: {s.codigo}",
                    f"Su caso pasó al área de {AREAS[req.area]}, que continuará la atención.", f"solicitud:{s.id}")
    await notificar_admins(db, s.clase.value, f"Caso derivado a su área: {s.codigo}", s.asunto, f"solicitud:{s.id}",
                           excepto_id=admin.id, area=s.area)
    await db.flush()
    return serializar(s, admin=True)


# ===== Detalle / adjuntos / comentarios =====
@router.get("/{solicitud_id}", response_model=None)  # el tipo depende de quién consulta (admin o titular)
async def detalle(solicitud_id: int, db: AsyncSession = Depends(get_db_session), usuario: Ciudadano = Depends(get_usuario_actual)):
    s = await _cargar(db, solicitud_id, usuario)
    # El personal ve también las notas internas y los datos de contacto; el titular, solo lo que le corresponde
    return serializar(s, admin=es_personal(usuario) and s.ciudadano_id != usuario.id)


@router.post("/{solicitud_id}/adjuntos", response_model=SolicitudResponse)
async def adjuntar(
    solicitud_id: int,
    files: List[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db_session),
    usuario: Ciudadano = Depends(get_usuario_actual),
):
    s = await _cargar(db, solicitud_id, usuario)
    if s.ciudadano_id != usuario.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Solicitud no encontrada.")
    if s.estado in ESTADOS_SOLICITUD_CERRADOS:
        raise HTTPException(status.HTTP_409_CONFLICT, "La solicitud ya está cerrada y no admite más adjuntos.")
    existentes = list(s.documentos or [])
    if len(existentes) + len(files) > config.MAX_FILES_PER_TRAMITE:
        raise HTTPException(400, f"Se admiten como máximo {config.MAX_FILES_PER_TRAMITE} adjuntos.")
    guardados = []
    try:
        for f in files:
            guardados.append(await upload_service.guardar_documento(f))
    except BaseException:
        upload_service.borrar_documentos(guardados)
        raise
    s.documentos = existentes + guardados
    s.historial = [*(s.historial or []), _evento(usuario.nombre, "Adjuntos agregados", ", ".join(g["nombre"] for g in guardados))]
    await db.flush()
    await db.refresh(s)
    return serializar(s)


@router.get("/{solicitud_id}/documentos/{archivo}")
async def descargar(
    solicitud_id: int, archivo: str,
    db: AsyncSession = Depends(get_db_session), usuario: Ciudadano = Depends(get_usuario_actual),
):
    s = await _cargar(db, solicitud_id, usuario)
    doc = next((d for d in (s.documentos or []) if d["archivo"] == archivo), None)
    ruta = upload_service.ruta_documento(archivo)
    if not doc or not upload_service.nombre_archivo_valido(archivo) or not ruta.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Documento no encontrado.")
    return FileResponse(ruta, media_type=upload_service.content_type_de(archivo), filename=doc["nombre"], headers={"X-Content-Type-Options": "nosniff"})


@router.post("/{solicitud_id}/comentarios", response_model=SolicitudResponse)
async def comentar(
    solicitud_id: int, req: ComentarioRequest,
    db: AsyncSession = Depends(get_db_session), usuario: Ciudadano = Depends(get_usuario_actual),
):
    """El ciudadano agrega información mientras la solicitud sigue abierta."""
    s = await _cargar(db, solicitud_id, usuario)
    if s.ciudadano_id != usuario.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Solicitud no encontrada.")
    if s.estado in ESTADOS_SOLICITUD_CERRADOS:
        raise HTTPException(status.HTTP_409_CONFLICT, "La solicitud ya está cerrada.")
    if not _limite_comentarios.check_and_hit(str(usuario.id)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Demasiados comentarios. Intente más tarde.")
    s.historial = [*(s.historial or []), _evento(usuario.nombre, "Comentario del ciudadano", req.texto)]
    await notificar_admins(db, s.clase.value, f"Nuevo comentario en {s.codigo}", req.texto[:200], f"solicitud:{s.id}", excepto_id=usuario.id, area=s.area)
    await db.flush()
    await db.refresh(s)
    return serializar(s)
