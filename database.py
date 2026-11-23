from typing import AsyncGenerator

import logging

from sqlalchemy import inspect
from sqlalchemy.engine import URL, make_url
from sqlalchemy.schema import CreateColumn
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

import config

Base = declarative_base()


def url_asincrona(value: str) -> URL:
    """Normaliza las URL de PostgreSQL al controlador asíncrono del portal."""
    url = make_url(value)
    if url.drivername not in {"postgres", "postgresql", "postgresql+asyncpg"}:
        raise ValueError("Municipio Conecta requiere PostgreSQL. Revisa DATABASE_URL en el archivo .env.")
    return url.set(drivername="postgresql+asyncpg")


engine = create_async_engine(url_asincrona(config.DATABASE_URL), echo=config.SQL_ECHO, pool_pre_ping=True)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Sesión por petición. Hace commit si todo salió bien y rollback si hubo error."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


logger = logging.getLogger(__name__)


def _agregar_columnas_faltantes(sync_conn) -> None:
    """Migración mínima: añade a tablas existentes las columnas NUEVAS (siempre opcionales) del modelo.

    Evita tener que borrar la base al actualizar. Para cambios más complejos usa Alembic.
    """
    insp = inspect(sync_conn)
    for tabla in Base.metadata.sorted_tables:
        if not insp.has_table(tabla.name):
            continue
        existentes = {c["name"] for c in insp.get_columns(tabla.name)}
        for col in tabla.columns:
            if col.name in existentes:
                continue
            if not col.nullable and col.server_default is None:
                logger.warning("No se puede añadir %s.%s (obligatoria sin valor por defecto)", tabla.name, col.name)
                continue
            dialecto = sync_conn.dialect
            nombre_tabla = dialecto.identifier_preparer.format_table(tabla)
            definicion = CreateColumn(col).compile(dialect=dialecto)
            sync_conn.exec_driver_sql(f"ALTER TABLE {nombre_tabla} ADD COLUMN {definicion}")
            logger.info("Columna añadida: %s.%s", tabla.name, col.name)


async def init_models() -> None:
    """Crea las tablas que falten y añade las columnas nuevas a las existentes."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_agregar_columnas_faltantes)

    await _asignar_area_a_solicitudes_antiguas()


async def _asignar_area_a_solicitudes_antiguas() -> None:
    """Las solicitudes creadas antes de existir las áreas reciben la que les corresponde por categoría."""
    from catalogo import area_de_solicitud
    from models import Solicitud
    from sqlalchemy import select, update

    async with AsyncSessionLocal() as s:
        sin_area = (await s.execute(select(Solicitud.id, Solicitud.categoria).where(Solicitud.area.is_(None)))).all()
        for sid, categoria in sin_area:
            await s.execute(update(Solicitud).where(Solicitud.id == sid).values(area=area_de_solicitud(categoria)))
        await s.commit()
