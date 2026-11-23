import asyncio
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# La configuración se fija ANTES de importar la aplicación
_tmp = tempfile.mkdtemp(prefix="muni_tests_")
db_servidor = os.getenv("MUNICIPIO_TEST_DATABASE_URL", "").strip()
if not db_servidor:
    raise pytest.UsageError("Define MUNICIPIO_TEST_DATABASE_URL con una base PostgreSQL de pruebas vacía.")
os.environ.update(
    SECRET_KEY="clave-de-pruebas-" + "x" * 40,
    DATABASE_URL=db_servidor,
    UPLOADS_DIR=f"{_tmp}/uploads",
    SEED_DEMO_DATA="true",
    DEMO_CITIZEN_PASSWORD="ClaveCiudadano1",
    DEMO_ADMIN_PASSWORD="ClaveAdmin1234",
    DEMO_STAFF_PASSWORD="ClaveFuncionario1",
    MAX_UPLOAD_MB="1",
    GOOGLE_API_KEY="",
    SMTP_HOST="",
    CALLMEBOT_APIKEY="",
    GATEWAY_LATENCY_S="0",
    MAX_PAGOS_FALLIDOS="5",
    SOLICITUDES_POR_HORA="1000",
    REGISTROS_POR_HORA="1000",
)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

CIUDADANO = ("12345678", "ClaveCiudadano1")
ADMIN = ("87654321", "ClaveAdmin1234")
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


@pytest.fixture(scope="session")
def client():
    # La suite crea usuarios y datos de prueba. Rechazar cualquier base que ya tenga tablas.
    from database import engine
    from sqlalchemy import inspect

    async def comprobar_base_vacia():
        try:
            async with engine.connect() as conn:
                tablas = await conn.run_sync(lambda sync: inspect(sync).get_table_names())
                if tablas:
                    pytest.fail("MUNICIPIO_TEST_DATABASE_URL debe apuntar a una base de pruebas vacía.")
        finally:
            await engine.dispose()

    asyncio.run(comprobar_base_vacia())
    with TestClient(main.app, raise_server_exceptions=False) as c:
        yield c


def _login(client, dni, password):
    r = client.post("/api/v1/auth/login", data={"username": dni, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="session")
def h_ciudadano(client):
    return _login(client, *CIUDADANO)


@pytest.fixture(scope="session")
def h_admin(client):
    return _login(client, *ADMIN)


@pytest.fixture(scope="session")
def h_staff(client):
    """Funcionaria demo del área Servicios Públicos."""
    return _login(client, "11223344", "ClaveFuncionario1")


@pytest.fixture(scope="session")
def h_otro(client, h_admin):
    """Segundo ciudadano, para probar que no puede ver lo ajeno."""
    r = client.post(
        "/api/v1/admin/ciudadanos",
        headers=h_admin,
        json={"dni": "11111111", "nombre": "OTRA PERSONA", "password": "OtraClave123"},
    )
    assert r.status_code == 201, r.text
    return _login(client, "11111111", "OtraClave123")


@pytest.fixture()
def tramite(client, h_ciudadano):
    r = client.post("/api/v1/tramites/", headers=h_ciudadano, json={"tipo": "LICENCIA_FUNCIONAMIENTO"})
    assert r.status_code == 201, r.text
    return r.json()
