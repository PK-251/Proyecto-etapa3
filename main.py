import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import SQLAlchemyError

import config  # noqa: F401  (valida SECRET_KEY al arrancar)
import models  # noqa: F401  (registra las tablas)
from controllers.admin_controller import router as admin_router
from controllers.ai_controller import router as ai_router
from controllers.auth_controller import router as auth_router
from controllers.ciudadano_controller import router as ciudadano_router
from controllers.deuda_controller import router as deuda_router
from controllers.notificacion_controller import router as notificacion_router
from controllers.pago_controller import router as pago_router
from controllers.publico_controller import router as publico_router
from controllers.solicitud_controller import router as solicitud_router
from controllers.tramite_controller import router as tramite_router
from controllers.verificacion_controller import router as verificacion_router
from seed import init_db
from database import engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("portal")


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    await init_db()
    logger.info("Aplicación lista")
    try:
        yield
    finally:
        await engine.dispose()


app = FastAPI(
    title=f"Municipio Conecta - {config.MUNI_NOMBRE}",
    description="API para la gestión de trámites y deudas municipales.",
    version="2.3.0",
    lifespan=lifespan,
)

# Solo recursos públicos de la interfaz. Los documentos de los ciudadanos NO se sirven aquí:
# se descargan por /api/v1/tramites/{id}/documentos/{archivo} con autenticación.
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

for router in (auth_router, admin_router, ai_router, ciudadano_router, tramite_router, deuda_router, pago_router, verificacion_router, solicitud_router, notificacion_router, publico_router):
    app.include_router(router)


@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse(request, "index.html", {"muni": config.MUNI_NOMBRE, "telefono": config.MUNI_TELEFONO})


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse("static/favicon.svg", media_type="image/svg+xml")


@app.get("/health", include_in_schema=False)
async def health_check():
    return {"status": "ok"}


# ===== Manejo de errores =====
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Error no controlado en %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"success": False, "error": "Ha ocurrido un error inesperado en el servidor."},
    )


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError):
    logger.exception("Error de base de datos en %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"success": False, "error": "Error al procesar la solicitud en la base de datos."},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # Se quitan 'ctx' e 'input' (pueden contener excepciones no serializables o datos sensibles)
    errores = [
        {"campo": ".".join(str(p) for p in e["loc"] if p != "body"), "mensaje": e["msg"].removeprefix("Value error, ")}
        for e in exc.errors()
    ]
    detalle = "; ".join(f"{e['campo']}: {e['mensaje']}" if e["campo"] else e["mensaje"] for e in errores)
    return JSONResponse(
        status_code=422,
        content=jsonable_encoder({"success": False, "error": "Datos de entrada inválidos.", "detail": detalle, "details": errores}),
    )


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response: Response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    return response


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
