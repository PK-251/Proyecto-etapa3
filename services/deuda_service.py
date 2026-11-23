from datetime import date, timedelta
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from typing import Iterable, List, Optional, Tuple

from models import Cuota, Deuda, EstadoDeudaEnum

CENTAVO = Decimal("0.01")
# Tasa de interés moratorio diaria: 1.2 % mensual / 30 días
TIM_DIARIA = Decimal("0.012") / Decimal("30")

ESTADOS_PAGABLES = (EstadoDeudaEnum.PENDIENTE, EstadoDeudaEnum.VENCIDO)


def _q(valor: Decimal) -> Decimal:
    return Decimal(valor).quantize(CENTAVO, rounding=ROUND_HALF_UP)


class DeudaService:
    @staticmethod
    def calcular_intereses(
        monto_base: Decimal, fecha_vencimiento: date, hoy: Optional[date] = None
    ) -> Tuple[Decimal, Decimal, bool]:
        """Devuelve (intereses, monto_total, vencida) a la fecha `hoy`."""
        hoy = hoy or date.today()
        monto_base = Decimal(monto_base)
        if hoy <= fecha_vencimiento:
            return Decimal("0.00"), _q(monto_base), False
        dias = (hoy - fecha_vencimiento).days
        intereses = _q(monto_base * TIM_DIARIA * Decimal(dias))
        return intereses, _q(monto_base + intereses), True

    @staticmethod
    def actualizar_deuda(deuda: Deuda, hoy: Optional[date] = None) -> Deuda:
        """Recalcula y PERSISTE intereses/estado de una deuda impaga.

        Las deudas pagadas o fraccionadas no se tocan: su monto queda congelado.
        Es la única fuente del monto a pagar, tanto para consultar como para cobrar.
        """
        if deuda.estado not in ESTADOS_PAGABLES:
            return deuda
        intereses, total, vencida = DeudaService.calcular_intereses(
            deuda.monto_base, deuda.fecha_vencimiento, hoy
        )
        deuda.intereses_moratorios = intereses
        deuda.monto_total = total
        deuda.esta_vencida = vencida
        deuda.estado = EstadoDeudaEnum.VENCIDO if vencida else EstadoDeudaEnum.PENDIENTE
        return deuda

    @staticmethod
    def generar_cuotas(deuda: Deuda, numero_cuotas: int, hoy: Optional[date] = None) -> List[Cuota]:
        """Divide el monto actual en cuotas mensuales; el último centavo va a la última cuota."""
        hoy = hoy or date.today()
        total = Decimal(deuda.monto_total)
        base = (total / numero_cuotas).quantize(CENTAVO, rounding=ROUND_DOWN)
        cuotas = []
        acumulado = Decimal("0.00")
        for i in range(1, numero_cuotas + 1):
            monto = base if i < numero_cuotas else total - acumulado
            acumulado += monto
            cuotas.append(
                Cuota(numero=i, monto=monto, fecha_vencimiento=hoy + timedelta(days=30 * i))
            )
        return cuotas

    @staticmethod
    def calcular_total_deudas(deudas_municipales: Iterable, deudas_sunat: Iterable) -> Decimal:
        """Suma solo lo que realmente se debe (excluye deudas pagadas o fraccionadas)."""
        total_muni = sum(
            (d.monto_total for d in deudas_municipales if d.estado in ESTADOS_PAGABLES), Decimal("0")
        )
        total_sunat = sum((d.monto for d in deudas_sunat), Decimal("0"))
        return _q(total_muni + total_sunat)
