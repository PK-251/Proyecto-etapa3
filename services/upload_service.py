"""Guardado seguro de documentos: nombre aleatorio, tamaño limitado y verificación del contenido real."""
import os
import re
import uuid
from pathlib import Path
from typing import Dict, List

from fastapi import HTTPException, UploadFile

import config

# extensión -> (firma inicial del archivo, content-type)
TIPOS_PERMITIDOS = {
    ".pdf": (b"%PDF-", "application/pdf"),
    ".png": (b"\x89PNG\r\n\x1a\n", "image/png"),
    ".jpg": (b"\xff\xd8\xff", "image/jpeg"),
    ".jpeg": (b"\xff\xd8\xff", "image/jpeg"),
}
_CHUNK = 64 * 1024
_ARCHIVO_RE = re.compile(r"^[0-9a-f]{32}\.(pdf|png|jpg|jpeg)$")


def nombre_archivo_valido(nombre: str) -> bool:
    return bool(_ARCHIVO_RE.match(nombre))


def content_type_de(nombre: str) -> str:
    return TIPOS_PERMITIDOS[Path(nombre).suffix.lower()][1]


def ruta_documento(nombre: str) -> Path:
    return config.UPLOADS_DIR / nombre


def _nombre_para_mostrar(filename: str) -> str:
    base = os.path.basename((filename or "documento").replace("\\", "/"))
    base = re.sub(r"[^\w.\- ]", "_", base)[:100]
    return base or "documento"


async def guardar_documento(file: UploadFile) -> Dict[str, str]:
    """Valida y guarda un archivo. Devuelve {"archivo": <nombre en disco>, "nombre": <nombre original>}."""
    nombre_original = _nombre_para_mostrar(file.filename)
    ext = Path(nombre_original).suffix.lower()
    if ext not in TIPOS_PERMITIDOS:
        raise HTTPException(
            400, f"Tipo de archivo no permitido: '{ext or 'sin extensión'}'. Solo se permite PDF, JPG o PNG."
        )

    firma = TIPOS_PERMITIDOS[ext][0]
    cabecera = await file.read(len(firma))
    if not cabecera.startswith(firma):
        raise HTTPException(400, f"El contenido de '{nombre_original}' no corresponde a un archivo {ext[1:].upper()}.")

    config.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    archivo = f"{uuid.uuid4().hex}{ext}"
    destino = ruta_documento(archivo)
    total = len(cabecera)
    try:
        with open(destino, "wb") as out:
            out.write(cabecera)
            while chunk := await file.read(_CHUNK):
                total += len(chunk)
                if total > config.MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        413, f"'{nombre_original}' supera el máximo de {config.MAX_UPLOAD_MB} MB."
                    )
                out.write(chunk)
    except BaseException:
        destino.unlink(missing_ok=True)
        raise
    return {"archivo": archivo, "nombre": nombre_original}


def borrar_documentos(items: List[Dict[str, str]]) -> None:
    for it in items:
        ruta_documento(it["archivo"]).unlink(missing_ok=True)
