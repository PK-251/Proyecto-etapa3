import re
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Annotated, Any, Dict, List, Optional

from pydantic import (
    BaseModel, ConfigDict, EmailStr, Field, PlainSerializer, field_validator, model_validator,
)

# Los enums viven en models.py (una sola definición)
from models import (  # noqa: F401
    ClaseSolicitudEnum, EstadoSolicitudEnum, EstadoDeudaEnum, EstadoPagoEnum, EstadoTramiteEnum, MetodoPagoEnum,
    TipoDeudaEnum, TipoTramiteEnum,
)
from security import MAX_PASSWORD_BYTES, MIN_PASSWORD_LENGTH


def _utc_iso(dt: datetime) -> str:
    """Las fechas se guardan en UTC sin tzinfo: se envían con 'Z' para que el navegador las convierta bien."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


UTCDateTime = Annotated[datetime, PlainSerializer(_utc_iso, return_type=str)]


def _validar_dni(v: str) -> str:
    if not v.isdigit() or len(v) != 8:
        raise ValueError("El DNI debe tener exactamente 8 dígitos.")
    return v


def _validar_password(v: str) -> str:
    if len(v) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"La contraseña debe tener al menos {MIN_PASSWORD_LENGTH} caracteres.")
    if len(v.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError(f"La contraseña no puede superar {MAX_PASSWORD_BYTES} bytes.")
    return v


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ===== Ciudadano =====
class CiudadanoBase(BaseModel):
    dni: str
    nombre: str
    email: Optional[EmailStr] = None
    telefono: Optional[str] = None
    direccion: Optional[str] = None

    _dni = field_validator("dni")(classmethod(lambda cls, v: _validar_dni(v)))


class Ciudadano(CiudadanoBase, ORMModel):
    id: int
    role: str
    fecha_registro: UTCDateTime


class CiudadanoReniecData(BaseModel):
    nombre: str
    dni: str
    direccion: Optional[str] = None


class CiudadanoReniec(BaseModel):
    success: bool
    data: Optional[CiudadanoReniecData] = None


# ===== Trámite =====
class TramiteCreate(BaseModel):
    tipo: TipoTramiteEnum
    detalles: Optional[Dict[str, Any]] = None
    # Opcional y solo informativo: el trámite siempre se crea a nombre del usuario autenticado
    # (un admin puede indicar el DNI de otro ciudadano).
    dni_ciudadano: Optional[str] = None

    @field_validator("dni_ciudadano")
    @classmethod
    def _dni(cls, v):
        return _validar_dni(v) if v is not None else v


class Observacion(BaseModel):
    fecha: str
    autor: str
    estado: str
    texto: str


class DocumentoAdjunto(BaseModel):
    nombre: str
    url: str  # enlace autenticado: requiere el token del usuario


class Tramite(ORMModel):
    id: int
    expediente: str
    tipo: TipoTramiteEnum
    estado: EstadoTramiteEnum
    costo_total: Decimal
    ciudadano_id: int
    detalles: Optional[Dict[str, Any]] = None
    observaciones: List[Observacion] = []
    documentos: List[DocumentoAdjunto] = []
    fecha_creacion: UTCDateTime
    fecha_actualizacion: UTCDateTime


class TramiteAdminResponse(Tramite):
    ciudadano_nombre: str
    ciudadano_dni: str


class ActualizarEstadoRequest(BaseModel):
    estado: EstadoTramiteEnum
    observaciones: Optional[str] = Field(default=None, max_length=1000)


# ===== Deuda =====
class Cuota(ORMModel):
    numero: int
    monto: Decimal
    fecha_vencimiento: date
    estado: EstadoDeudaEnum


class Deuda(ORMModel):
    id: int
    tipo: TipoDeudaEnum
    monto_base: Decimal
    periodo: Optional[str] = None
    fecha_vencimiento: date
    intereses_moratorios: Decimal
    monto_total: Decimal
    esta_vencida: bool
    estado: EstadoDeudaEnum
    ciudadano_id: int


class DeudaTributaria(BaseModel):
    fuente: str = "SUNAT"
    descripcion: str
    monto: Decimal
    periodo: str


class ConsultaDeudaRequest(BaseModel):
    dni: Optional[str] = None  # opcional: por defecto el del usuario autenticado

    @field_validator("dni")
    @classmethod
    def _dni(cls, v):
        return _validar_dni(v) if v is not None else v


class ConsultaDeudaResponse(BaseModel):
    deudasMunicipales: List[Deuda]
    deudasTributarias: List[DeudaTributaria]
    totalGeneral: Decimal


class PlanPagosRequest(BaseModel):
    numero_cuotas: int = Field(ge=3, le=12, description="Entre 3 y 12 cuotas mensuales")


class PlanPagosResponse(BaseModel):
    message: str
    deuda_id: int
    cuotas: List[Cuota]


# ===== Pago =====
class TarjetaDatos(BaseModel):
    """Datos de tarjeta: solo viajan en la petición; nunca se guardan ni se registran en logs."""
    numero: str
    vencimiento: str = Field(description="MM/AA")
    cvv: str
    titular: str = Field(min_length=3, max_length=60)

    @field_validator("numero")
    @classmethod
    def _numero(cls, v):
        from services.simulador_pago import luhn_valido

        v = re.sub(r"[\s-]", "", v)
        if not v.isdigit() or not 13 <= len(v) <= 19 or not luhn_valido(v):
            raise ValueError("Número de tarjeta inválido.")
        return v

    @field_validator("vencimiento")
    @classmethod
    def _vencimiento(cls, v):
        m = re.fullmatch(r"(0[1-9]|1[0-2])/(\d{2})", v.strip())
        if not m:
            raise ValueError("El vencimiento debe tener el formato MM/AA.")
        mes, anio = int(m.group(1)), 2000 + int(m.group(2))
        hoy = date.today()
        if (anio, mes) < (hoy.year, hoy.month):
            raise ValueError("La tarjeta está vencida.")
        return v.strip()

    @field_validator("cvv")
    @classmethod
    def _cvv(cls, v):
        if not re.fullmatch(r"\d{3,4}", v):
            raise ValueError("CVV inválido.")
        return v


class PagoRequest(BaseModel):
    # El monto lo calcula el servidor; se envía solo para confirmar que el usuario vio el mismo importe.
    monto: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    metodo: MetodoPagoEnum
    tarjeta: Optional[TarjetaDatos] = None  # obligatorio con TARJETA
    celular: Optional[str] = None  # obligatorio con YAPE / PLIN
    codigo_aprobacion: Optional[str] = None  # 6 dígitos, obligatorio con YAPE / PLIN

    @model_validator(mode="after")
    def _datos_segun_metodo(self):
        if self.metodo == MetodoPagoEnum.TARJETA:
            if self.tarjeta is None:
                raise ValueError("Ingrese los datos de la tarjeta.")
        else:
            if not self.celular or not re.fullmatch(r"9\d{8}", self.celular):
                raise ValueError("El celular debe tener 9 dígitos y empezar con 9.")
            if not self.codigo_aprobacion or not re.fullmatch(r"\d{6}", self.codigo_aprobacion):
                raise ValueError("El código de aprobación debe tener 6 dígitos.")
        return self


class PagoResponse(BaseModel):
    id: int
    estado: EstadoPagoEnum
    monto: Decimal
    metodo: MetodoPagoEnum
    mensaje: str
    numero_comprobante: Optional[str] = None
    transaccion_id: Optional[str] = None
    codigo_autorizacion: Optional[str] = None
    detalle_metodo: Optional[str] = None
    concepto: Optional[str] = None
    fecha_pago: Optional[UTCDateTime] = None
    tramite_expediente: Optional[str] = None
    deuda_id: Optional[int] = None


class PagoHistorial(ORMModel):
    id: int
    numero_comprobante: Optional[str] = None  # solo los pagos completados tienen comprobante
    concepto: Optional[str] = None
    monto: Decimal
    metodo: MetodoPagoEnum
    estado: EstadoPagoEnum
    fecha_pago: UTCDateTime
    detalle_metodo: Optional[str] = None
    transaccion_id: Optional[str] = None
    motivo_rechazo: Optional[str] = None


class PagoAdminView(PagoHistorial):
    ciudadano_nombre: str
    ciudadano_dni: str


# ===== Admin =====
class CiudadanoCreateAdmin(BaseModel):
    dni: str
    nombre: str = Field(min_length=3, max_length=255)
    email: Optional[EmailStr] = None
    password: str
    role: str = "ciudadano"
    area: Optional[str] = None

    _dni = field_validator("dni")(classmethod(lambda cls, v: _validar_dni(v)))
    _pw = field_validator("password")(classmethod(lambda cls, v: _validar_password(v)))

    @field_validator("role")
    @classmethod
    def _role(cls, v):
        if v not in ("ciudadano", "funcionario", "admin"):
            raise ValueError('El rol debe ser "ciudadano", "funcionario" o "admin".')
        return v

    @model_validator(mode="after")
    def _area_del_funcionario(self):
        from catalogo import AREAS
        if self.role == "funcionario" and self.area not in AREAS:
            raise ValueError("El funcionario debe tener un área válida.")
        if self.role != "funcionario":
            self.area = None
        return self


class CiudadanoAdminView(ORMModel):
    id: int
    dni: str
    nombre: str
    email: Optional[EmailStr] = None
    role: str
    area: Optional[str] = None
    fecha_registro: UTCDateTime


# ===== IA =====
class AIChatRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=1000)


class AIChatResponse(BaseModel):
    response: str



# ===== Quejas, reclamos y peticiones =====
class SolicitudCreate(BaseModel):
    clase: ClaseSolicitudEnum
    categoria: str
    asunto: str = Field(min_length=5, max_length=150)
    descripcion: str = Field(min_length=20, max_length=3000)
    ubicacion: Optional[str] = Field(default=None, max_length=255)

    @field_validator("asunto", "descripcion", "ubicacion")
    @classmethod
    def _limpiar(cls, v):
        return v.strip() if isinstance(v, str) else v

    @model_validator(mode="after")
    def _categoria_valida(self):
        from catalogo import CATEGORIAS_SOLICITUD
        if self.categoria not in CATEGORIAS_SOLICITUD[self.clase]:
            raise ValueError("La categoría no corresponde al tipo de solicitud.")
        if len(self.asunto) < 5 or len(self.descripcion) < 20:
            raise ValueError("Describa el asunto (mín. 5 caracteres) y los hechos (mín. 20 caracteres).")
        return self


class EventoHistorial(BaseModel):
    fecha: str
    autor: str
    evento: str
    texto: Optional[str] = None
    visible: bool = True


class SolicitudResponse(BaseModel):
    id: int
    codigo: str
    clase: ClaseSolicitudEnum
    clase_nombre: str
    categoria: str
    categoria_nombre: str
    asunto: str
    descripcion: str
    ubicacion: Optional[str] = None
    estado: EstadoSolicitudEnum
    area: Optional[str] = None
    area_nombre: Optional[str] = None
    fecha_limite: date
    dias_restantes: Optional[int] = None  # None si ya está cerrada
    vencida: bool = False
    respuesta: Optional[str] = None
    respondido_por: Optional[str] = None
    fecha_respuesta: Optional[UTCDateTime] = None
    historial: List[EventoHistorial] = []
    documentos: List[DocumentoAdjunto] = []
    fecha_creacion: UTCDateTime
    fecha_actualizacion: UTCDateTime


class SolicitudAdminResponse(SolicitudResponse):
    ciudadano_nombre: str
    ciudadano_dni: str
    ciudadano_telefono: Optional[str] = None
    ciudadano_email: Optional[str] = None


class GestionSolicitudRequest(BaseModel):
    estado: EstadoSolicitudEnum
    respuesta: Optional[str] = Field(default=None, max_length=3000)
    nota_interna: Optional[str] = Field(default=None, max_length=1000)


class DerivarRequest(BaseModel):
    area: str = Field(max_length=30)
    motivo: str = Field(min_length=5, max_length=300)

    @field_validator("motivo")
    @classmethod
    def _strip(cls, v):
        v = v.strip()
        if len(v) < 5:
            raise ValueError("Indique el motivo de la derivación (mín. 5 caracteres).")
        return v


class ComentarioRequest(BaseModel):
    texto: str = Field(min_length=3, max_length=1000)

    @field_validator("texto")
    @classmethod
    def _strip(cls, v):
        v = v.strip()
        if len(v) < 3:
            raise ValueError("El comentario es demasiado corto.")
        return v


# ===== Notificaciones y seguimiento =====
class NotificacionResponse(ORMModel):
    id: int
    tipo: str
    titulo: str
    mensaje: str
    referencia: Optional[str] = None
    leida: bool
    fecha: UTCDateTime


class NotificacionesListado(BaseModel):
    no_leidas: int
    items: List[NotificacionResponse]


class EventoSeguimiento(BaseModel):
    fecha: UTCDateTime
    titulo: str
    detalle: Optional[str] = None
    tipo: str  # creacion | pago | estado | observacion | info


# ===== Registro y recuperación de contraseña =====
class RegistroRequest(BaseModel):
    dni: str
    nombre: str = Field(min_length=3, max_length=255)
    email: EmailStr
    telefono: Optional[str] = Field(default=None, max_length=20)
    password: str

    _dni = field_validator("dni")(classmethod(lambda cls, v: _validar_dni(v)))
    _pw = field_validator("password")(classmethod(lambda cls, v: _validar_password(v)))

    @field_validator("nombre")
    @classmethod
    def _nombre(cls, v):
        v = " ".join(v.split()).upper()
        if len(v) < 3:
            raise ValueError("Ingrese su nombre completo.")
        return v

    @field_validator("telefono")
    @classmethod
    def _tel(cls, v):
        if v in (None, ""):
            return None
        v = v.strip().replace(" ", "")
        if not v.lstrip("+").isdigit() or not 7 <= len(v) <= 15:
            raise ValueError("El teléfono debe tener entre 7 y 15 dígitos.")
        return v


class OlvideClaveRequest(BaseModel):
    dni: str
    _dni = field_validator("dni")(classmethod(lambda cls, v: _validar_dni(v)))


class RestablecerClaveRequest(BaseModel):
    dni: str
    codigo: str = Field(min_length=6, max_length=6)
    nueva_clave: str

    _dni = field_validator("dni")(classmethod(lambda cls, v: _validar_dni(v)))
    _pw = field_validator("nueva_clave")(classmethod(lambda cls, v: _validar_password(v)))

    @field_validator("codigo")
    @classmethod
    def _codigo(cls, v):
        if not v.isdigit():
            raise ValueError("El código tiene 6 dígitos.")
        return v


class AuditoriaView(ORMModel):
    id: int
    fecha: UTCDateTime
    usuario_dni: Optional[str] = None
    usuario_nombre: Optional[str] = None
    accion: str
    entidad: Optional[str] = None
    entidad_id: Optional[str] = None
    detalle: Optional[str] = None
