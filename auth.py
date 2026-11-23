from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

import config
from database import get_db_session
from models import Ciudadano
from security import verificar_password  # noqa: F401  (re-export)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/login")


def crear_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=config.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode["exp"] = expire
    return jwt.encode(to_encode, config.SECRET_KEY, algorithm=config.ALGORITHM)


async def get_usuario_actual(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db_session),
) -> Ciudadano:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No se pudieron validar las credenciales",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, config.SECRET_KEY, algorithms=[config.ALGORITHM])
        dni = payload.get("sub")
        if not dni:
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception

    result = await db.execute(select(Ciudadano).where(Ciudadano.dni == dni))
    user = result.scalar_one_or_none()
    if user is None:
        raise credentials_exception
    return user


async def get_admin_actual(current_user: Ciudadano = Depends(get_usuario_actual)) -> Ciudadano:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso denegado: se requieren permisos de administrador.",
        )
    return current_user


def es_admin(usuario: Ciudadano) -> bool:
    return usuario.role == "admin"


ROLES_PERSONAL = ("admin", "funcionario")


def es_personal(usuario: Ciudadano) -> bool:
    """Administrador o funcionario municipal."""
    return usuario.role in ROLES_PERSONAL


def area_permitida(usuario: Ciudadano, area: Optional[str]) -> bool:
    """El administrador ve todo; el funcionario solo los casos de su área."""
    return usuario.role == "admin" or (usuario.role == "funcionario" and bool(usuario.area) and usuario.area == area)


async def get_personal_actual(current_user: Ciudadano = Depends(get_usuario_actual)) -> Ciudadano:
    if not es_personal(current_user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Acceso denegado: se requiere personal municipal.")
    return current_user
