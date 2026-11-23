"""Catálogo de servicios: trámites (requisitos, costos, plazos, campos) y categorías de quejas/reclamos/peticiones.

El costo oficial sigue viviendo en models.COSTOS_TRAMITE; aquí está lo demás.
"""
from datetime import date, timedelta
from typing import Any, Dict, List

import config
from feriados import es_dia_habil
from models import COSTOS_TRAMITE, NOMBRES_TRAMITE, ClaseSolicitudEnum, TipoTramiteEnum as T

# tipo de campo: text | textarea | number | date | select
CATALOGO_TRAMITES: Dict[T, Dict[str, Any]] = {
    T.CONSTANCIA_NO_ADEUDO: {
        "categoria": "Certificados y constancias",
        "descripcion": "Documento que acredita que no tienes deudas tributarias ni multas pendientes con la municipalidad.",
        "plazo_dias": 2,
        "requisitos": [
            "DNI vigente (copia o foto legible)",
            "No registrar deudas pendientes en 'Mis deudas' (se verifica automáticamente)",
        ],
        "campos": [
            {"id": "motivo", "label": "Motivo de la constancia", "tipo": "select", "requerido": True,
             "opciones": ["Trámite bancario", "Trámite judicial o notarial", "Compra o venta de inmueble", "Otro"]},
        ],
        "valida_deudas": True,
    },
    T.CERTIFICADO_DOMICILIO: {
        "categoria": "Certificados y constancias",
        "descripcion": "Certifica el domicilio que declaras dentro del distrito.",
        "plazo_dias": 3,
        "requisitos": ["DNI vigente", "Recibo reciente de luz o agua a tu nombre o del propietario"],
        "campos": [
            {"id": "direccion", "label": "Dirección a certificar", "tipo": "text", "requerido": True},
            {"id": "tiempo_residencia", "label": "Tiempo de residencia", "tipo": "select", "requerido": True,
             "opciones": ["Menos de 1 año", "Entre 1 y 5 años", "Más de 5 años"]},
        ],
    },
    T.LICENCIA_EVENTO: {
        "categoria": "Licencias y autorizaciones",
        "descripcion": "Autorización para realizar eventos públicos o con fines de lucro (ferias, conciertos, campeonatos).",
        "plazo_dias": 7,
        "requisitos": [
            "DNI del organizador",
            "Croquis o descripción del lugar",
            "Constancia de seguridad o Defensa Civil si el aforo supera 100 personas",
        ],
        "campos": [
            {"id": "nombre_evento", "label": "Nombre del evento", "tipo": "text", "requerido": True},
            {"id": "fecha_evento", "label": "Fecha del evento", "tipo": "date", "requerido": True},
            {"id": "lugar", "label": "Lugar", "tipo": "text", "requerido": True},
            {"id": "aforo", "label": "Aforo estimado (personas)", "tipo": "number", "requerido": True},
        ],
    },
    T.COPIA_CERTIFICADA: {
        "categoria": "Certificados y constancias",
        "descripcion": "Copia fedateada de un documento que obra en archivo municipal.",
        "plazo_dias": 2,
        "requisitos": ["DNI vigente", "Datos del documento (tipo, número y año) o número de expediente"],
        "campos": [
            {"id": "documento", "label": "Documento solicitado (tipo, número, año)", "tipo": "text", "requerido": True},
            {"id": "num_copias", "label": "Número de copias", "tipo": "number", "requerido": True, "min": 1, "max": 20},
        ],
    },
    T.LICENCIA_OBRA: {
        "categoria": "Licencias y autorizaciones",
        "descripcion": "Autorización para construir, ampliar o remodelar.",
        "plazo_dias": 15,
        "requisitos": ["Título de propiedad o documento que acredite derecho a edificar", "Planos firmados por arquitecto o ingeniero", "DNI vigente"],
        "campos": [],
    },
    T.LICENCIA_FUNCIONAMIENTO: {
        "categoria": "Licencias y autorizaciones",
        "descripcion": "Autorización para operar un negocio en un local determinado.",
        "plazo_dias": 10,
        "requisitos": ["RUC activo", "Contrato o título del local", "Certificado de seguridad cuando corresponda", "DNI vigente"],
        "campos": [],
    },
    T.PARTIDA_NACIMIENTO: {
        "categoria": "Registro civil",
        "descripcion": "Copia certificada de partida de nacimiento inscrita en el registro civil de la municipalidad.",
        "plazo_dias": 3,
        "requisitos": ["DNI del solicitante", "Datos del inscrito (nombres, fecha y lugar de nacimiento)"],
        "campos": [],
    },
}


def catalogo_publico() -> List[Dict[str, Any]]:
    return [
        {
            "tipo": tipo.value,
            "nombre": NOMBRES_TRAMITE[tipo],
            "costo": str(COSTOS_TRAMITE[tipo]),
            **{k: v for k, v in datos.items() if k != "valida_deudas"},
        }
        for tipo, datos in CATALOGO_TRAMITES.items()
    ]


def validar_detalles(tipo: T, detalles: Dict[str, Any] | None) -> Dict[str, Any]:
    """Valida los campos propios del trámite y devuelve los detalles limpios. Lanza ValueError con el motivo."""
    detalles = dict(detalles or {})
    for campo in CATALOGO_TRAMITES.get(tipo, {}).get("campos", []):
        valor = detalles.get(campo["id"])
        valor = valor.strip() if isinstance(valor, str) else valor
        if valor in (None, ""):
            if campo.get("requerido"):
                raise ValueError(f"Falta el dato: {campo['label']}.")
            detalles.pop(campo["id"], None)
            continue
        if campo["tipo"] == "select" and valor not in campo["opciones"]:
            raise ValueError(f"Valor no válido en: {campo['label']}.")
        if campo["tipo"] == "number":
            try:
                n = int(valor)
            except (TypeError, ValueError):
                raise ValueError(f"{campo['label']} debe ser un número entero.")
            if not campo.get("min", 1) <= n <= campo.get("max", 100000):
                raise ValueError(f"{campo['label']} fuera de rango.")
            valor = n
        if campo["tipo"] == "date":
            try:
                date.fromisoformat(str(valor))
            except ValueError:
                raise ValueError(f"{campo['label']} no es una fecha válida (AAAA-MM-DD).")
        if isinstance(valor, str) and len(valor) > 300:
            raise ValueError(f"{campo['label']} es demasiado largo (máx. 300 caracteres).")
        detalles[campo["id"]] = valor
    return detalles


# ===== Quejas, reclamos y peticiones =====
CATEGORIAS_SOLICITUD: Dict[ClaseSolicitudEnum, Dict[str, str]] = {
    ClaseSolicitudEnum.QUEJA: {
        "ATENCION_FUNCIONARIO": "Mala atención de un funcionario o servidor",
        "DEMORA_TRAMITE": "Demora o incumplimiento de plazos en un trámite",
        "SERVICIO_DEFICIENTE": "Servicio municipal deficiente",
        "OTRO": "Otro motivo",
    },
    ClaseSolicitudEnum.RECLAMO: {
        "COBRO_INDEBIDO": "Cobro indebido o monto incorrecto (tributos, arbitrios)",
        "LIMPIEZA_PUBLICA": "Limpieza pública y recojo de residuos",
        "ALUMBRADO": "Alumbrado público",
        "TRANSITO": "Multa o papeleta de tránsito",
        "OTRO": "Otro motivo",
    },
    ClaseSolicitudEnum.PETICION: {
        "SOLICITUD_INFORMACION": "Acceso a la información pública",
        "SOLICITUD_SERVICIO": "Solicitud de servicio (poda, bacheo, fumigación…)",
        "PETICION_ADMINISTRATIVA": "Petición administrativa o autorización",
        "SUGERENCIA": "Sugerencia o propuesta de mejora",
    },
}

NOMBRES_CLASE = {
    ClaseSolicitudEnum.QUEJA: "Queja",
    ClaseSolicitudEnum.RECLAMO: "Reclamo",
    ClaseSolicitudEnum.PETICION: "Petición",
}


def plazo_dias_solicitud(clase: ClaseSolicitudEnum, categoria: str) -> int:
    if clase == ClaseSolicitudEnum.QUEJA:
        return config.PLAZO_QUEJA_DIAS
    if clase == ClaseSolicitudEnum.RECLAMO:
        return config.PLAZO_RECLAMO_DIAS
    return config.PLAZO_INFORMACION_DIAS if categoria == "SOLICITUD_INFORMACION" else config.PLAZO_PETICION_DIAS


def sumar_dias_habiles(desde: date, dias: int) -> date:
    """Suma días hábiles: lunes a viernes, sin feriados nacionales ni los de FERIADOS_EXTRA."""
    actual = desde
    while dias > 0:
        actual += timedelta(days=1)
        if es_dia_habil(actual):
            dias -= 1
    return actual


# ===== Áreas municipales (para roles de funcionario y derivación) =====
AREAS: Dict[str, str] = {
    "MESA_PARTES": "Mesa de Partes",
    "RENTAS": "Rentas y Tributos",
    "SERVICIOS_PUBLICOS": "Servicios Públicos",
    "OBRAS": "Obras y Desarrollo Urbano",
    "REGISTRO_CIVIL": "Registro Civil",
    "ATENCION_CIUDADANO": "Atención al Ciudadano",
}

AREA_DE_TRAMITE = {
    T.LICENCIA_OBRA: "OBRAS",
    T.LICENCIA_FUNCIONAMIENTO: "OBRAS",
    T.PARTIDA_NACIMIENTO: "REGISTRO_CIVIL",
    T.CONSTANCIA_NO_ADEUDO: "RENTAS",
    T.CERTIFICADO_DOMICILIO: "MESA_PARTES",
    T.LICENCIA_EVENTO: "SERVICIOS_PUBLICOS",
    T.COPIA_CERTIFICADA: "MESA_PARTES",
}

AREA_DE_CATEGORIA = {
    "COBRO_INDEBIDO": "RENTAS",
    "LIMPIEZA_PUBLICA": "SERVICIOS_PUBLICOS",
    "ALUMBRADO": "SERVICIOS_PUBLICOS",
    "TRANSITO": "SERVICIOS_PUBLICOS",
    "SOLICITUD_SERVICIO": "SERVICIOS_PUBLICOS",
    "SOLICITUD_INFORMACION": "MESA_PARTES",
    "PETICION_ADMINISTRATIVA": "MESA_PARTES",
}


def area_de_tramite(tipo) -> str:
    return AREA_DE_TRAMITE.get(tipo, "MESA_PARTES")


def area_de_solicitud(categoria: str) -> str:
    """Área que recibe el caso por defecto; el resto va a Atención al Ciudadano."""
    return AREA_DE_CATEGORIA.get(categoria, "ATENCION_CIUDADANO")
