"""Feriados nacionales del Perú (no laborables) para calcular plazos en días hábiles.

Revise la lista cada año (el Gobierno puede decretar días no laborables). Los feriados locales o
extraordinarios se agregan en el .env con FERIADOS_EXTRA=AAAA-MM-DD,AAAA-MM-DD.
"""
from datetime import date, timedelta
from functools import lru_cache

import config

# (mes, día) fijos
_FIJOS = [
    (1, 1),    # Año Nuevo
    (5, 1),    # Día del Trabajo
    (6, 29),   # San Pedro y San Pablo
    (7, 28),   # Fiestas Patrias
    (7, 29),   # Fiestas Patrias
    (8, 6),    # Batalla de Junín
    (8, 30),   # Santa Rosa de Lima
    (10, 8),   # Combate de Angamos
    (11, 1),   # Todos los Santos
    (12, 8),   # Inmaculada Concepción
    (12, 9),   # Batalla de Ayacucho
    (12, 25),  # Navidad
]


def _pascua(anio: int) -> date:
    """Domingo de Pascua (algoritmo de Meeus/Jones/Butcher)."""
    a, b, c = anio % 19, anio // 100, anio % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = ((h + l - 7 * m + 114) % 31) + 1
    return date(anio, mes, dia)


@lru_cache(maxsize=32)
def feriados_del_anio(anio: int) -> frozenset:
    pascua = _pascua(anio)
    dias = {date(anio, m, d) for m, d in _FIJOS}
    dias |= {pascua - timedelta(days=3), pascua - timedelta(days=2)}  # Jueves y Viernes Santo
    return frozenset(dias)


def _extra() -> set:
    extra = set()
    for texto in config.FERIADOS_EXTRA:
        try:
            extra.add(date.fromisoformat(texto))
        except ValueError:
            pass
    return extra


def es_feriado(dia: date) -> bool:
    return dia in feriados_del_anio(dia.year) or dia in _extra()


def es_dia_habil(dia: date) -> bool:
    return dia.weekday() < 5 and not es_feriado(dia)
