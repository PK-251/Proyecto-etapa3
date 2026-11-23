import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status

import config
from auth import get_admin_actual, get_usuario_actual
from models import Ciudadano
from schemas import AIChatRequest, AIChatResponse
from services.ai_service import get_ai_response, ia_configurada
from services.rate_limit import RateLimiter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/ai", tags=["Asistente IA"])

_limite = RateLimiter(max_events=config.AI_REQUESTS_PER_MINUTE, window_seconds=60)

# Métricas en memoria: se reinician con el servidor. Para persistirlas, guárdalas en una tabla.
_metricas = {"consultas_dia": 0, "total_consultas": 0, "fecha": datetime.now().date()}


def _contar_consulta() -> None:
    hoy = datetime.now().date()
    if _metricas["fecha"] != hoy:
        _metricas.update(consultas_dia=0, fecha=hoy)
    _metricas["consultas_dia"] += 1
    _metricas["total_consultas"] += 1


@router.post("/chat", response_model=AIChatResponse)
async def chat(request: AIChatRequest, usuario: Ciudadano = Depends(get_usuario_actual)):
    """HU-028: asistente virtual (máx. N consultas por minuto y usuario)."""
    prompt = request.prompt.strip()
    if not prompt:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "El mensaje no puede estar vacío.")
    if not _limite.check_and_hit(usuario.dni):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Demasiadas consultas. Espere un momento.")

    _contar_consulta()
    return AIChatResponse(response=await get_ai_response(prompt))


@router.get("/metricas")
async def metricas(_: Ciudadano = Depends(get_admin_actual)):
    """HU-028: métricas de uso. 'satisfaccion' es null hasta que exista una encuesta real."""
    return {
        "consultasDia": _metricas["consultas_dia"],
        "totalConsultas": _metricas["total_consultas"],
        "satisfaccion": None,
    }


@router.post("/metricas/reset")
async def resetear_metricas(admin: Ciudadano = Depends(get_admin_actual)):
    _metricas.update(consultas_dia=0, total_consultas=0, fecha=datetime.now().date())
    logger.info("Métricas de IA reseteadas por %s", admin.dni)
    return {"message": "Métricas reseteadas exitosamente"}


@router.get("/health")
async def health():
    """Público y mínimo: no expone métricas."""
    return {"status": "online" if ia_configurada() else "sin_configurar"}
