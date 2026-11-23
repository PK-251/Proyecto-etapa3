"""Inicialización de la base de datos y datos de demostración (solo si SEED_DEMO_DATA=true)."""
import logging
import secrets
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select

import config
from database import AsyncSessionLocal, Base, engine, init_models
from catalogo import sumar_dias_habiles
from models import (
    Ciudadano, ClaseSolicitudEnum, Deuda, EstadoDeudaEnum, EstadoSolicitudEnum, Notificacion, Solicitud, TipoDeudaEnum,
)
from security import get_password_hash

logger = logging.getLogger(__name__)


async def init_db() -> None:
    """Crea las tablas y, solo si se pidió explícitamente, los datos de demostración."""
    await init_models()
    if not config.SEED_DEMO_DATA:
        return
    async with AsyncSessionLocal() as session:
        total = (await session.execute(select(func.count(Ciudadano.id)))).scalar()
    if total == 0:
        await seed_test_data()
    else:
        await _asegurar_funcionaria_demo()


async def _asegurar_funcionaria_demo() -> None:
    """En una base ya existente (modo demostración) agrega la funcionaria de ejemplo si falta."""
    async with AsyncSessionLocal() as session:
        existe = (await session.execute(select(Ciudadano.id).where(Ciudadano.dni == "11223344"))).first()
        if existe:
            return
        clave = config.DEMO_STAFF_PASSWORD or secrets.token_urlsafe(9)
        session.add(Ciudadano(
            dni="11223344", nombre="MARIA TORRES QUISPE (SERVICIOS PUBLICOS)", email="mtorres@example.com",
            telefono="954111222", hashed_password=get_password_hash(clave), role="funcionario", area="SERVICIOS_PUBLICOS",
        ))
        await session.commit()
    logger.warning("[DEMO] Funcionaria de ejemplo creada (DNI 11223344). Clave: %s", clave)


async def seed_test_data() -> None:
    """Usuarios y deudas de demostración. Las contraseñas vienen del entorno o se generan al azar."""
    clave_ciudadano = config.DEMO_CITIZEN_PASSWORD or secrets.token_urlsafe(9)
    clave_admin = config.DEMO_ADMIN_PASSWORD or secrets.token_urlsafe(9)
    clave_staff = config.DEMO_STAFF_PASSWORD or secrets.token_urlsafe(9)
    hoy = date.today()

    async with AsyncSessionLocal() as session:
        ciudadano = Ciudadano(
            dni="12345678", nombre="JUAN CARLOS DELGADO MARTINEZ", email="jcdelgado@example.com",
            telefono="987654321", direccion="JR. REAL 456, HUANCAYO",
            hashed_password=get_password_hash(clave_ciudadano), role="ciudadano",
        )
        admin = Ciudadano(
            dni="87654321", nombre="ADMINISTRADOR DEL SISTEMA", email="admin@example.com",
            telefono="964123456", direccion="PLAZA PRINCIPAL S/N, HUANCAYO",
            hashed_password=get_password_hash(clave_admin), role="admin",
        )
        funcionario = Ciudadano(
            dni="11223344", nombre="MARIA TORRES QUISPE (SERVICIOS PUBLICOS)", email="mtorres@example.com",
            telefono="954111222", hashed_password=get_password_hash(clave_staff), role="funcionario", area="SERVICIOS_PUBLICOS",
        )
        session.add_all([ciudadano, admin, funcionario])
        await session.flush()

        session.add_all([
            Deuda(ciudadano_id=ciudadano.id, tipo=TipoDeudaEnum.PREDIAL, monto_base=Decimal("150.00"),
                  periodo="2024-Q1", fecha_vencimiento=hoy - timedelta(days=90), estado=EstadoDeudaEnum.VENCIDO, esta_vencida=True,
                  intereses_moratorios=Decimal("0.00"), monto_total=Decimal("150.00")),
            Deuda(ciudadano_id=ciudadano.id, tipo=TipoDeudaEnum.LIMPIEZA_PUBLICA, monto_base=Decimal("80.50"),
                  periodo=f"{hoy:%Y-%m}", fecha_vencimiento=hoy + timedelta(days=30),
                  intereses_moratorios=Decimal("0.00"), monto_total=Decimal("80.50")),
            Deuda(ciudadano_id=ciudadano.id, tipo=TipoDeudaEnum.ARBITRIOS, monto_base=Decimal("45.00"),
                  periodo=f"{hoy:%Y-%m}", fecha_vencimiento=hoy + timedelta(days=15),
                  intereses_moratorios=Decimal("0.00"), monto_total=Decimal("45.00")),
        ])
        ahora = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        session.add_all([
            Solicitud(
                ciudadano_id=ciudadano.id, clase=ClaseSolicitudEnum.RECLAMO, categoria="ALUMBRADO", area="SERVICIOS_PUBLICOS",
                asunto="Poste sin luz en Jr. Real cuadra 4", ubicacion="Jr. Real cuadra 4, frente al parque",
                descripcion="Desde hace dos semanas el poste frente al parque no enciende y la cuadra queda muy oscura por las noches.",
                estado=EstadoSolicitudEnum.EN_ATENCION, fecha_limite=sumar_dias_habiles(hoy, 25), documentos=[],
                historial=[
                    {"fecha": ahora, "autor": ciudadano.nombre, "evento": "Registrada", "texto": "Su solicitud fue recibida.", "visible": True},
                    {"fecha": ahora, "autor": admin.nombre, "evento": "En atención", "texto": "Derivado a la Gerencia de Servicios Públicos para inspección.", "visible": True},
                ],
            ),
            Solicitud(
                ciudadano_id=ciudadano.id, clase=ClaseSolicitudEnum.PETICION, categoria="SOLICITUD_INFORMACION", area="MESA_PARTES",
                asunto="Copia del plano de zonificación del distrito",
                descripcion="Solicito copia simple del plano de zonificación vigente para evaluar la compra de un terreno.",
                estado=EstadoSolicitudEnum.RECIBIDA, fecha_limite=sumar_dias_habiles(hoy, 8), documentos=[],
                historial=[{"fecha": ahora, "autor": ciudadano.nombre, "evento": "Registrada", "texto": "Su solicitud fue recibida.", "visible": True}],
            ),
            Notificacion(ciudadano_id=ciudadano.id, tipo="SISTEMA", titulo="Bienvenido al portal",
                         mensaje="Aquí recibirá avisos sobre sus trámites, pagos, quejas y peticiones."),
        ])
        await session.commit()

    print("=" * 60)
    print("DATOS DE DEMOSTRACIÓN CREADOS (esta es la única vez que se muestran)")
    print(f"  Ciudadano  DNI 12345678  contraseña: {clave_ciudadano}")
    print(f"  Admin      DNI 87654321  contraseña: {clave_admin}")
    print(f"  Funcionario (Servicios Públicos) DNI 11223344  contraseña: {clave_staff}")
    print("=" * 60)


async def reset_and_seed_db() -> None:
    """DESARROLLO: borra todas las tablas y las recrea con datos de demostración."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await seed_test_data()


if __name__ == "__main__":
    import asyncio
    import sys

    if "--reset" in sys.argv:
        if input("Esto ELIMINA todos los datos. Escribe SI para continuar: ").strip().upper() == "SI":
            asyncio.run(reset_and_seed_db())
        else:
            print("Cancelado.")
    else:
        asyncio.run(init_db())
        print("Base de datos lista. Usa 'python seed.py --reset' para recrearla con datos de demostración.")
