"""La actualización del esquema debe conservar filas en PostgreSQL."""
from sqlalchemy import Column, Integer, MetaData, String, Table, select

import database


def test_agregar_columnas_respeta_dialecto_y_conserva_filas(client, monkeypatch):
    antigua = Table("prueba_migracion", MetaData(), Column("id", Integer, primary_key=True))
    nueva = antigua.to_metadata(MetaData())
    # "group" es una palabra reservada de PostgreSQL.
    nueva.append_column(Column("group", String(20), nullable=False, server_default="inicial"))
    monkeypatch.setattr(database.Base, "metadata", nueva.metadata)

    def comprobar(conn):
        antigua.create(conn)
        try:
            conn.execute(antigua.insert().values(id=1))
            database._agregar_columnas_faltantes(conn)
            database._agregar_columnas_faltantes(conn)
            assert conn.execute(select(nueva.c.id, nueva.c.group)).one() == (1, "inicial")
        finally:
            antigua.drop(conn)

    async def ejecutar():
        async with database.engine.begin() as conn:
            await conn.run_sync(comprobar)

    client.portal.call(ejecutar)
