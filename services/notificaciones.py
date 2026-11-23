"""Avisos dentro del portal. Se agregan a la sesión actual: se guardan junto con el cambio que los origina."""
from typing import Iterable

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

import config
from models import Ciudadano, Notificacion
from services.mensajeria import encolar


async def notificar(db: AsyncSession, ciudadano_id: int, tipo: str, titulo: str, mensaje: str, referencia: str | None = None) -> None:
    db.add(Notificacion(
        ciudadano_id=ciudadano_id, tipo=tipo, titulo=titulo[:120], mensaje=mensaje[:500], referencia=referencia,
    ))
    if config.EMAIL_ACTIVO:
        email = (await db.execute(select(Ciudadano.email).where(Ciudadano.id == ciudadano_id))).scalar_one_or_none()
        if email:
            encolar(db, "correo", email, titulo[:120], f"{titulo}\n\n{mensaje}\n\nIngrese al portal para ver el detalle.")


async def notificar_admins(db: AsyncSession, tipo: str, titulo: str, mensaje: str, referencia: str | None = None, excepto_id: int | None = None, area: str | None = None) -> None:
    if config.WHATSAPP_ACTIVO:  # un solo WhatsApp al número configurado, no uno por administrador
        encolar(db, "whatsapp", f"{config.MUNI_NOMBRE}\n{titulo}\n{mensaje}")
    # Administradores siempre; funcionarios solo del área responsable (o todos si no se indica área)
    filtro = Ciudadano.role == "admin"
    if area is None:
        filtro = Ciudadano.role.in_(("admin", "funcionario"))
    else:
        filtro = (Ciudadano.role == "admin") | ((Ciudadano.role == "funcionario") & (Ciudadano.area == area))
    admins: Iterable[int] = (await db.execute(select(Ciudadano.id).where(filtro))).scalars().all()
    for admin_id in admins:
        if admin_id != excepto_id:
            await notificar(db, admin_id, tipo, titulo, mensaje, referencia)
