import enum
from datetime import date, datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import (
    JSON, Boolean, CheckConstraint, Column, Date, DateTime, Enum, ForeignKey,
    Integer, Numeric, String, UniqueConstraint, event, func,
)
from sqlalchemy.future import select
from sqlalchemy.orm import relationship

import config
from database import Base


def utc_now() -> datetime:
    """Fecha/hora actual en UTC (sin tzinfo, como se almacena en la base)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ===== Enums (únicos: los schemas los importan de aquí) =====
class TipoTramiteEnum(str, enum.Enum):
    LICENCIA_OBRA = "LICENCIA_OBRA"
    LICENCIA_FUNCIONAMIENTO = "LICENCIA_FUNCIONAMIENTO"
    PARTIDA_NACIMIENTO = "PARTIDA_NACIMIENTO"
    CONSTANCIA_NO_ADEUDO = "CONSTANCIA_NO_ADEUDO"
    CERTIFICADO_DOMICILIO = "CERTIFICADO_DOMICILIO"
    LICENCIA_EVENTO = "LICENCIA_EVENTO"
    COPIA_CERTIFICADA = "COPIA_CERTIFICADA"


class EstadoTramiteEnum(str, enum.Enum):
    PENDIENTE_PAGO = "PENDIENTE_PAGO"
    EN_EVALUACION = "EN_EVALUACION"
    OBSERVADO = "OBSERVADO"
    APROBADO = "APROBADO"
    RECHAZADO = "RECHAZADO"


class TipoDeudaEnum(str, enum.Enum):
    PREDIAL = "PREDIAL"
    ARBITRIOS = "ARBITRIOS"
    MULTA_TRANSITO = "MULTA_TRANSITO"
    LIMPIEZA_PUBLICA = "LIMPIEZA_PUBLICA"


class EstadoDeudaEnum(str, enum.Enum):
    PENDIENTE = "PENDIENTE"
    PAGADO = "PAGADO"
    VENCIDO = "VENCIDO"
    FRACCIONADO = "FRACCIONADO"


class MetodoPagoEnum(str, enum.Enum):
    TARJETA = "TARJETA"
    YAPE = "YAPE"
    PLIN = "PLIN"


class EstadoPagoEnum(str, enum.Enum):
    PENDIENTE = "PENDIENTE"
    COMPLETADO = "COMPLETADO"
    FALLIDO = "FALLIDO"


NOMBRES_TRAMITE = {
    TipoTramiteEnum.LICENCIA_OBRA: "Licencia de Obra",
    TipoTramiteEnum.LICENCIA_FUNCIONAMIENTO: "Licencia de Funcionamiento",
    TipoTramiteEnum.PARTIDA_NACIMIENTO: "Partida de Nacimiento",
    TipoTramiteEnum.CONSTANCIA_NO_ADEUDO: "Constancia de No Adeudo",
    TipoTramiteEnum.CERTIFICADO_DOMICILIO: "Certificado de Domicilio",
    TipoTramiteEnum.LICENCIA_EVENTO: "Licencia para Evento",
    TipoTramiteEnum.COPIA_CERTIFICADA: "Copia Certificada de Documento",
}
NOMBRES_DEUDA = {
    TipoDeudaEnum.PREDIAL: "Impuesto Predial",
    TipoDeudaEnum.ARBITRIOS: "Arbitrios Municipales",
    TipoDeudaEnum.MULTA_TRANSITO: "Multa de Tránsito",
    TipoDeudaEnum.LIMPIEZA_PUBLICA: "Limpieza Pública",
}

# Costos oficiales (única fuente de verdad; el cliente nunca manda el precio)
COSTOS_TRAMITE = {
    TipoTramiteEnum.LICENCIA_OBRA: Decimal("250.00"),
    TipoTramiteEnum.LICENCIA_FUNCIONAMIENTO: Decimal("120.50"),
    TipoTramiteEnum.PARTIDA_NACIMIENTO: Decimal("15.00"),
    TipoTramiteEnum.CONSTANCIA_NO_ADEUDO: Decimal("8.50"),
    TipoTramiteEnum.CERTIFICADO_DOMICILIO: Decimal("12.00"),
    TipoTramiteEnum.LICENCIA_EVENTO: Decimal("85.00"),
    TipoTramiteEnum.COPIA_CERTIFICADA: Decimal("5.50"),
}
_SIGLAS = {
    TipoTramiteEnum.LICENCIA_OBRA: "LOB",
    TipoTramiteEnum.LICENCIA_FUNCIONAMIENTO: "LFU",
    TipoTramiteEnum.PARTIDA_NACIMIENTO: "PNA",
    TipoTramiteEnum.CONSTANCIA_NO_ADEUDO: "CNA",
    TipoTramiteEnum.CERTIFICADO_DOMICILIO: "CDO",
    TipoTramiteEnum.LICENCIA_EVENTO: "LEV",
    TipoTramiteEnum.COPIA_CERTIFICADA: "CCE",
}


# ===== Modelos =====
class Ciudadano(Base):
    __tablename__ = "ciudadano"

    id = Column(Integer, primary_key=True, index=True)
    dni = Column(String(8), unique=True, index=True, nullable=False)
    nombre = Column(String(255), nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=True)
    telefono = Column(String(20), nullable=True)
    direccion = Column(String(255), nullable=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="ciudadano")  # ciudadano | funcionario | admin
    area = Column(String(30), nullable=True)  # solo funcionarios: área a la que pertenecen
    fecha_registro = Column(DateTime, default=utc_now)

    tramites = relationship("Tramite", back_populates="ciudadano", cascade="all, delete-orphan")
    deudas = relationship("Deuda", back_populates="ciudadano", cascade="all, delete-orphan")


class ClaseSolicitudEnum(str, enum.Enum):
    QUEJA = "QUEJA"
    RECLAMO = "RECLAMO"
    PETICION = "PETICION"


class EstadoSolicitudEnum(str, enum.Enum):
    RECIBIDA = "RECIBIDA"
    EN_ATENCION = "EN_ATENCION"
    ATENDIDA = "ATENDIDA"
    IMPROCEDENTE = "IMPROCEDENTE"


ESTADOS_SOLICITUD_CERRADOS = (EstadoSolicitudEnum.ATENDIDA, EstadoSolicitudEnum.IMPROCEDENTE)
_PREFIJOS_SOLICITUD = {ClaseSolicitudEnum.QUEJA: "QJ", ClaseSolicitudEnum.RECLAMO: "RC", ClaseSolicitudEnum.PETICION: "PT"}


class Tramite(Base):
    __tablename__ = "tramite"

    id = Column(Integer, primary_key=True, index=True)
    expediente = Column(String(50), unique=True, index=True, nullable=False)
    tipo = Column(Enum(TipoTramiteEnum), nullable=False)
    estado = Column(Enum(EstadoTramiteEnum), default=EstadoTramiteEnum.PENDIENTE_PAGO, nullable=False)
    costo_total = Column(Numeric(10, 2), nullable=False, default=Decimal("0.00"))

    detalles = Column(JSON, nullable=True)  # datos libres del solicitante (dict)
    observaciones = Column(JSON, nullable=False, default=list)  # [{fecha, autor, estado, texto}]
    documentos = Column(JSON, nullable=False, default=list)  # nombres de archivo guardados

    fecha_creacion = Column(DateTime, default=utc_now)
    fecha_actualizacion = Column(DateTime, default=utc_now, onupdate=utc_now)

    ciudadano_id = Column(Integer, ForeignKey("ciudadano.id"), nullable=False, index=True)

    ciudadano = relationship("Ciudadano", back_populates="tramites")
    pagos = relationship("Pago", back_populates="tramite_asociado", cascade="all, delete-orphan")


class Solicitud(Base):
    """Queja, reclamo o petición del ciudadano, con código de seguimiento, plazo y respuesta oficial."""
    __tablename__ = "solicitud"

    id = Column(Integer, primary_key=True, index=True)
    codigo = Column(String(30), unique=True, index=True, nullable=False)  # p. ej. QJ-2026-00001
    clase = Column(Enum(ClaseSolicitudEnum), nullable=False, index=True)
    categoria = Column(String(40), nullable=False)
    asunto = Column(String(150), nullable=False)
    descripcion = Column(String(3000), nullable=False)
    ubicacion = Column(String(255), nullable=True)
    area = Column(String(30), nullable=True, index=True)  # área responsable (se puede derivar)
    estado = Column(Enum(EstadoSolicitudEnum), default=EstadoSolicitudEnum.RECIBIDA, nullable=False, index=True)

    fecha_limite = Column(Date, nullable=False)  # plazo de atención
    respuesta = Column(String(3000), nullable=True)  # respuesta oficial
    respondido_por = Column(String(255), nullable=True)
    fecha_respuesta = Column(DateTime, nullable=True)

    historial = Column(JSON, nullable=False, default=list)  # línea de tiempo [{fecha, autor, evento, texto, visible}]
    documentos = Column(JSON, nullable=False, default=list)

    fecha_creacion = Column(DateTime, default=utc_now)
    fecha_actualizacion = Column(DateTime, default=utc_now, onupdate=utc_now)

    ciudadano_id = Column(Integer, ForeignKey("ciudadano.id"), nullable=False, index=True)
    ciudadano = relationship("Ciudadano")


class Notificacion(Base):
    """Aviso dentro del portal para un ciudadano (o funcionario)."""
    __tablename__ = "notificacion"

    id = Column(Integer, primary_key=True, index=True)
    ciudadano_id = Column(Integer, ForeignKey("ciudadano.id"), nullable=False, index=True)
    tipo = Column(String(20), nullable=False)  # TRAMITE | PAGO | QUEJA | RECLAMO | PETICION | SISTEMA
    titulo = Column(String(120), nullable=False)
    mensaje = Column(String(500), nullable=False)
    referencia = Column(String(60), nullable=True)  # p. ej. "tramite:12", "solicitud:3"
    leida = Column(Boolean, default=False, nullable=False)
    fecha = Column(DateTime, default=utc_now, index=True)


class Auditoria(Base):
    """Registro de acciones del personal y de seguridad: quién hizo qué y cuándo."""
    __tablename__ = "auditoria"

    id = Column(Integer, primary_key=True, index=True)
    fecha = Column(DateTime, default=utc_now, index=True)
    usuario_dni = Column(String(8), nullable=True)
    usuario_nombre = Column(String(255), nullable=True)
    accion = Column(String(40), nullable=False, index=True)
    entidad = Column(String(30), nullable=True)
    entidad_id = Column(String(40), nullable=True)
    detalle = Column(String(500), nullable=True)


class CodigoRecuperacion(Base):
    """Código de 6 dígitos para restablecer la contraseña (solo se guarda su huella, nunca el código)."""
    __tablename__ = "codigo_recuperacion"

    id = Column(Integer, primary_key=True, index=True)
    ciudadano_id = Column(Integer, ForeignKey("ciudadano.id"), nullable=False, index=True)
    huella = Column(String(64), nullable=False)
    expira = Column(DateTime, nullable=False)
    intentos = Column(Integer, nullable=False, default=0)
    usado = Column(Boolean, nullable=False, default=False)
    fecha = Column(DateTime, default=utc_now)


class Deuda(Base):
    __tablename__ = "deuda"

    id = Column(Integer, primary_key=True, index=True)
    tipo = Column(Enum(TipoDeudaEnum), nullable=False)

    monto_base = Column(Numeric(10, 2), nullable=False)
    intereses_moratorios = Column(Numeric(10, 2), default=Decimal("0.00"), nullable=False)
    monto_total = Column(Numeric(10, 2), nullable=False)

    periodo = Column(String(50), nullable=True)
    fecha_vencimiento = Column(Date, nullable=False)
    estado = Column(Enum(EstadoDeudaEnum), default=EstadoDeudaEnum.PENDIENTE, nullable=False)
    esta_vencida = Column(Boolean, default=False, nullable=False)

    ciudadano_id = Column(Integer, ForeignKey("ciudadano.id"), nullable=False, index=True)

    ciudadano = relationship("Ciudadano", back_populates="deudas")
    pagos = relationship("Pago", back_populates="deuda_asociada", cascade="all, delete-orphan")
    cuotas = relationship(
        "Cuota", back_populates="deuda", cascade="all, delete-orphan", order_by="Cuota.numero"
    )


class Cuota(Base):
    """Cuota de un plan de fraccionamiento."""
    __tablename__ = "cuota"
    __table_args__ = (UniqueConstraint("deuda_id", "numero", name="uq_cuota_deuda_numero"),)

    id = Column(Integer, primary_key=True)
    deuda_id = Column(Integer, ForeignKey("deuda.id"), nullable=False, index=True)
    numero = Column(Integer, nullable=False)
    monto = Column(Numeric(10, 2), nullable=False)
    fecha_vencimiento = Column(Date, nullable=False)
    estado = Column(Enum(EstadoDeudaEnum), default=EstadoDeudaEnum.PENDIENTE, nullable=False)

    deuda = relationship("Deuda", back_populates="cuotas")


class Pago(Base):
    __tablename__ = "pago"
    __table_args__ = (
        CheckConstraint(
            "(tramite_id IS NOT NULL AND deuda_id IS NULL) OR (tramite_id IS NULL AND deuda_id IS NOT NULL)",
            name="ck_pago_un_solo_destino",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    monto = Column(Numeric(10, 2), nullable=False)
    metodo = Column(Enum(MetodoPagoEnum), nullable=False)
    estado = Column(Enum(EstadoPagoEnum), default=EstadoPagoEnum.PENDIENTE, nullable=False)
    fecha_pago = Column(DateTime, default=utc_now)
    comprobante_url = Column(String(255), nullable=True)

    # Datos del cobro (todos opcionales: los pagos antiguos no los tienen)
    concepto = Column(String(255), nullable=True)
    monto_base = Column(Numeric(10, 2), nullable=True)
    intereses = Column(Numeric(10, 2), nullable=True)
    transaccion_id = Column(String(40), nullable=True, index=True)
    codigo_autorizacion = Column(String(20), nullable=True)
    detalle_metodo = Column(String(60), nullable=True)  # p. ej. "VISA ****4242" (nunca el número completo)
    motivo_rechazo = Column(String(255), nullable=True)

    tramite_id = Column(Integer, ForeignKey("tramite.id"), nullable=True, index=True)
    deuda_id = Column(Integer, ForeignKey("deuda.id"), nullable=True, index=True)

    tramite_asociado = relationship("Tramite", back_populates="pagos")
    deuda_asociada = relationship("Deuda", back_populates="pagos")

    @property
    def numero_comprobante(self) -> str:
        return f"{config.COMPROBANTE_SERIE}-{self.id:08d}"


# ===== Eventos =====
@event.listens_for(Tramite, "before_insert")
def _asignar_expediente_y_costo(mapper, connection, target):
    """Genera el nº de expediente (AAAA-NNNNN-SIG) y fija el costo oficial.

    Usa MAX del correlativo del año (no COUNT), así no se repite si se borran trámites.
    La columna es UNIQUE: ante una carrera extrema la BD rechaza el duplicado.
    """
    year = datetime.now(ZoneInfo(config.APP_TIMEZONE)).year
    last = connection.execute(
        select(func.max(Tramite.expediente)).where(Tramite.expediente.like(f"{year}-%"))
    ).scalar()
    siguiente = int(last.split("-")[1]) + 1 if last else 1
    target.expediente = f"{year}-{siguiente:05d}-{_SIGLAS.get(target.tipo, 'TRA')}"

    if not target.costo_total:
        target.costo_total = COSTOS_TRAMITE.get(target.tipo, Decimal("10.00"))


@event.listens_for(Deuda, "before_insert")
def _normalizar_deuda(mapper, connection, target):
    if not target.monto_total:
        target.monto_total = (target.monto_base or Decimal("0")) + (target.intereses_moratorios or Decimal("0"))
    if target.estado in (None, EstadoDeudaEnum.PENDIENTE) and target.fecha_vencimiento < date.today():
        target.esta_vencida = True
        target.estado = EstadoDeudaEnum.VENCIDO


@event.listens_for(Solicitud, "before_insert")
def _asignar_codigo_solicitud(mapper, connection, target):
    """Código de seguimiento PP-AAAA-NNNNN (correlativo por año y clase, por MAX como el expediente)."""
    year = datetime.now(ZoneInfo(config.APP_TIMEZONE)).year
    pref = _PREFIJOS_SOLICITUD[target.clase]
    last = connection.execute(
        select(func.max(Solicitud.codigo)).where(Solicitud.codigo.like(f"{pref}-{year}-%"))
    ).scalar()
    siguiente = int(last.split("-")[2]) + 1 if last else 1
    target.codigo = f"{pref}-{year}-{siguiente:05d}"
