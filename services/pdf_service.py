"""Generación de la boleta / comprobante de pago en PDF (HU-007)."""
from datetime import datetime, timezone
from decimal import Decimal
from io import BytesIO
from typing import Union
from zoneinfo import ZoneInfo

import qrcode
from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfgen import canvas

import config
from models import NOMBRES_DEUDA, NOMBRES_TRAMITE, Ciudadano, Deuda, Pago, Tramite
from services import verificacion

ANCHO, ALTO = A4
MARGEN = 18 * mm
AZUL = HexColor("#0F4C81")
AZUL_CLARO = HexColor("#EAF1F8")
GRIS = HexColor("#6B7280")
GRIS_BORDE = HexColor("#D9E0E8")
TEXTO = HexColor("#1F2937")
VERDE = HexColor("#15803D")

# ---------------- Importe en letras ----------------
_UNI = ["", "UNO", "DOS", "TRES", "CUATRO", "CINCO", "SEIS", "SIETE", "OCHO", "NUEVE", "DIEZ", "ONCE", "DOCE",
        "TRECE", "CATORCE", "QUINCE", "DIECISÉIS", "DIECISIETE", "DIECIOCHO", "DIECINUEVE", "VEINTE",
        "VEINTIUNO", "VEINTIDÓS", "VEINTITRÉS", "VEINTICUATRO", "VEINTICINCO", "VEINTISÉIS", "VEINTISIETE",
        "VEINTIOCHO", "VEINTINUEVE"]
_DEC = ["", "", "", "TREINTA", "CUARENTA", "CINCUENTA", "SESENTA", "SETENTA", "OCHENTA", "NOVENTA"]
_CEN = ["", "CIENTO", "DOSCIENTOS", "TRESCIENTOS", "CUATROCIENTOS", "QUINIENTOS", "SEISCIENTOS", "SETECIENTOS",
        "OCHOCIENTOS", "NOVECIENTOS"]


def _menor_mil(n: int) -> str:
    if n == 100:
        return "CIEN"
    c, resto = divmod(n, 100)
    partes = [_CEN[c]] if c else []
    if resto < 30:
        if resto:
            partes.append(_UNI[resto])
    else:
        d, u = divmod(resto, 10)
        partes.append(_DEC[d] + (f" Y {_UNI[u]}" if u else ""))
    return " ".join(partes)


def _apocope(texto: str) -> str:
    """UNO -> UN y VEINTIUNO -> VEINTIÚN cuando va antes de MIL / MILLONES."""
    if texto.endswith("VEINTIUNO"):
        return texto[:-9] + "VEINTIÚN"
    if texto.endswith("UNO"):
        return texto[:-3] + "UN"
    return texto


def numero_a_letras(n: int) -> str:
    if n == 0:
        return "CERO"
    if n >= 1_000_000_000:
        raise ValueError("Importe demasiado grande")
    partes = []
    millones, resto = divmod(n, 1_000_000)
    miles, unidades = divmod(resto, 1000)
    if millones:
        partes.append("UN MILLÓN" if millones == 1 else f"{_apocope(numero_a_letras(millones))} MILLONES")
    if miles:
        partes.append("MIL" if miles == 1 else f"{_apocope(_menor_mil(miles))} MIL")
    if unidades:
        partes.append(_menor_mil(unidades))
    return " ".join(partes)


def importe_en_letras(monto: Decimal) -> str:
    entero, centavos = divmod(int((Decimal(monto) * 100).to_integral_value()), 100)
    return f"{numero_a_letras(entero)} CON {centavos:02d}/100 SOLES"


# ---------------- Utilidades de dibujo ----------------
def _fecha_local(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(config.APP_TIMEZONE))


def _texto(c, x, y, txt, fuente="Helvetica", tam=9, color=TEXTO, ancho=None, interlineado=None, derecha=False, centro=False):
    """Dibuja texto (con ajuste de línea si se da `ancho`). Devuelve la Y final."""
    c.setFillColor(color)
    c.setFont(fuente, tam)
    lineas = simpleSplit(str(txt), fuente, tam, ancho) if ancho else [str(txt)]
    paso = interlineado or tam * 1.3
    for i, linea in enumerate(lineas):
        dibujar = c.drawRightString if derecha else c.drawCentredString if centro else c.drawString
        dibujar(x, y - i * paso, linea)
    return y - len(lineas) * paso


def _etiqueta_valor(c, x, y, etiqueta, valor, ancho):
    _texto(c, x, y, etiqueta.upper(), "Helvetica-Bold", 6.5, GRIS)
    return _texto(c, x, y - 4.2 * mm, valor, "Helvetica-Bold", 9.5, TEXTO, ancho=ancho)


def _marca_demo(c):
    c.saveState()
    c.setFillColor(HexColor("#0F4C81"))
    c.setFillAlpha(0.06)
    c.setFont("Helvetica-Bold", 78)
    c.translate(ANCHO / 2, ALTO / 2 - 10 * mm)
    c.rotate(35)
    c.drawCentredString(0, 0, "DEMOSTRACIÓN")
    c.restoreState()


def _qr(url: str) -> ImageReader:
    qr = qrcode.QRCode(box_size=8, border=1, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(url)
    qr.make(fit=True)
    return ImageReader(qr.make_image(fill_color="#0F4C81", back_color="white").get_image())


def _filas_detalle(pago: Pago, item: Union[Deuda, Tramite]):
    """[(descripcion, referencia, importe)], subtotal, intereses"""
    if isinstance(item, Deuda):
        nombre = NOMBRES_DEUDA.get(item.tipo, item.tipo.value)
        ref = f"Periodo {item.periodo or '-'}"
        base = Decimal(pago.monto_base if pago.monto_base is not None else item.monto_base)
        interes = Decimal(pago.intereses if pago.intereses is not None else item.intereses_moratorios)
        filas = [(f"{nombre}", ref, base)]
        if interes > 0:
            filas.append(("Intereses moratorios", f"Venc. {item.fecha_vencimiento:%d/%m/%Y}", interes))
        return filas, base, interes
    nombre = NOMBRES_TRAMITE.get(item.tipo, item.tipo.value)
    base = Decimal(pago.monto)
    return [(f"Derecho de trámite: {nombre}", f"Exp. {item.expediente}", base)], base, Decimal("0.00")


# ---------------- Boleta ----------------
def generar_comprobante_pdf(pago: Pago, ciudadano: Ciudadano, item_pagado: Union[Deuda, Tramite]) -> BytesIO:
    """Genera la boleta de pago en PDF (A4) con QR de verificación firmado."""
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    c.setTitle(f"Boleta {pago.numero_comprobante}")
    c.setAuthor(config.MUNI_NOMBRE)
    c.setSubject("Comprobante de pago")

    if config.MODO_DEMO:
        _marca_demo(c)

    # --- Cabecera ---
    alto_cab = 36 * mm
    c.setFillColor(AZUL)
    c.rect(0, ALTO - alto_cab, ANCHO, alto_cab, fill=1, stroke=0)
    y = ALTO - 13 * mm
    _texto(c, MARGEN, y, config.MUNI_NOMBRE.upper(), "Helvetica-Bold", 14, white)
    _texto(c, MARGEN, y - 6 * mm, "Sistema de Trámites y Pagos en Línea", "Helvetica", 9.5, HexColor("#CFE0F1"))
    datos_emisor = [
        f"RUC {config.MUNI_RUC}" if config.MUNI_RUC else "",
        config.MUNI_DIRECCION,
        f"Tel. {config.MUNI_TELEFONO}" if config.MUNI_TELEFONO else "",
    ]
    pie_cab = "  ·  ".join(dato for dato in datos_emisor if dato)
    _texto(c, MARGEN, y - 11.5 * mm, pie_cab, "Helvetica", 7.5, HexColor("#CFE0F1"))

    # Recuadro con tipo y número de documento
    cw, ch = 62 * mm, 25 * mm
    cx, cy = ANCHO - MARGEN - cw, ALTO - alto_cab / 2 - ch / 2
    c.setFillColor(white)
    c.roundRect(cx, cy, cw, ch, 3 * mm, fill=1, stroke=0)
    _texto(c, cx + cw / 2, cy + ch - 7 * mm, "BOLETA DE PAGO", "Helvetica-Bold", 9, AZUL, centro=True)
    _texto(c, cx + cw / 2, cy + ch - 15 * mm, pago.numero_comprobante, "Helvetica-Bold", 15, AZUL, centro=True)
    _texto(c, cx + cw / 2, cy + 3.5 * mm, "PAGO CONFIRMADO", "Helvetica-Bold", 8, VERDE, centro=True)

    # --- Contribuyente ---
    y = ALTO - alto_cab - 11 * mm
    _texto(c, MARGEN, y, "DATOS DEL CONTRIBUYENTE", "Helvetica-Bold", 9, AZUL)
    y -= 3 * mm
    panel_h = 24 * mm
    c.setFillColor(AZUL_CLARO)
    c.roundRect(MARGEN, y - panel_h, ANCHO - 2 * MARGEN, panel_h, 2 * mm, fill=1, stroke=0)
    mitad = (ANCHO - 2 * MARGEN) / 2
    _etiqueta_valor(c, MARGEN + 4 * mm, y - 6 * mm, "Nombre / Razón social", ciudadano.nombre, mitad - 8 * mm)
    _etiqueta_valor(c, MARGEN + mitad, y - 6 * mm, "DNI", ciudadano.dni, mitad - 8 * mm)
    _etiqueta_valor(c, MARGEN + 4 * mm, y - 15 * mm, "Dirección", ciudadano.direccion or "No registrada", mitad - 8 * mm)
    emision = _fecha_local(pago.fecha_pago)
    _etiqueta_valor(c, MARGEN + mitad, y - 15 * mm, "Fecha y hora de pago", emision.strftime("%d/%m/%Y  %H:%M:%S"), mitad - 8 * mm)
    y -= panel_h + 9 * mm

    # --- Detalle ---
    _texto(c, MARGEN, y, "DETALLE DEL PAGO", "Helvetica-Bold", 9, AZUL)
    y -= 3 * mm
    x_desc, x_ref, x_imp = MARGEN + 3 * mm, MARGEN + 100 * mm, ANCHO - MARGEN - 3 * mm
    c.setFillColor(AZUL)
    c.roundRect(MARGEN, y - 8 * mm, ANCHO - 2 * MARGEN, 8 * mm, 1.5 * mm, fill=1, stroke=0)
    _texto(c, x_desc, y - 5.3 * mm, "Descripción", "Helvetica-Bold", 8.5, white)
    _texto(c, x_ref, y - 5.3 * mm, "Referencia", "Helvetica-Bold", 8.5, white)
    _texto(c, x_imp, y - 5.3 * mm, "Importe (S/)", "Helvetica-Bold", 8.5, white, derecha=True)
    y -= 8 * mm

    filas, subtotal, intereses = _filas_detalle(pago, item_pagado)
    for desc, ref, imp in filas:
        y_txt = y - 6 * mm
        fin_desc = _texto(c, x_desc, y_txt, desc, "Helvetica", 9.5, TEXTO, ancho=92 * mm)
        _texto(c, x_ref, y_txt, ref, "Helvetica", 9, GRIS, ancho=48 * mm)
        _texto(c, x_imp, y_txt, f"{imp:,.2f}", "Helvetica-Bold", 9.5, TEXTO, derecha=True)
        y = min(fin_desc, y_txt - 4 * mm) - 3 * mm
        c.setStrokeColor(GRIS_BORDE)
        c.line(MARGEN, y, ANCHO - MARGEN, y)

    # Totales
    y -= 7 * mm
    if intereses > 0:
        _texto(c, ANCHO - MARGEN - 52 * mm, y, "Tributo", "Helvetica", 9, GRIS)
        _texto(c, x_imp, y, f"{subtotal:,.2f}", "Helvetica", 9, TEXTO, derecha=True)
        y -= 5 * mm
        _texto(c, ANCHO - MARGEN - 52 * mm, y, "Intereses", "Helvetica", 9, GRIS)
        _texto(c, x_imp, y, f"{intereses:,.2f}", "Helvetica", 9, TEXTO, derecha=True)
        y -= 4 * mm
    tw, th = 78 * mm, 11 * mm
    c.setFillColor(AZUL_CLARO)
    c.roundRect(ANCHO - MARGEN - tw, y - th, tw, th, 2 * mm, fill=1, stroke=0)
    _texto(c, ANCHO - MARGEN - tw + 4 * mm, y - 7.2 * mm, "TOTAL PAGADO", "Helvetica-Bold", 9.5, AZUL)
    _texto(c, x_imp, y - 7.4 * mm, f"S/ {Decimal(pago.monto):,.2f}", "Helvetica-Bold", 13, AZUL, derecha=True)
    y -= th + 6 * mm
    _texto(c, MARGEN, y, f"SON: {importe_en_letras(pago.monto)}", "Helvetica-Oblique", 8.5, TEXTO, ancho=ANCHO - 2 * MARGEN)
    y -= 12 * mm

    # --- Datos de la transacción ---
    _texto(c, MARGEN, y, "DATOS DE LA TRANSACCIÓN", "Helvetica-Bold", 9, AZUL)
    y -= 3 * mm
    caja_h = 24 * mm
    c.setStrokeColor(GRIS_BORDE)
    c.setFillColor(white)
    c.roundRect(MARGEN, y - caja_h, ANCHO - 2 * MARGEN, caja_h, 2 * mm, fill=0, stroke=1)
    tercio = (ANCHO - 2 * MARGEN) / 3
    metodo = pago.metodo.value.capitalize()
    _etiqueta_valor(c, MARGEN + 4 * mm, y - 6 * mm, "Medio de pago", metodo, tercio - 6 * mm)
    _etiqueta_valor(c, MARGEN + tercio, y - 6 * mm, "Detalle", pago.detalle_metodo or "—", tercio - 6 * mm)
    _etiqueta_valor(c, MARGEN + 2 * tercio, y - 6 * mm, "Cód. autorización", pago.codigo_autorizacion or "—", tercio - 6 * mm)
    _etiqueta_valor(c, MARGEN + 4 * mm, y - 16 * mm, "Nro. de operación", pago.transaccion_id or "—", 2 * tercio - 6 * mm)
    _etiqueta_valor(c, MARGEN + 2 * tercio, y - 16 * mm, "Estado", "COMPLETADO", tercio - 6 * mm)
    y -= caja_h + 10 * mm

    # --- QR de verificación ---
    qr_t = 34 * mm
    c.drawImage(_qr(verificacion.url_verificacion(pago)), MARGEN, y - qr_t, qr_t, qr_t, mask="auto")
    xt = MARGEN + qr_t + 6 * mm
    _texto(c, xt, y - 5 * mm, "Verifique este comprobante", "Helvetica-Bold", 10, AZUL)
    _texto(c, xt, y - 11 * mm,
           "Escanee el código QR con su celular para comprobar en línea que esta boleta es auténtica "
           "y que el pago fue registrado en el sistema municipal.",
           "Helvetica", 8.5, TEXTO, ancho=ANCHO - xt - MARGEN)
    _texto(c, xt, y - 26 * mm, f"{config.PUBLIC_BASE_URL}/verificar/{pago.numero_comprobante}", "Helvetica", 7, GRIS,
           ancho=ANCHO - xt - MARGEN)

    # --- Pie de página ---
    c.setStrokeColor(GRIS_BORDE)
    c.line(MARGEN, 22 * mm, ANCHO - MARGEN, 22 * mm)
    if config.MODO_DEMO:
        c.setFillColor(HexColor("#FEF3C7"))
        c.roundRect(MARGEN, 12 * mm, ANCHO - 2 * MARGEN, 7 * mm, 1.5 * mm, fill=1, stroke=0)
        _texto(c, ANCHO / 2, 14.6 * mm,
               "COMPROBANTE DE DEMOSTRACIÓN: el pago es simulado y este documento no tiene valor legal ni tributario.",
               "Helvetica-Bold", 7.5, HexColor("#92400E"), centro=True)
    _texto(c, ANCHO / 2, 7 * mm,
           f"{config.MUNI_NOMBRE}  ·  Conserve esta boleta para cualquier reclamo  ·  "
           f"Emitido el {datetime.now(ZoneInfo(config.APP_TIMEZONE)):%d/%m/%Y %H:%M}",
           "Helvetica", 7, GRIS, centro=True)

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer
