from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from auth import get_usuario_actual
from database import get_db_session
from models import Ciudadano, Notificacion
from schemas import NotificacionesListado

router = APIRouter(prefix="/api/v1/notificaciones", tags=["Notificaciones"])


async def _no_leidas(db: AsyncSession, usuario_id: int) -> int:
    return (
        await db.execute(
            select(func.count()).select_from(Notificacion).where(Notificacion.ciudadano_id == usuario_id, Notificacion.leida.is_(False))
        )
    ).scalar()


@router.get("/", response_model=NotificacionesListado)
async def listar(
    limite: int = Query(default=30, ge=1, le=100),
    db: AsyncSession = Depends(get_db_session),
    usuario: Ciudadano = Depends(get_usuario_actual),
):
    items = (
        await db.execute(
            select(Notificacion).where(Notificacion.ciudadano_id == usuario.id)
            .order_by(Notificacion.fecha.desc(), Notificacion.id.desc()).limit(limite)
        )
    ).scalars().all()
    return {"no_leidas": await _no_leidas(db, usuario.id), "items": items}


@router.get("/contador")
async def contador(db: AsyncSession = Depends(get_db_session), usuario: Ciudadano = Depends(get_usuario_actual)):
    return {"no_leidas": await _no_leidas(db, usuario.id)}


@router.post("/leer-todas")
async def leer_todas(db: AsyncSession = Depends(get_db_session), usuario: Ciudadano = Depends(get_usuario_actual)):
    await db.execute(
        update(Notificacion).where(Notificacion.ciudadano_id == usuario.id, Notificacion.leida.is_(False)).values(leida=True)
    )
    return {"no_leidas": 0}


@router.post("/{notificacion_id}/leida")
async def marcar_leida(
    notificacion_id: int, db: AsyncSession = Depends(get_db_session), usuario: Ciudadano = Depends(get_usuario_actual)
):
    res = await db.execute(
        update(Notificacion).where(Notificacion.id == notificacion_id, Notificacion.ciudadano_id == usuario.id).values(leida=True)
    )
    if res.rowcount != 1:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notificación no encontrada.")
    return {"no_leidas": await _no_leidas(db, usuario.id)}
