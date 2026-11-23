import hashlib
import hmac
import logging
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

import config
from auth import crear_access_token, get_usuario_actual
from database import get_db_session
from models import CodigoRecuperacion, Ciudadano, utc_now
from schemas import OlvideClaveRequest, RegistroRequest, RestablecerClaveRequest
from security import get_password_hash, verificar_password
from services.auditoria import registrar as auditar
from services.integrations import IntegracionReniec
from services.mensajeria import correo_inmediato
from services.notificaciones import notificar
from services.rate_limit import RateLimiter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/auth", tags=["Autenticación"])

# 5 intentos fallidos por DNI+IP cada 5 minutos
_intentos_fallidos = RateLimiter(max_events=5, window_seconds=300)
_registros = RateLimiter(max_events=config.REGISTROS_POR_HORA, window_seconds=3600)         # altas por IP
_olvidos_ip = RateLimiter(max_events=5, window_seconds=900)          # códigos pedidos por IP
_olvidos_dni = RateLimiter(max_events=3, window_seconds=900)         # códigos pedidos por DNI
_intentos_codigo = RateLimiter(max_events=10, window_seconds=900)    # códigos probados por IP
CODIGO_VALIDO_MINUTOS = 15
MAX_INTENTOS_CODIGO = 5
# Hash válido de una contraseña cualquiera: se usa para que el tiempo de respuesta no revele si el DNI existe
_HASH_FALSO = "$2b$12$C6UzMDM.H6dfI/f/IKcEeO5nqf6bYtI6ZQCWkYQ1l1D8h8f2w5wS."


@router.post("/login")
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db_session),
):
    """Login: 'username' es el DNI."""
    dni = form_data.username.strip()
    clave = f"{request.client.host if request.client else '?'}:{dni}"

    if _intentos_fallidos.is_blocked(clave):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Demasiados intentos fallidos. Espere unos minutos e intente nuevamente.",
        )

    user = (await db.execute(select(Ciudadano).where(Ciudadano.dni == dni))).scalar_one_or_none()
    ok = verificar_password(form_data.password, user.hashed_password if user else _HASH_FALSO)
    if not user or not ok:
        _intentos_fallidos.hit(clave)
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "DNI o contraseña incorrectos",
            headers={"WWW-Authenticate": "Bearer"},
        )

    _intentos_fallidos.reset(clave)
    return _sesion(user)


def _sesion(user: Ciudadano) -> dict:
    token = crear_access_token({"sub": user.dni, "role": user.role})
    return {
        "access_token": token, "token_type": "bearer",
        "user": {"dni": user.dni, "name": user.nombre, "role": user.role, "area": user.area},
    }


def _ip(request: Request) -> str:
    return request.client.host if request.client else "?"


def _huella(ciudadano_id: int, codigo: str) -> str:
    return hmac.new(config.SECRET_KEY.encode(), f"{ciudadano_id}:{codigo}".encode(), hashlib.sha256).hexdigest()


@router.post("/registro", status_code=status.HTTP_201_CREATED)
async def registro(request: Request, datos: RegistroRequest, db: AsyncSession = Depends(get_db_session)):
    """Auto-registro del ciudadano. Si RENIEC reconoce el DNI se usa su nombre oficial."""
    if not _registros.check_and_hit(_ip(request)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Demasiados registros desde esta conexión. Intente más tarde.")
    existe = (
        await db.execute(select(Ciudadano.id).where((Ciudadano.dni == datos.dni) | (Ciudadano.email == str(datos.email).lower())))
    ).first()
    if existe:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya existe una cuenta con ese DNI o ese correo. Si es suya, use 'Olvidé mi contraseña'.")
    reniec = await IntegracionReniec.validar_dni(datos.dni)
    nombre = reniec.data.nombre if reniec.success and reniec.data else datos.nombre
    user = Ciudadano(
        dni=datos.dni, nombre=nombre, email=str(datos.email).lower(), telefono=datos.telefono,
        hashed_password=get_password_hash(datos.password), role="ciudadano",
    )
    db.add(user)
    await db.flush()
    await notificar(db, user.id, "SISTEMA", "Bienvenido al portal",
                    "Su cuenta fue creada. Aquí recibirá avisos de sus trámites, pagos, quejas y peticiones.")
    await auditar(db, user, "CUENTA_CREADA", "usuario", user.dni, "auto-registro")
    logger.info("Nueva cuenta %s", user.dni)
    return _sesion(user)


@router.post("/olvide-clave")
async def olvide_clave(request: Request, datos: OlvideClaveRequest, db: AsyncSession = Depends(get_db_session)):
    """Envía un código de 6 dígitos al correo registrado. La respuesta es la misma exista o no la cuenta."""
    respuesta = {"message": "Si el DNI está registrado y tiene un correo, enviamos un código de 6 dígitos (vale 15 minutos)."}
    if not _olvidos_ip.check_and_hit(_ip(request)) or not _olvidos_dni.check_and_hit(datos.dni):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Demasiadas solicitudes. Espere unos minutos.")
    user = (await db.execute(select(Ciudadano).where(Ciudadano.dni == datos.dni))).scalar_one_or_none()
    if not user or not user.email:
        return respuesta
    # un código vigente a la vez
    for viejo in (await db.execute(select(CodigoRecuperacion).where(CodigoRecuperacion.ciudadano_id == user.id, CodigoRecuperacion.usado.is_(False)))).scalars():
        viejo.usado = True
    codigo = f"{secrets.randbelow(10**6):06d}"
    db.add(CodigoRecuperacion(ciudadano_id=user.id, huella=_huella(user.id, codigo), expira=utc_now() + timedelta(minutes=CODIGO_VALIDO_MINUTOS)))
    await auditar(db, user, "CLAVE_CODIGO_SOLICITADO", "usuario", user.dni)
    correo_inmediato(
        user.email, "Código para restablecer su contraseña",
        f"Su código de recuperación es: {codigo}\n\nVale {CODIGO_VALIDO_MINUTOS} minutos. Si usted no lo solicitó, ignore este mensaje: su contraseña no cambia.",
    )
    if not config.EMAIL_ACTIVO and config.MODO_DEMO:
        logger.warning("[DEMO] Correo no configurado. Código de recuperación del DNI %s: %s", user.dni, codigo)
    return respuesta


@router.post("/restablecer-clave")
async def restablecer_clave(request: Request, datos: RestablecerClaveRequest, db: AsyncSession = Depends(get_db_session)):
    error = HTTPException(status.HTTP_400_BAD_REQUEST, "El código no es válido o ya venció.")
    if not _intentos_codigo.check_and_hit(_ip(request)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Demasiados intentos. Espere unos minutos.")
    user = (await db.execute(select(Ciudadano).where(Ciudadano.dni == datos.dni))).scalar_one_or_none()
    if not user:
        raise error
    cod = (
        await db.execute(
            select(CodigoRecuperacion).where(CodigoRecuperacion.ciudadano_id == user.id, CodigoRecuperacion.usado.is_(False))
            .order_by(CodigoRecuperacion.id.desc())
        )
    ).scalars().first()
    if not cod or cod.expira < utc_now():
        raise error
    if not hmac.compare_digest(cod.huella, _huella(user.id, datos.codigo)):
        cod.intentos += 1
        if cod.intentos >= MAX_INTENTOS_CODIGO:
            cod.usado = True  # se quema el código tras demasiados fallos
        await db.commit()  # persiste el intento aunque se responda con error
        raise error
    cod.usado = True
    user.hashed_password = get_password_hash(datos.nueva_clave)
    _intentos_fallidos.reset(f"{_ip(request)}:{user.dni}")
    await auditar(db, user, "CLAVE_RESTABLECIDA", "usuario", user.dni)
    await notificar(db, user.id, "SISTEMA", "Contraseña cambiada", "Su contraseña fue restablecida. Si no fue usted, comuníquese con la municipalidad.")
    return {"message": "Contraseña actualizada. Ya puede iniciar sesión."}


@router.get("/me")
async def read_users_me(current_user: Ciudadano = Depends(get_usuario_actual)):
    return {
        "dni": current_user.dni,
        "name": current_user.nombre,
        "role": current_user.role,
        "area": current_user.area,
        "email": current_user.email,
    }
