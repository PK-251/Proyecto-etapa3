"""Integraciones externas SIMULADAS (RENIEC y SUNAT). Sustituir por llamadas reales (httpx) en producción."""
import asyncio
from decimal import Decimal
from typing import List

from schemas import CiudadanoReniec, CiudadanoReniecData, DeudaTributaria


class IntegracionReniec:
    @staticmethod
    async def validar_dni(dni: str) -> CiudadanoReniec:
        await asyncio.sleep(0.3)  # latencia simulada
        if dni == "12345678":
            return CiudadanoReniec(
                success=True,
                data=CiudadanoReniecData(
                    nombre="JUAN CARLOS DELGADO MARTINEZ", dni=dni, direccion="JR. REAL 456, HUANCAYO"
                ),
            )
        return CiudadanoReniec(success=False)


class IntegracionSunat:
    @staticmethod
    async def consultar_deudas(dni: str) -> List[DeudaTributaria]:
        await asyncio.sleep(0.3)  # latencia simulada
        if dni == "12345678":
            return [
                DeudaTributaria(
                    descripcion="Impuesto a la Renta 4ta Categoría",
                    monto=Decimal("150.70"),
                    periodo="2024-10",
                )
            ]
        return []
