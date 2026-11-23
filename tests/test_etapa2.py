"""Etapa 2: quejas, reclamos, peticiones, catálogo de trámites y notificaciones."""
from datetime import date

import pytest

from catalogo import sumar_dias_habiles
from conftest import PDF
from test_api import TARJETA_OK, _usuario_nuevo, archivos, pago

API = "/api/v1"
QUEJA = {
    "clase": "QUEJA", "categoria": "ATENCION_FUNCIONARIO",
    "asunto": "Maltrato en ventanilla", "descripcion": "Fui atendido de mala manera en la ventanilla 3 el lunes por la mañana.",
}


def nueva(client, h, **extra):
    r = client.post(f"{API}/solicitudes/", headers=h, json={**QUEJA, **extra})
    assert r.status_code == 201, r.text
    return r.json()


# ---------- Quejas / reclamos / peticiones ----------
def test_registrar_queja_da_codigo_plazo_y_notifica(client, h_ciudadano):
    s = nueva(client, h_ciudadano)
    assert s["codigo"].startswith("QJ-") and s["estado"] == "RECIBIDA"
    assert s["dias_restantes"] >= 14 and not s["vencida"]
    assert s["historial"][0]["evento"] == "Registrada"
    notis = client.get(f"{API}/notificaciones/", headers=h_ciudadano).json()
    assert any(s["codigo"] in n["mensaje"] for n in notis["items"])


def test_codigos_distintos_por_clase_y_correlativos(client, h_ciudadano):
    a = nueva(client, h_ciudadano)
    b = nueva(client, h_ciudadano, clase="RECLAMO", categoria="ALUMBRADO")
    c = nueva(client, h_ciudadano, clase="PETICION", categoria="SOLICITUD_INFORMACION")
    assert b["codigo"].startswith("RC-") and c["codigo"].startswith("PT-")
    d = nueva(client, h_ciudadano)
    assert int(d["codigo"].split("-")[2]) == int(a["codigo"].split("-")[2]) + 1


def test_plazo_de_informacion_es_mas_corto_que_el_de_peticion(client, h_ciudadano):
    info = nueva(client, h_ciudadano, clase="PETICION", categoria="SOLICITUD_INFORMACION")
    otra = nueva(client, h_ciudadano, clase="PETICION", categoria="SUGERENCIA")
    assert info["fecha_limite"] < otra["fecha_limite"]


@pytest.mark.parametrize("cambio", [
    {"categoria": "ALUMBRADO"},              # categoría de otra clase
    {"asunto": "ab"},
    {"descripcion": "muy corto"},
    {"clase": "OTRA"},
])
def test_validaciones_al_registrar(client, h_ciudadano, cambio):
    r = client.post(f"{API}/solicitudes/", headers=h_ciudadano, json={**QUEJA, **cambio})
    assert r.status_code == 422


def test_requiere_login(client):
    assert client.post(f"{API}/solicitudes/", json=QUEJA).status_code == 401
    assert client.get(f"{API}/solicitudes/mias").status_code == 401
    assert client.get(f"{API}/notificaciones/").status_code == 401


def test_solo_el_titular_ve_su_solicitud(client, h_ciudadano, h_otro):
    s = nueva(client, h_ciudadano)
    assert client.get(f"{API}/solicitudes/{s['id']}", headers=h_otro).status_code == 404
    assert client.post(f"{API}/solicitudes/{s['id']}/comentarios", headers=h_otro, json={"texto": "hola"}).status_code == 404
    assert client.post(f"{API}/solicitudes/{s['id']}/adjuntos", headers=h_otro, files=archivos("a.pdf")).status_code == 404
    assert all(x["id"] != s["id"] for x in client.get(f"{API}/solicitudes/mias", headers=h_otro).json())
    assert client.get(f"{API}/solicitudes/{s['id']}", headers=h_ciudadano).status_code == 200


def test_ciudadano_no_puede_gestionar(client, h_ciudadano):
    s = nueva(client, h_ciudadano)
    r = client.put(f"{API}/solicitudes/{s['id']}/gestionar", headers=h_ciudadano, json={"estado": "ATENDIDA", "respuesta": "x" * 20})
    assert r.status_code == 403
    assert client.get(f"{API}/solicitudes/admin/all", headers=h_ciudadano).status_code == 403


def test_adjuntos_se_descargan_solo_por_titular_o_admin(client, h_ciudadano, h_otro, h_admin):
    s = nueva(client, h_ciudadano)
    r = client.post(f"{API}/solicitudes/{s['id']}/adjuntos", headers=h_ciudadano, files=archivos("foto.pdf"))
    assert r.status_code == 200
    url = r.json()["documentos"][0]["url"]
    assert client.get(url, headers=h_ciudadano).content == PDF
    assert client.get(url, headers=h_admin).status_code == 200
    assert client.get(url, headers=h_otro).status_code == 404
    assert client.get(url).status_code == 401
    mala = client.post(f"{API}/solicitudes/{s['id']}/adjuntos", headers=h_ciudadano, files=archivos("x.pdf", contenido=b"MZ no es pdf"))
    assert mala.status_code in (400, 415, 422)


def test_flujo_completo_atencion_y_respuesta(client, h_ciudadano, h_admin):
    s = nueva(client, h_ciudadano, clase="RECLAMO", categoria="COBRO_INDEBIDO")
    base = f"{API}/solicitudes/{s['id']}"
    # En atención con nota interna oculta para el ciudadano
    r = client.put(f"{base}/gestionar", headers=h_admin,
                   json={"estado": "EN_ATENCION", "respuesta": "Derivado a Rentas.", "nota_interna": "Revisar con el gerente"})
    assert r.status_code == 200
    assert any(e["evento"] == "Nota interna" for e in r.json()["historial"])
    vista = client.get(base, headers=h_ciudadano).json()
    assert vista["estado"] == "EN_ATENCION"
    assert all(e["evento"] != "Nota interna" for e in vista["historial"])
    assert "ciudadano_dni" not in vista
    visto_admin = client.get(base, headers=h_admin).json()
    assert visto_admin["ciudadano_dni"] == "12345678" and any(e["evento"] == "Nota interna" for e in visto_admin["historial"])
    # Cerrar exige respuesta oficial
    assert client.put(f"{base}/gestionar", headers=h_admin, json={"estado": "ATENDIDA"}).status_code == 400
    assert client.put(f"{base}/gestionar", headers=h_admin, json={"estado": "ATENDIDA", "respuesta": "corta"}).status_code == 400
    ok = client.put(f"{base}/gestionar", headers=h_admin, json={"estado": "ATENDIDA", "respuesta": "Se corrigió el cobro y se emitirá la nota de crédito."})
    assert ok.status_code == 200 and ok.json()["respondido_por"]
    final = client.get(base, headers=h_ciudadano).json()
    assert final["respuesta"].startswith("Se corrigió") and final["dias_restantes"] is None
    # Cerrada: no se reabre ni admite comentarios o adjuntos
    assert client.put(f"{base}/gestionar", headers=h_admin, json={"estado": "EN_ATENCION"}).status_code == 409
    assert client.post(f"{base}/comentarios", headers=h_ciudadano, json={"texto": "una duda más"}).status_code == 409
    assert client.post(f"{base}/adjuntos", headers=h_ciudadano, files=archivos("a.pdf")).status_code == 409
    # El ciudadano fue avisado
    notis = client.get(f"{API}/notificaciones/", headers=h_ciudadano).json()["items"]
    assert any("atendid" in n["titulo"] and s["codigo"] in n["titulo"] for n in notis)


def test_no_se_regresa_a_recibida(client, h_ciudadano, h_admin):
    s = nueva(client, h_ciudadano)
    r = client.put(f"{API}/solicitudes/{s['id']}/gestionar", headers=h_admin, json={"estado": "RECIBIDA"})
    assert r.status_code == 400


def test_comentario_del_ciudadano_avisa_al_personal(client, h_ciudadano, h_admin):
    s = nueva(client, h_ciudadano)
    r = client.post(f"{API}/solicitudes/{s['id']}/comentarios", headers=h_ciudadano, json={"texto": "Adjunto más detalles del caso."})
    assert r.status_code == 200 and r.json()["historial"][-1]["evento"] == "Comentario del ciudadano"
    admin_notis = client.get(f"{API}/notificaciones/", headers=h_admin).json()["items"]
    assert any(s["codigo"] in n["titulo"] for n in admin_notis)


def test_comentario_html_se_guarda_tal_cual_el_front_lo_escapa(client, h_ciudadano):
    s = nueva(client, h_ciudadano)
    r = client.post(f"{API}/solicitudes/{s['id']}/comentarios", headers=h_ciudadano, json={"texto": "<b>hola</b> gracias"})
    assert r.status_code == 200


def test_admin_filtra_busca_y_ve_resumen(client, h_ciudadano, h_admin):
    s = nueva(client, h_ciudadano, asunto="Basura acumulada en la esquina", clase="RECLAMO", categoria="LIMPIEZA_PUBLICA")
    lista = client.get(f"{API}/solicitudes/admin/all", headers=h_admin, params={"q": "Basura acumulada"}).json()
    assert [x["id"] for x in lista] == [s["id"]] and lista[0]["ciudadano_dni"] == "12345678"
    assert all(x["clase"] == "RECLAMO" for x in client.get(f"{API}/solicitudes/admin/all", headers=h_admin, params={"clase": "RECLAMO"}).json())
    res = client.get(f"{API}/solicitudes/admin/resumen", headers=h_admin).json()
    assert res["recibidas"] >= 1 and set(res) == {"recibidas", "en_atencion", "atendidas", "improcedentes", "vencidas"}


def test_solicitud_vencida_se_detecta(client, h_ciudadano, h_admin):
    from sqlalchemy import update
    from database import AsyncSessionLocal
    from models import Solicitud

    s = nueva(client, h_ciudadano)

    async def vencer():
        async with AsyncSessionLocal() as db:
            await db.execute(update(Solicitud).where(Solicitud.id == s["id"]).values(fecha_limite=date(2020, 1, 1)))
            await db.commit()

    client.portal.call(vencer)
    v = client.get(f"{API}/solicitudes/{s['id']}", headers=h_ciudadano).json()
    assert v["vencida"] and v["dias_restantes"] < 0
    assert s["id"] in [x["id"] for x in client.get(f"{API}/solicitudes/admin/all", headers=h_admin, params={"vencidas": True}).json()]


def test_dias_habiles_salta_fines_de_semana():
    assert sumar_dias_habiles(date(2026, 11, 13), 1) == date(2026, 11, 16)  # viernes -> lunes
    assert sumar_dias_habiles(date(2026, 11, 13), 5) == date(2026, 11, 20)


def test_categorias(client, h_ciudadano):
    r = client.get(f"{API}/solicitudes/categorias", headers=h_ciudadano).json()
    assert {c["clase"] for c in r} == {"QUEJA", "RECLAMO", "PETICION"}


# ---------- Catálogo de trámites ----------
def test_catalogo_lista_los_tramites_con_requisitos(client, h_ciudadano):
    cat = {c["tipo"]: c for c in client.get(f"{API}/tramites/catalogo", headers=h_ciudadano).json()}
    assert {"CONSTANCIA_NO_ADEUDO", "CERTIFICADO_DOMICILIO", "LICENCIA_EVENTO", "COPIA_CERTIFICADA", "LICENCIA_OBRA"} <= set(cat)
    assert cat["LICENCIA_EVENTO"]["costo"] == "85.00" and cat["LICENCIA_EVENTO"]["requisitos"]


def test_tramite_nuevo_valida_campos_obligatorios(client, h_otro):
    r = client.post(f"{API}/tramites/", headers=h_otro, json={"tipo": "LICENCIA_EVENTO", "detalles": {"nombre_evento": "Feria"}})
    assert r.status_code == 422 and "Fecha del evento" in r.json()["detail"]
    r = client.post(f"{API}/tramites/", headers=h_otro, json={"tipo": "COPIA_CERTIFICADA", "detalles": {"documento": "Resolución 12-2020", "num_copias": 99}})
    assert r.status_code == 422
    r = client.post(f"{API}/tramites/", headers=h_otro, json={"tipo": "CERTIFICADO_DOMICILIO", "detalles": {"direccion": "Jr. Lima 1", "tiempo_residencia": "inventado"}})
    assert r.status_code == 422


def test_tramite_nuevo_se_crea_con_costo_oficial(client, h_otro):
    r = client.post(f"{API}/tramites/", headers=h_otro, json={
        "tipo": "LICENCIA_EVENTO",
        "detalles": {"nombre_evento": "Feria", "fecha_evento": "2027-01-20", "lugar": "Plaza", "aforo": "300"},
    })
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["costo_total"] == "85.00" and t["expediente"].endswith("-LEV") and t["detalles"]["aforo"] == 300


def test_constancia_no_adeudo_exige_no_tener_deudas(client, h_ciudadano, h_otro):
    # El ciudadano demo tiene deudas pendientes
    r = client.post(f"{API}/tramites/", headers=h_ciudadano, json={"tipo": "CONSTANCIA_NO_ADEUDO", "detalles": {"motivo": "Trámite bancario"}})
    assert r.status_code == 409 and "deudas pendientes" in r.json()["detail"]
    # Quien no debe nada sí puede
    r = client.post(f"{API}/tramites/", headers=h_otro, json={"tipo": "CONSTANCIA_NO_ADEUDO", "detalles": {"motivo": "Trámite bancario"}})
    assert r.status_code == 201 and r.json()["costo_total"] == "8.50"


# ---------- Seguimiento y notificaciones ----------
def test_seguimiento_del_tramite_muestra_registro_pago_y_estado(client, h_admin, h_otro):
    t = client.post(f"{API}/tramites/", headers=h_otro, json={"tipo": "PARTIDA_NACIMIENTO"}).json()
    assert client.post(f"{API}/pagos/tramite/{t['id']}", headers=h_otro, json=pago("15.00", "TARJETA")).status_code == 200
    assert client.put(f"{API}/tramites/{t['id']}/estado", headers=h_admin,
                      json={"estado": "OBSERVADO", "observaciones": "Falta copia legible del DNI"}).status_code == 200
    ev = client.get(f"{API}/tramites/{t['id']}/seguimiento", headers=h_otro).json()
    assert [e["tipo"] for e in ev] == ["creacion", "pago", "observacion"]
    assert "Falta copia" in ev[2]["detalle"]
    notis = client.get(f"{API}/notificaciones/", headers=h_otro).json()["items"]
    textos = " ".join(n["titulo"] + n["mensaje"] for n in notis)
    assert "Pago recibido" in textos and "Falta copia" in textos


def test_seguimiento_ajeno_404(client, h_ciudadano, h_otro, tramite):
    assert client.get(f"{API}/tramites/{tramite['id']}/seguimiento", headers=h_otro).status_code == 404


def test_notificaciones_marcar_leidas_y_aislamiento(client, h_ciudadano, h_otro):
    s = nueva(client, h_ciudadano)
    datos = client.get(f"{API}/notificaciones/", headers=h_ciudadano).json()
    assert datos["no_leidas"] >= 1
    nid = datos["items"][0]["id"]
    # otro usuario no puede marcarla
    assert client.post(f"{API}/notificaciones/{nid}/leida", headers=h_otro).status_code == 404
    r = client.post(f"{API}/notificaciones/{nid}/leida", headers=h_ciudadano)
    assert r.status_code == 200 and r.json()["no_leidas"] == datos["no_leidas"] - 1
    assert client.post(f"{API}/notificaciones/leer-todas", headers=h_ciudadano).json()["no_leidas"] == 0
    assert client.get(f"{API}/notificaciones/contador", headers=h_ciudadano).json()["no_leidas"] == 0
    assert all(s["codigo"] not in n["mensaje"] for n in client.get(f"{API}/notificaciones/", headers=h_otro).json()["items"])


def test_limite_de_registros_por_hora(client, h_admin, monkeypatch):
    from controllers import solicitud_controller as sc
    monkeypatch.setattr(sc._limite_registro, "max_events", 2)
    h = _usuario_nuevo(client, h_admin, "55555555")
    assert client.post(f"{API}/solicitudes/", headers=h, json=QUEJA).status_code == 201
    assert client.post(f"{API}/solicitudes/", headers=h, json=QUEJA).status_code == 201
    assert client.post(f"{API}/solicitudes/", headers=h, json=QUEJA).status_code == 429
