"""Consulta PÚBLICA de seguimiento (sin login): código de seguimiento o expediente + DNI del titular.

Solo devuelve el estado y los hitos (títulos y fechas): nunca descripciones, respuestas, nombres ni documentos.
"""
import hmac
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

import config
from catalogo import AREAS, NOMBRES_CLASE
from database import get_db_session
from models import ESTADOS_SOLICITUD_CERRADOS, NOMBRES_TRAMITE, EstadoPagoEnum, Pago, Solicitud, Tramite
from services.rate_limit import RateLimiter

router = APIRouter(tags=["Consulta pública"])
templates = Jinja2Templates(directory="templates")
_limite = RateLimiter(max_events=20, window_seconds=60)

_RE_SOLICITUD = re.compile(r"^(QJ|RC|PT)-\d{4}-\d{5}$")
_RE_EXPEDIENTE = re.compile(r"^\d{4}-\d{5}-[A-Z]{3}$")
_ESTADO_SOLICITUD = {"RECIBIDA": "Recibida", "EN_ATENCION": "En atención", "ATENDIDA": "Atendida", "IMPROCEDENTE": "Improcedente"}
_NO_ENCONTRADO = HTTPException(
    status.HTTP_404_NOT_FOUND,
    "No encontramos un caso con esos datos. Verifique el código y el DNI del titular.",
)


@router.get("/seguimiento", response_class=HTMLResponse, include_in_schema=False)
async def pagina_seguimiento(request: Request):
    return templates.TemplateResponse(request, "seguimiento.html", {"muni": config.MUNI_NOMBRE})


@router.get("/api/v1/publico/seguimiento")
async def consultar(
    request: Request,
    codigo: str = Query(min_length=8, max_length=30),
    dni: str = Query(min_length=8, max_length=8),
    db: AsyncSession = Depends(get_db_session),
):
    if not _limite.check_and_hit(request.client.host if request.client else "?"):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Demasiadas consultas. Espere un minuto.")
    codigo = codigo.strip().upper()
    if not dni.isdigit():
        raise _NO_ENCONTRADO

    if _RE_SOLICITUD.match(codigo):
        s = (
            await db.execute(select(Solicitud).options(selectinload(Solicitud.ciudadano)).where(Solicitud.codigo == codigo))
        ).scalar_one_or_none()
        if not s or not hmac.compare_digest(s.ciudadano.dni, dni):
            raise _NO_ENCONTRADO
        abierta = s.estado not in ESTADOS_SOLICITUD_CERRADOS
        hoy = datetime.now(ZoneInfo(config.APP_TIMEZONE)).date()
        return {
            "tipo": NOMBRES_CLASE[s.clase], "codigo": s.codigo, "estado": _ESTADO_SOLICITUD[s.estado.value],
            "cerrado": not abierta, "area": AREAS.get(s.area or ""), "fecha_registro": s.fecha_creacion.date().isoformat(),
            "fecha_limite": s.fecha_limite.isoformat(), "vencida": abierta and s.fecha_limite < hoy,
            "eventos": [
                {"fecha": e["fecha"], "titulo": e["evento"]}
                for e in (s.historial or []) if e.get("visible", True) and e["evento"] != "Comentario del ciudadano"
            ],
        }

    if _RE_EXPEDIENTE.match(codigo):
        t = (
            await db.execute(select(Tramite).options(selectinload(Tramite.ciudadano)).where(Tramite.expediente == codigo))
        ).scalar_one_or_none()
        if not t or not hmac.compare_digest(t.ciudadano.dni, dni):
            raise _NO_ENCONTRADO
        pagos = (
            await db.execute(select(Pago).where(Pago.tramite_id == t.id, Pago.estado == EstadoPagoEnum.COMPLETADO))
        ).scalars().all()
        iso = lambda d: d.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")  # noqa: E731
        eventos = [{"fecha": iso(t.fecha_creacion), "titulo": "Trámite registrado"}]
        eventos += [{"fecha": iso(p.fecha_pago), "titulo": "Pago recibido"} for p in pagos]
        for o in t.observaciones or []:
            try:
                f = iso(datetime.strptime(o["fecha"], "%Y-%m-%d %H:%M UTC"))
            except (KeyError, ValueError):
                f = iso(t.fecha_actualizacion)
            eventos.append({"fecha": f, "titulo": "Estado: " + o["estado"].replace("_", " ").title()})
        eventos.sort(key=lambda e: e["fecha"])
        return {
            "tipo": "Trámite: " + NOMBRES_TRAMITE[t.tipo], "codigo": t.expediente,
            "estado": t.estado.value.replace("_", " ").capitalize(),
            "cerrado": t.estado.value in ("APROBADO", "RECHAZADO"), "area": None,
            "fecha_registro": t.fecha_creacion.date().isoformat(), "fecha_limite": None, "vencida": False, "eventos": eventos,
        }

    raise _NO_ENCONTRADO
