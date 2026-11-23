"""Configuración central de la aplicación (variables de entorno / .env)."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "si", "sí"}


BASE_DIR = Path(__file__).resolve().parent

SECRET_KEY = os.getenv("SECRET_KEY", "").strip()
if len(SECRET_KEY) < 32:
    raise RuntimeError(
        "Falta SECRET_KEY (mínimo 32 caracteres). Copia .env.example a .env y genera una con:\n"
        '  python -c "import secrets; print(secrets.token_urlsafe(64))"'
    )

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if not DATABASE_URL:
    raise RuntimeError("Configura DATABASE_URL con una conexión PostgreSQL. Consulta .env.example.")
SQL_ECHO = _bool("SQL_ECHO", False)

SEED_DEMO_DATA = _bool("SEED_DEMO_DATA", False)
DEMO_CITIZEN_PASSWORD = os.getenv("DEMO_CITIZEN_PASSWORD", "").strip()
DEMO_ADMIN_PASSWORD = os.getenv("DEMO_ADMIN_PASSWORD", "").strip()
DEMO_STAFF_PASSWORD = os.getenv("DEMO_STAFF_PASSWORD", "").strip()

APP_TIMEZONE = os.getenv("APP_TIMEZONE", "America/Lima")

UPLOADS_DIR = Path(os.getenv("UPLOADS_DIR", "private_uploads"))
if not UPLOADS_DIR.is_absolute():
    UPLOADS_DIR = BASE_DIR / UPLOADS_DIR
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "5"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
MAX_FILES_PER_TRAMITE = int(os.getenv("MAX_FILES_PER_TRAMITE", "10"))

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
AI_REQUESTS_PER_MINUTE = int(os.getenv("AI_REQUESTS_PER_MINUTE", "10"))


# --- Pagos y comprobantes ---
GATEWAY_LATENCY_S = float(os.getenv("GATEWAY_LATENCY_S", "1.2"))
MAX_PAGOS_FALLIDOS = int(os.getenv("MAX_PAGOS_FALLIDOS", "5"))  # por usuario cada 10 min
COMPROBANTE_SERIE = os.getenv("COMPROBANTE_SERIE", "B001")
# La pasarela es simulada: los comprobantes llevan marca de DEMOSTRACIÓN mientras esto sea true.
MODO_DEMO = _bool("MODO_DEMO", True)
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
MUNI_NOMBRE = os.getenv("MUNI_NOMBRE", "Municipalidad de Chilca")
MUNI_RUC = os.getenv("MUNI_RUC", "").strip()
MUNI_DIRECCION = os.getenv("MUNI_DIRECCION", "Chilca, Junín - Perú")
MUNI_TELEFONO = os.getenv("MUNI_TELEFONO", "").strip()

# --- Quejas, reclamos y peticiones: plazos de atención en días hábiles (referenciales, configurables) ---
PLAZO_QUEJA_DIAS = int(os.getenv("PLAZO_QUEJA_DIAS", "15"))
PLAZO_RECLAMO_DIAS = int(os.getenv("PLAZO_RECLAMO_DIAS", "30"))
PLAZO_PETICION_DIAS = int(os.getenv("PLAZO_PETICION_DIAS", "30"))
PLAZO_INFORMACION_DIAS = int(os.getenv("PLAZO_INFORMACION_DIAS", "10"))  # solicitudes de acceso a la información
SOLICITUDES_POR_HORA = int(os.getenv("SOLICITUDES_POR_HORA", "10"))  # anti-spam por usuario

# --- Avisos por correo (SMTP) y WhatsApp (CallMeBot). Todo opcional: sin datos, solo funciona la campana del portal ---
SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "").strip()
SMTP_FROM = os.getenv("SMTP_FROM", "").strip() or SMTP_USER
SMTP_STARTTLS = _bool("SMTP_STARTTLS", True)
EMAIL_ACTIVO = bool(SMTP_HOST and SMTP_USER and SMTP_PASSWORD)

CALLMEBOT_PHONE = os.getenv("CALLMEBOT_PHONE", "").strip()      # con código de país, p. ej. +51987654321
CALLMEBOT_APIKEY = os.getenv("CALLMEBOT_APIKEY", "").strip()
WHATSAPP_ACTIVO = bool(CALLMEBOT_PHONE and CALLMEBOT_APIKEY)

# --- Feriados adicionales (AAAA-MM-DD separados por coma) que se suman a los nacionales ---
FERIADOS_EXTRA = [d.strip() for d in os.getenv("FERIADOS_EXTRA", "").split(",") if d.strip()]
REGISTROS_POR_HORA = int(os.getenv("REGISTROS_POR_HORA", "5"))  # altas de cuenta por IP
