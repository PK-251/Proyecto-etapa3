from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

from conftest import ROOT  # noqa: F401  (ajusta sys.path)
from models import EstadoDeudaEnum
from services.deuda_service import DeudaService


def test_sin_retraso_no_hay_intereses():
    hoy = date(2026, 1, 10)
    assert DeudaService.calcular_intereses(Decimal("100"), hoy, hoy) == (Decimal("0.00"), Decimal("100.00"), False)


def test_intereses_por_dia():
    hoy = date(2026, 1, 31)
    venc = hoy - timedelta(days=30)  # 30 días * 0.04 % diario = 1.2 %
    assert DeudaService.calcular_intereses(Decimal("100"), venc, hoy) == (Decimal("1.20"), Decimal("101.20"), True)


def test_actualizar_deuda_no_toca_pagadas():
    d = SimpleNamespace(
        estado=EstadoDeudaEnum.PAGADO, monto_base=Decimal("50"), monto_total=Decimal("50"),
        intereses_moratorios=Decimal("0"), esta_vencida=False, fecha_vencimiento=date(2020, 1, 1),
    )
    DeudaService.actualizar_deuda(d)
    assert d.monto_total == Decimal("50") and not d.esta_vencida


def test_cuotas_suman_exactamente_el_total():
    d = SimpleNamespace(monto_total=Decimal("100.00"))
    for n in range(3, 13):
        assert sum(c.monto for c in DeudaService.generar_cuotas(d, n)) == Decimal("100.00")


def test_importe_en_letras():
    from services.pdf_service import importe_en_letras, numero_a_letras

    assert importe_en_letras(Decimal("177.12")) == "CIENTO SETENTA Y SIETE CON 12/100 SOLES"
    assert importe_en_letras(Decimal("15")) == "QUINCE CON 00/100 SOLES"
    assert numero_a_letras(21000) == "VEINTIÚN MIL" and numero_a_letras(1000) == "MIL"
    assert numero_a_letras(100) == "CIEN" and numero_a_letras(101) == "CIENTO UNO"
    assert numero_a_letras(1_000_000) == "UN MILLÓN"
