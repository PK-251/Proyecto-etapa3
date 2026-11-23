import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from conftest import PDF, ROOT

API = "/api/v1"


TARJETA_OK = {"numero": "4111 1111 1111 1111", "vencimiento": "12/35", "cvv": "123", "titular": "JUAN PRUEBA"}


def pago(monto, metodo="YAPE", **extra):
    """Cuerpo de pago válido según el medio elegido."""
    cuerpo = {"monto": monto, "metodo": metodo}
    if metodo == "TARJETA":
        cuerpo["tarjeta"] = TARJETA_OK
    else:
        cuerpo.update(celular="987654321", codigo_aprobacion="123456")
    cuerpo.update(extra)
    return cuerpo


def archivos(*nombres, contenido=PDF, tipo="application/pdf"):
    return [("files", (n, contenido, tipo)) for n in nombres]


# ---------- Autenticación ----------
@pytest.mark.parametrize(
    "metodo,ruta",
    [
        ("get", "/tramites/usuario/12345678"),
        ("get", "/tramites/expediente/2026-00001-LOB"),
        ("post", "/tramites/"),
        ("post", "/tramites/1/upload-documentos"),
        ("get", "/tramites/1/documentos/" + "a" * 32 + ".pdf"),
        ("post", "/deudas/consultar"),
        ("post", "/deudas/1/fraccionar"),
        ("get", "/ciudadanos/validar/12345678"),
        ("post", "/pagos/deuda/1"),
        ("get", "/admin/stats"),
        ("get", "/ai/metricas"),
        ("post", "/ai/chat"),
    ],
)
def test_endpoints_exigen_token(client, metodo, ruta):
    assert getattr(client, metodo)(API + ruta).status_code == 401


def test_login_incorrecto_y_bloqueo_por_intentos(client):
    for _ in range(5):
        r = client.post(f"{API}/auth/login", data={"username": "00000001", "password": "mala"})
        assert r.status_code == 401
    r = client.post(f"{API}/auth/login", data={"username": "00000001", "password": "mala"})
    assert r.status_code == 429


def test_ciudadano_no_accede_a_rutas_admin(client, h_ciudadano):
    assert client.get(f"{API}/admin/stats", headers=h_ciudadano).status_code == 403
    assert client.get(f"{API}/tramites/admin/all", headers=h_ciudadano).status_code == 403


def test_no_hay_credenciales_ni_secretos_por_defecto():
    """Sin SECRET_KEY la app se niega a arrancar."""
    r = subprocess.run(
        [sys.executable, "-I", "-c", "import sys; sys.path.insert(0, '.'); import config"],
        cwd=ROOT, capture_output=True, text=True, env={"PATH": "/usr/bin:/bin", "SECRET_KEY": ""},
    )
    assert r.returncode != 0 and "SECRET_KEY" in r.stderr


# ---------- Validación ----------
def test_error_de_validacion_es_422_con_mensaje(client, h_ciudadano):
    r = client.post(f"{API}/deudas/consultar", headers=h_ciudadano, json={"dni": "abc"})
    assert r.status_code == 422
    assert "8 dígitos" in r.json()["detail"]


def test_password_corta_rechazada(client, h_admin):
    r = client.post(
        f"{API}/admin/ciudadanos", headers=h_admin, json={"dni": "22222222", "nombre": "PRUEBA", "password": "123"}
    )
    assert r.status_code == 422


# ---------- Trámites ----------
def test_crear_tramite_costo_y_expediente_los_pone_el_servidor(client, h_ciudadano):
    r = client.post(
        f"{API}/tramites/", headers=h_ciudadano,
        json={"tipo": "PARTIDA_NACIMIENTO", "costo_total": 0.01, "expediente": "HACK-1", "detalles": {"motivo": "tesis"}},
    )
    assert r.status_code == 201
    t = r.json()
    assert t["costo_total"] == "15.00" and t["expediente"].endswith("-PNA") and t["expediente"] != "HACK-1"
    assert t["detalles"] == {"motivo": "tesis"}  # antes: 500 al enviar detalles
    assert t["fecha_creacion"].endswith("Z")


def test_no_se_pueden_crear_tramites_a_nombre_de_otro(client, h_otro):
    r = client.post(f"{API}/tramites/", headers=h_otro, json={"tipo": "LICENCIA_OBRA", "dni_ciudadano": "12345678"})
    assert r.status_code == 403


def test_tramites_ajenos_no_visibles(client, h_ciudadano, h_otro, tramite):
    assert client.get(f"{API}/tramites/expediente/{tramite['expediente']}", headers=h_otro).status_code == 404
    assert client.get(f"{API}/tramites/usuario/12345678", headers=h_otro).status_code == 403
    assert client.post(f"{API}/pagos/tramite/{tramite['id']}", headers=h_otro,
                       json=pago("120.50", "YAPE")).status_code == 404
    mios = client.get(f"{API}/tramites/usuario/12345678", headers=h_ciudadano).json()
    assert tramite["expediente"] in [t["expediente"] for t in mios]


def test_subida_de_varios_documentos_se_guarda_todo(client, h_ciudadano, h_otro, tramite):
    tid = tramite["id"]
    for i in (1, 2, 3):  # antes solo se guardaba el primero
        r = client.post(f"{API}/tramites/{tid}/upload-documentos", headers=h_ciudadano, files=archivos(f"doc{i}.pdf"))
        assert r.status_code == 200, r.text
    docs = r.json()["documentos"]
    assert [d["nombre"] for d in docs] == ["doc1.pdf", "doc2.pdf", "doc3.pdf"]

    # Descarga: titular sí, otro ciudadano no, anónimo no, y no hay acceso público por /uploads ni /static
    url = docs[0]["url"]
    d = client.get(url, headers=h_ciudadano)
    assert d.status_code == 200 and d.content == PDF
    assert client.get(url, headers=h_otro).status_code == 404
    assert client.get(url).status_code == 401
    archivo = url.rsplit("/", 1)[1]
    assert client.get(f"/uploads/{archivo}").status_code == 404
    assert client.get(f"/static/uploads/{archivo}").status_code == 404


def test_subida_rechaza_archivos_peligrosos(client, h_ciudadano, tramite):
    url = f"{API}/tramites/{tramite['id']}/upload-documentos"
    assert client.post(url, headers=h_ciudadano, files=archivos("virus.exe")).status_code == 400
    # extensión .pdf pero contenido que no es PDF
    assert client.post(url, headers=h_ciudadano,
                       files=archivos("falso.pdf", contenido=b"<script>alert(1)</script>")).status_code == 400
    # demasiado grande (límite de pruebas: 1 MB)
    grande = PDF + b"0" * (1024 * 1024 + 10)
    assert client.post(url, headers=h_ciudadano, files=archivos("grande.pdf", contenido=grande)).status_code == 413
    # nombre con ../ se sanea y no rompe nada
    r = client.post(url, headers=h_ciudadano, files=archivos("../../etc/passwd.pdf"))
    assert r.status_code == 200 and r.json()["documentos"][-1]["nombre"] == "passwd.pdf"
    # todo o nada: si uno falla, ninguno se guarda
    antes = len(client.get(f"{API}/tramites/expediente/{tramite['expediente']}", headers=h_ciudadano).json()["documentos"])
    mixto = [("files", ("ok.pdf", PDF, "application/pdf")), ("files", ("mal.exe", b"MZ", "application/octet-stream"))]
    assert client.post(url, headers=h_ciudadano, files=mixto).status_code == 400
    despues = len(client.get(f"{API}/tramites/expediente/{tramite['expediente']}", headers=h_ciudadano).json()["documentos"])
    assert antes == despues


# ---------- Pago de trámites ----------
def test_pago_de_tramite_y_no_se_paga_dos_veces(client, h_ciudadano, tramite):
    url = f"{API}/pagos/tramite/{tramite['id']}"
    assert client.post(url, headers=h_ciudadano, json=pago("1.00", "YAPE")).status_code == 400
    r = client.post(url, headers=h_ciudadano, json=pago("120.50", "YAPE"))
    assert r.status_code == 200, r.text
    pago_id = r.json()["id"]
    assert client.post(url, headers=h_ciudadano, json=pago("120.50", "YAPE")).status_code == 409

    ya_pagado = client.get(f"{API}/tramites/expediente/{tramite['expediente']}", headers=h_ciudadano).json()
    assert ya_pagado["estado"] == "EN_EVALUACION"
    # ya no se pueden adjuntar documentos
    assert client.post(f"{API}/tramites/{tramite['id']}/upload-documentos", headers=h_ciudadano,
                       files=archivos("tarde.pdf")).status_code == 409

    pdf = client.get(f"{API}/pagos/comprobante/{pago_id}", headers=h_ciudadano)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def test_tramite_aprobado_no_vuelve_a_evaluacion_al_pagar(client, h_ciudadano, h_admin, tramite):
    url = f"{API}/pagos/tramite/{tramite['id']}"
    assert client.post(url, headers=h_ciudadano, json=pago("120.50", "PLIN")).status_code == 200
    r = client.put(f"{API}/tramites/{tramite['id']}/estado", headers=h_admin, json={"estado": "APROBADO"})
    assert r.status_code == 200
    assert client.post(url, headers=h_ciudadano, json=pago("120.50", "PLIN")).status_code == 409
    assert client.get(f"{API}/tramites/{tramite['id']}", headers=h_admin).json()["estado"] == "APROBADO"


# ---------- Administración de trámites ----------
def test_observaciones_no_rompen_el_panel_admin(client, h_ciudadano, h_admin, tramite):
    tid = tramite["id"]
    # sin pagar no se puede evaluar
    assert client.put(f"{API}/tramites/{tid}/estado", headers=h_admin, json={"estado": "APROBADO"}).status_code == 409
    client.post(f"{API}/pagos/tramite/{tid}", headers=h_ciudadano, json=pago("120.50", "TARJETA"))

    # estado inválido -> 422; observar sin motivo -> 400; el ciudadano no puede -> 403
    assert client.put(f"{API}/tramites/{tid}/estado", headers=h_admin, json={"estado": "EN_REVISION"}).status_code == 422
    assert client.put(f"{API}/tramites/{tid}/estado", headers=h_admin, json={"estado": "OBSERVADO"}).status_code == 400
    assert client.put(f"{API}/tramites/{tid}/estado", headers=h_ciudadano, json={"estado": "APROBADO"}).status_code == 403

    r = client.put(f"{API}/tramites/{tid}/estado", headers=h_admin,
                   json={"estado": "OBSERVADO", "observaciones": "Falta el plano firmado"})
    assert r.status_code == 200, r.text  # antes: 500 y dejaba la BD corrupta
    assert r.json()["observaciones"][0]["texto"] == "Falta el plano firmado"

    todos = client.get(f"{API}/tramites/admin/all", headers=h_admin)  # antes: 500 para siempre
    assert todos.status_code == 200 and any(t["id"] == tid for t in todos.json())
    # el ciudadano ve la observación en su trámite
    mio = client.get(f"{API}/tramites/expediente/{tramite['expediente']}", headers=h_ciudadano).json()
    assert mio["estado"] == "OBSERVADO" and len(mio["observaciones"]) == 1


def test_estadisticas(client, h_admin):
    r = client.get(f"{API}/admin/stats", headers=h_admin)
    assert r.status_code == 200
    s = r.json()
    assert s["tramitesHoy"] >= 1 and s["tramitesPendientes"] >= 1 and s["recaudacionHoy"] >= 120.5


def test_reset_password_y_exportacion(client, h_admin):
    r = client.post(f"{API}/admin/usuarios/11111111/reset-password", headers=h_admin)
    assert r.status_code == 200
    nueva = r.json()["password"]
    assert client.post(f"{API}/auth/login", data={"username": "11111111", "password": nueva}).status_code == 200
    sql = client.get(f"{API}/admin/export/ciudadanos.sql", headers=h_admin)
    assert sql.status_code == 200 and "INSERT INTO ciudadano" in sql.text


# ---------- Deudas ----------
def _deudas(client, headers):
    r = client.post(f"{API}/deudas/consultar", headers=headers, json={})
    assert r.status_code == 200, r.text
    return r.json()


def _por_tipo(data, tipo):
    return next(d for d in data["deudasMunicipales"] if d["tipo"] == tipo)


def test_consultar_calcula_intereses_de_la_vencida(client, h_ciudadano, h_otro):
    data = _deudas(client, h_ciudadano)
    predial = _por_tipo(data, "PREDIAL")
    assert predial["esta_vencida"] and Decimal(predial["intereses_moratorios"]) > 0
    assert Decimal(predial["monto_total"]) == Decimal(predial["monto_base"]) + Decimal(predial["intereses_moratorios"])
    assert not _por_tipo(data, "ARBITRIOS")["esta_vencida"]
    assert data["deudasTributarias"][0]["fuente"] == "SUNAT"
    # no se puede consultar el DNI de otra persona
    assert client.post(f"{API}/deudas/consultar", headers=h_otro, json={"dni": "12345678"}).status_code == 403


def test_pagar_deuda_vencida_con_el_monto_mostrado(client, h_ciudadano):
    data = _deudas(client, h_ciudadano)
    predial = _por_tipo(data, "PREDIAL")
    url = f"{API}/pagos/deuda/{predial['id']}"

    # antes: 400 porque se comparaba contra el monto viejo guardado en la BD
    r = client.post(url, headers=h_ciudadano, json=pago(predial["monto_total"], "YAPE"))
    assert r.status_code == 200, r.text
    assert Decimal(r.json()["monto"]) == Decimal(predial["monto_total"])
    # no se paga dos veces
    assert client.post(url, headers=h_ciudadano, json=pago(predial["monto_total"], "YAPE")).status_code == 409

    # y una deuda pagada ya no genera intereses ni suma al total general
    despues = _deudas(client, h_ciudadano)
    pagada = _por_tipo(despues, "PREDIAL")
    assert pagada["estado"] == "PAGADO" and pagada["monto_total"] == predial["monto_total"]
    pendientes = sum(Decimal(d["monto_total"]) for d in despues["deudasMunicipales"] if d["estado"] in ("PENDIENTE", "VENCIDO"))
    sunat = sum(Decimal(d["monto"]) for d in despues["deudasTributarias"])
    assert Decimal(despues["totalGeneral"]) == pendientes + sunat


def test_pagar_deuda_con_monto_incorrecto_o_ajena(client, h_ciudadano, h_otro):
    arbitrios = _por_tipo(_deudas(client, h_ciudadano), "ARBITRIOS")
    url = f"{API}/pagos/deuda/{arbitrios['id']}"
    assert client.post(url, headers=h_ciudadano, json=pago("1.00", "YAPE")).status_code == 400
    assert client.post(url, headers=h_otro, json=pago(arbitrios["monto_total"], "YAPE")).status_code == 404


def test_fraccionar_deuda(client, h_ciudadano, h_otro):
    limpieza = _por_tipo(_deudas(client, h_ciudadano), "LIMPIEZA_PUBLICA")
    url = f"{API}/deudas/{limpieza['id']}/fraccionar"
    assert client.post(url, headers=h_ciudadano, json={"numero_cuotas": 2}).status_code == 422
    assert client.post(url, headers=h_ciudadano, json={"numero_cuotas": 13}).status_code == 422
    assert client.post(url, headers=h_otro, json={"numero_cuotas": 3}).status_code == 404

    r = client.post(url, headers=h_ciudadano, json={"numero_cuotas": 3})  # antes: siempre 400
    assert r.status_code == 201, r.text
    cuotas = r.json()["cuotas"]
    assert len(cuotas) == 3
    assert sum(Decimal(c["monto"]) for c in cuotas) == Decimal(limpieza["monto_total"])  # sin perder centavos
    assert _por_tipo(_deudas(client, h_ciudadano), "LIMPIEZA_PUBLICA")["estado"] == "FRACCIONADO"
    assert client.post(url, headers=h_ciudadano, json={"numero_cuotas": 3}).status_code == 409
    assert client.post(f"{API}/pagos/deuda/{limpieza['id']}", headers=h_ciudadano,
                       json=pago(limpieza["monto_total"], "YAPE")).status_code == 409


# ---------- Varios ----------
def test_ciudadanos_validar_solo_admin(client, h_ciudadano, h_admin):
    assert client.get(f"{API}/ciudadanos/validar/12345678", headers=h_ciudadano).status_code == 403
    assert client.get(f"{API}/ciudadanos/validar/12345678", headers=h_admin).status_code == 200
    assert client.get(f"{API}/ciudadanos/validar/12", headers=h_admin).status_code == 400


def test_chat_ia_sin_clave_responde_sin_romper(client, h_ciudadano):
    r = client.post(f"{API}/ai/chat", headers=h_ciudadano, json={"prompt": "hola"})
    assert r.status_code == 200 and "no está configurado" in r.json()["response"]
    assert client.post(f"{API}/ai/chat", headers=h_ciudadano, json={"prompt": "x" * 2000}).status_code == 422
    assert client.get(f"{API}/ai/health").json() == {"status": "sin_configurar"}


def test_metricas_ia_admin(client, h_admin):
    m = client.get(f"{API}/ai/metricas", headers=h_admin).json()
    assert m["totalConsultas"] >= 1 and m["satisfaccion"] is None


def test_frontend_y_favicon(client):
    assert "Municipio Conecta" in client.get("/").text
    assert client.get("/favicon.ico").status_code == 200
    assert client.get("/health").json() == {"status": "ok"}


# ---------- Pagos realistas ----------
def _nuevo_tramite(client, headers, tipo="PARTIDA_NACIMIENTO"):
    return client.post(f"{API}/tramites/", headers=headers, json={"tipo": tipo}).json()


def _usuario_nuevo(client, h_admin, dni):
    client.post(f"{API}/admin/ciudadanos", headers=h_admin,
                json={"dni": dni, "nombre": f"USUARIO {dni}", "password": "ClaveSegura123"})
    r = client.post(f"{API}/auth/login", data={"username": dni, "password": "ClaveSegura123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_tarjeta_rechazada_queda_registrada_y_se_puede_reintentar(client, h_ciudadano):
    t = _nuevo_tramite(client, h_ciudadano)
    url = f"{API}/pagos/tramite/{t['id']}"
    mala = pago("15.00", "TARJETA", tarjeta={**TARJETA_OK, "numero": "4000 0000 0000 0002"})
    r = client.post(url, headers=h_ciudadano, json=mala)
    assert r.status_code == 402 and "Fondos insuficientes" in r.json()["detail"]

    # el trámite sigue sin pagar, el intento quedó en el historial y no tiene comprobante
    assert client.get(f"{API}/tramites/expediente/{t['expediente']}", headers=h_ciudadano).json()["estado"] == "PENDIENTE_PAGO"
    hist = client.get(f"{API}/pagos/mis-pagos", headers=h_ciudadano).json()
    fallido = next(p for p in hist if p["id"] == r.json()["pago_id"])
    assert fallido["estado"] == "FALLIDO" and fallido["numero_comprobante"] is None
    assert "Fondos" in fallido["motivo_rechazo"]
    assert client.get(f"{API}/pagos/comprobante/{fallido['id']}", headers=h_ciudadano).status_code == 409

    ok = client.post(url, headers=h_ciudadano, json=pago("15.00", "TARJETA"))  # reintento con otra tarjeta
    assert ok.status_code == 200, ok.text
    d = ok.json()
    assert d["numero_comprobante"].startswith("B001-") and d["detalle_metodo"] == "VISA ****1111"
    assert d["transaccion_id"].startswith("TX") and len(d["codigo_autorizacion"]) == 6


def test_datos_de_pago_invalidos_dan_422_sin_filtrar_la_tarjeta(client, h_ciudadano):
    t = _nuevo_tramite(client, h_ciudadano)
    url = f"{API}/pagos/tramite/{t['id']}"
    r = client.post(url, headers=h_ciudadano, json=pago("15.00", "TARJETA", tarjeta={**TARJETA_OK, "numero": "4111 1111 1111 1112"}))
    assert r.status_code == 422 and "1112" not in r.text  # Luhn inválido; el número no se devuelve
    assert client.post(url, headers=h_ciudadano, json=pago("15.00", "TARJETA", tarjeta={**TARJETA_OK, "vencimiento": "01/20"})).status_code == 422
    assert client.post(url, headers=h_ciudadano, json={"monto": "15.00", "metodo": "TARJETA"}).status_code == 422
    assert client.post(url, headers=h_ciudadano, json={"monto": "15.00", "metodo": "YAPE"}).status_code == 422
    assert client.post(url, headers=h_ciudadano, json=pago("15.00", "YAPE", celular="12345")).status_code == 422
    # Yape con código inválido: rechazado por la pasarela
    r = client.post(url, headers=h_ciudadano, json=pago("15.00", "YAPE", codigo_aprobacion="000000"))
    assert r.status_code == 402 and "Código" in r.json()["detail"]


def test_nunca_se_guarda_la_tarjeta_completa(client, h_ciudadano):
    from sqlalchemy import select
    from database import AsyncSessionLocal
    from models import Pago

    async def leer_pagos():
        async with AsyncSessionLocal() as db:
            return (await db.execute(select(Pago.__table__))).all()

    t = _nuevo_tramite(client, h_ciudadano)
    assert client.post(f"{API}/pagos/tramite/{t['id']}", headers=h_ciudadano, json=pago("15.00", "TARJETA")).status_code == 200
    filas = client.portal.call(leer_pagos)
    volcado = repr(filas)
    assert "4111111111111111" not in volcado and "4111 1111" not in volcado  # ni número completo
    assert "cvv" not in volcado.lower()
    assert "VISA ****1111" in volcado


def test_bloqueo_tras_muchos_pagos_rechazados(client, h_admin):
    h = _usuario_nuevo(client, h_admin, "44444444")
    t = _nuevo_tramite(client, h)
    url = f"{API}/pagos/tramite/{t['id']}"
    mala = pago("15.00", "TARJETA", tarjeta={**TARJETA_OK, "numero": "4000 0000 0000 0069"})
    assert [client.post(url, headers=h, json=mala).status_code for _ in range(5)] == [402] * 5
    assert client.post(url, headers=h, json=pago("15.00", "TARJETA")).status_code == 429


def test_mis_pagos_solo_muestra_los_propios(client, h_ciudadano, h_otro):
    mios = client.get(f"{API}/pagos/mis-pagos", headers=h_ciudadano).json()
    ajenos = client.get(f"{API}/pagos/mis-pagos", headers=h_otro).json()
    assert len(mios) >= 3
    assert not ({p["id"] for p in mios} & {p["id"] for p in ajenos})


def test_verificacion_publica_del_comprobante(client, h_ciudadano):
    from types import SimpleNamespace

    from services import verificacion

    t = _nuevo_tramite(client, h_ciudadano, "LICENCIA_OBRA")
    r = client.post(f"{API}/pagos/tramite/{t['id']}", headers=h_ciudadano, json=pago("250.00", "PLIN")).json()
    firma = verificacion.firmar(SimpleNamespace(id=r["id"], monto=r["monto"], transaccion_id=r["transaccion_id"]))
    num = r["numero_comprobante"]

    ok = client.get(f"{API}/verificar/{num}?h={firma}")  # sin token: es público
    assert ok.status_code == 200
    d = ok.json()
    assert d["valido"] and d["monto"] == "250.00" and "***" in d["contribuyente"] and "DELGADO" not in d["contribuyente"]
    assert "Comprobante válido" in client.get(f"/verificar/{num}?h={firma}").text
    # firma mala, sin firma o número inexistente: misma respuesta 404 (no se puede enumerar)
    assert client.get(f"{API}/verificar/{num}?h=0000000000000000").status_code == 404
    assert client.get(f"{API}/verificar/{num}").status_code == 404
    assert client.get(f"{API}/verificar/B001-99999999?h={firma}").status_code == 404
    assert client.get(f"/verificar/{num}?h=mala").status_code == 404


def test_recaudacion_admin_y_csv(client, h_admin, h_ciudadano):
    assert client.get(f"{API}/admin/pagos", headers=h_ciudadano).status_code == 403
    r = client.get(f"{API}/admin/pagos", headers=h_admin)
    assert r.status_code == 200
    d = r.json()
    assert d["cantidadCompletados"] >= 3 and d["cantidadRechazados"] >= 2
    assert d["totalRecaudado"] == pytest.approx(sum(float(p["monto"]) for p in d["pagos"] if p["estado"] == "COMPLETADO"))
    assert sum(d["porMetodo"].values()) == pytest.approx(d["totalRecaudado"])
    assert client.get(f"{API}/admin/pagos?metodo=PLIN&estado=COMPLETADO", headers=h_admin).json()["pagos"]
    assert client.get(f"{API}/admin/pagos?desde=2030-01-02&hasta=2030-01-01", headers=h_admin).status_code == 400
    assert client.get(f"{API}/admin/pagos?desde=2020-01-01&hasta=2020-01-02", headers=h_admin).json()["pagos"] == []

    csv_ = client.get(f"{API}/admin/pagos/export.csv", headers=h_admin)
    assert csv_.status_code == 200 and csv_.content.startswith(b"\xef\xbb\xbf")  # BOM para Excel
    assert "Comprobante,Fecha" in csv_.text and "B001-" in csv_.text
    assert client.get(f"{API}/admin/pagos/export.csv", headers=h_ciudadano).status_code == 403


def test_boleta_pdf_y_migracion_de_columnas(client, h_ciudadano):
    from sqlalchemy import inspect, text

    from database import _agregar_columnas_faltantes, engine

    hist = client.get(f"{API}/pagos/mis-pagos", headers=h_ciudadano).json()
    pid = next(p["id"] for p in hist if p["estado"] == "COMPLETADO")
    pdf = client.get(f"{API}/pagos/comprobante/{pid}", headers=h_ciudadano)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF") and "boleta_B001-" in pdf.headers["content-disposition"]

    # Una base creada con la versión anterior recibe las columnas nuevas sin perder datos
    def comprobar_migracion(conn):
        conn.execute(text("CREATE TEMP TABLE pago (id INTEGER PRIMARY KEY, monto NUMERIC NOT NULL, metodo VARCHAR(10) NOT NULL, "
                          "estado VARCHAR(12) NOT NULL, fecha_pago TIMESTAMP, comprobante_url VARCHAR(255), tramite_id INTEGER, deuda_id INTEGER) ON COMMIT DROP"))
        conn.execute(text("SET LOCAL search_path TO pg_temp"))
        conn.execute(text("INSERT INTO pago (id, monto, metodo, estado) VALUES (1, 10, 'YAPE', 'COMPLETADO')"))
        _agregar_columnas_faltantes(conn)
        cols = {c["name"] for c in inspect(conn).get_columns("pago")}
        assert {"concepto", "transaccion_id", "detalle_metodo", "motivo_rechazo", "codigo_autorizacion"} <= cols
        assert conn.execute(text("SELECT COUNT(*) FROM pago")).scalar() == 1

    async def ejecutar():
        async with engine.begin() as conn:
            await conn.run_sync(comprobar_migracion)

    client.portal.call(ejecutar)
