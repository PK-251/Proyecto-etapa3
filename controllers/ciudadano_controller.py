import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from auth import get_admin_actual
from database import get_db_session
from models import Ciudadano
from schemas import Ciudadano as CiudadanoSchema
from security import get_password_hash
from services.integrations import IntegracionReniec

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/api/v1/ciudadanos",
    tags=["Ciudadanos"],
    dependencies=[Depends(get_admin_actual)],  # consulta de identidades: solo personal autorizado
)


@router.get("/validar/{dni}", response_model=CiudadanoSchema)
async def validar_dni_reniec(dni: str, db: AsyncSession = Depends(get_db_session)):
    """HU-014: busca en la BD local; si no existe, consulta RENIEC (simulado) y lo registra."""
    if not dni.isdigit() or len(dni) != 8:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "El DNI debe contener 8 dígitos numéricos.")

    existente = (await db.execute(select(Ciudadano).where(Ciudadano.dni == dni))).scalar_one_or_none()
    if existente:
        return existente

    reniec = await IntegracionReniec.validar_dni(dni)
    if not reniec.success or not reniec.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No se encontró al ciudadano en RENIEC.")

    nuevo = Ciudadano(
        dni=reniec.data.dni,
        nombre=reniec.data.nombre,
        direccion=reniec.data.direccion,
        # Sin contraseña utilizable: el ciudadano deberá pedir que un admin se la asigne.
        hashed_password=get_password_hash(secrets.token_urlsafe(24)),
        role="ciudadano",
    )
    db.add(nuevo)
    await db.flush()
    await db.refresh(nuevo)
    logger.info("Ciudadano %s registrado desde RENIEC", dni)
    return nuevo
