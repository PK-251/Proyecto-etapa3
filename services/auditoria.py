"""Registro de auditoría: se guarda junto con el cambio que lo origina (misma transacción)."""
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from models import Auditoria, Ciudadano


async def registrar(
    db: AsyncSession, usuario: Optional[Ciudadano], accion: str, entidad: str | None = None,
    entidad_id: object = None, detalle: str | None = None,
) -> None:
    db.add(Auditoria(
        usuario_dni=usuario.dni if usuario else None,
        usuario_nombre=usuario.nombre if usuario else None,
        accion=accion[:40], entidad=entidad, entidad_id=None if entidad_id is None else str(entidad_id)[:40],
        detalle=(detalle or "")[:500] or None,
    ))
