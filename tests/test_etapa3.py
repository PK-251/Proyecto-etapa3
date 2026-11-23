"""Etapa 3: feriados, roles por área, derivación, registro, recuperación de clave, consulta pública,
reportes, auditoría y avisos por correo/WhatsApp."""
from datetime import date

import pytest

import config
from catalogo import sumar_dias_habiles
from feriados import es_dia_habil, es_feriado, feriados_del_anio
from test_api import _usuario_nuevo
from test_etapa2 import QUEJA, nueva

API = "/api/v1"


def _login(client, dni, clave):
    r = client.post(f"{API}/auth/login", data={"username": dni, "password": clave})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _funcionario(client, h_admin, dni, area):
    r = client.post(f"{API}/admin/ciudadanos", headers=h_admin,
                    json={"dni": dni, "nombre": f"FUNCIONARIO {area}", "password": "ClaveSegura123", "role": "funcionario", "area": area})
    assert r.status_code == 201, r.text
    return _login(client, dni, "ClaveSegura123")


# ---------- Feriados ----------
def test_feriados_nacionales_y_semana_santa():
    assert es_feriado(date(2027, 1, 1)) and es_feriado(date(2026, 7, 28)) and es_feriado(date(2026, 12, 25))
    assert {date(2027, 3, 25), date(2027, 3, 26)} <= feriados_del_anio(2027)      # Pascua 2027 = 28/03
    assert {date(2026, 4, 2), date(2026, 4, 3)} <= feriados_del_anio(2026)        # Pascua 2026 = 05/04
    assert not es_dia_habil(date(2026, 11, 14)) and es_dia_habil(date(2026, 11, 16))


def test_plazos_saltan_feriados_y_fines_de_semana():
    assert sumar_dias_habiles(date(2027, 3, 24), 1) == date(2027, 3, 29)          # miércoles -> lunes (Jue/Vie santos)
    assert sumar_dias_habiles(date(2026, 7, 27), 1) == date(2026, 7, 30)          # lunes -> jueves (28 y 29 feriados)


def test_feriados_extra_desde_el_entorno(monkeypatch):
    monkeypatch.setattr(config, "FERIADOS_EXTRA", ["2026-11-16", "no-es-fecha"])
    assert es_feriado(date(2026, 11, 16))
    assert sumar_dias_habiles(date(2026, 11, 13), 1) == date(2026, 11, 17)


# ---------- Roles y áreas ----------
def test_funcionario_requiere_area_valida(client, h_admin):
    for extra in ({}, {"area": "NO_EXISTE"}):
        r = client.post(f"{API}/admin/ciudadanos", headers=h_admin,
                        json={"dni": "30000001", "nombre": "SIN AREA", "password": "ClaveSegura123", "role": "funcionario", **extra})
        assert r.status_code == 422


def test_funcionario_solo_ve_y_gestiona_su_area(client, h_ciudadano, h_admin, h_staff):
    alumbrado = nueva(client, h_ciudadano, clase="RECLAMO", categoria="ALUMBRADO")       # SERVICIOS_PUBLICOS
    cobro = nueva(client, h_ciudadano, clase="RECLAMO", categoria="COBRO_INDEBIDO")      # RENTAS
    assert alumbrado["area"] == "SERVICIOS_PUBLICOS" and cobro["area"] == "RENTAS"
    ids = [x["id"] for x in client.get(f"{API}/solicitudes/admin/all", headers=h_staff).json()]
    assert alumbrado["id"] in ids and cobro["id"] not in ids
    assert client.get(f"{API}/solicitudes/{cobro['id']}", headers=h_staff).status_code == 404
    r = client.put(f"{API}/solicitudes/{cobro['id']}/gestionar", headers=h_staff, json={"estado": "EN_ATENCION"})
    assert r.status_code == 404
    ok = client.put(f"{API}/solicitudes/{alumbrado['id']}/gestionar", headers=h_staff, json={"estado": "EN_ATENCION", "respuesta": "Cuadrilla programada."})
    assert ok.status_code == 200
    res = client.get(f"{API}/solicitudes/admin/resumen", headers=h_staff).json()
    assert res["recibidas"] + res["en_atencion"] >= 1
    # el administrador ve ambas
    todos = [x["id"] for x in client.get(f"{API}/solicitudes/admin/all", headers=h_admin).json()]
    assert {alumbrado["id"], cobro["id"]} <= set(todos)


def test_funcionario_no_accede_a_funciones_de_admin(client, h_staff):
    for url in ("/admin/stats", "/admin/reportes", "/admin/auditoria", "/admin/ciudadanos", "/admin/pagos"):
        assert client.get(f"{API}{url}", headers=h_staff).status_code == 403, url


def test_derivar_cambia_de_area_y_oculta_el_motivo(client, h_ciudadano, h_staff, h_admin):
    rentas = _funcionario(client, h_admin, "30000002", "RENTAS")
    s = nueva(client, h_ciudadano, clase="RECLAMO", categoria="ALUMBRADO")
    base = f"{API}/solicitudes/{s['id']}"
    assert client.put(f"{base}/derivar", headers=h_staff, json={"area": "NO_EXISTE", "motivo": "porque sí"}).status_code == 400
    assert client.put(f"{base}/derivar", headers=h_staff, json={"area": "SERVICIOS_PUBLICOS", "motivo": "misma área"}).status_code == 400
    assert client.put(f"{base}/derivar", headers=h_staff, json={"area": "RENTAS", "motivo": "x"}).status_code == 422
    assert client.put(f"{base}/derivar", headers=h_ciudadano, json={"area": "RENTAS", "motivo": "intento ciudadano"}).status_code == 403
    r = client.put(f"{base}/derivar", headers=h_staff, json={"area": "RENTAS", "motivo": "Corresponde a Rentas por el cobro"})
    assert r.status_code == 200 and r.json()["area"] == "RENTAS"
    # la funcionaria original pierde acceso; la de Rentas lo gana
    assert client.get(base, headers=h_staff).status_code == 404
    assert client.get(base, headers=rentas).status_code == 200
    # el ciudadano ve la derivación pero no el motivo interno
    eventos = client.get(base, headers=h_ciudadano).json()["historial"]
    assert any(e["evento"] == "Derivada" and "Rentas y Tributos" in e["texto"] for e in eventos)
    assert all(e["evento"] != "Motivo de derivación" for e in eventos)
    # cerrada no se deriva
    client.put(f"{base}/gestionar", headers=rentas, json={"estado": "ATENDIDA", "respuesta": "Resuelto por Rentas."})
    assert client.put(f"{base}/derivar", headers=rentas, json={"area": "OBRAS", "motivo": "ya cerrada"}).status_code == 409


def test_tramites_por_area_para_funcionarios(client, h_admin, h_otro):
    rentas = _funcionario(client, h_admin, "30000003", "RENTAS")
    t_rentas = client.post(f"{API}/tramites/", headers=h_otro, json={"tipo": "CONSTANCIA_NO_ADEUDO", "detalles": {"motivo": "Trámite bancario"}}).json()
    t_obras = client.post(f"{API}/tramites/", headers=h_otro, json={"tipo": "LICENCIA_OBRA"}).json()
    ids = [t["id"] for t in client.get(f"{API}/tramites/admin/all", headers=rentas).json()]
    assert t_rentas["id"] in ids and t_obras["id"] not in ids
    assert client.get(f"{API}/tramites/{t_obras['id']}", headers=rentas).status_code == 404
    assert client.put(f"{API}/tramites/{t_obras['id']}/estado", headers=rentas, json={"estado": "APROBADO"}).status_code == 404
    assert client.get(f"{API}/tramites/{t_rentas['id']}", headers=rentas).status_code == 200


# ---------- Registro de cuenta ----------
REG = {"dni": "40000001", "nombre": "ana lucia rojas", "email": "ana.rojas@example.com", "password": "ClaveSegura123"}


def test_registro_crea_cuenta_y_permite_ingresar(client):
    r = client.post(f"{API}/auth/registro", json=REG)
    assert r.status_code == 201, r.text
    assert r.json()["user"]["role"] == "ciudadano" and r.json()["user"]["name"] == "ANA LUCIA ROJAS"
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get(f"{API}/auth/me", headers=h).json()["email"] == "ana.rojas@example.com"
    assert _login(client, "40000001", "ClaveSegura123")
    assert any("Bienvenido" in n["titulo"] for n in client.get(f"{API}/notificaciones/", headers=h).json()["items"])


def test_registro_rechaza_duplicados_y_datos_invalidos(client):
    assert client.post(f"{API}/auth/registro", json={**REG, "dni": "40000002", "email": "x@example.com"}).status_code == 201
    assert client.post(f"{API}/auth/registro", json={**REG, "dni": "40000002", "email": "otro@example.com"}).status_code == 409
    assert client.post(f"{API}/auth/registro", json={**REG, "dni": "40000003", "email": "x@example.com"}).status_code == 409
    for malo in ({"dni": "123"}, {"email": "no-es-correo"}, {"password": "123"}, {"nombre": "A"}, {"telefono": "abc"}):
        assert client.post(f"{API}/auth/registro", json={**REG, "dni": "40000004", **malo}).status_code == 422


def test_registro_no_permite_elegir_rol(client):
    r = client.post(f"{API}/auth/registro", json={**REG, "dni": "40000005", "email": "r5@example.com", "role": "admin"})
    assert r.status_code == 201 and r.json()["user"]["role"] == "ciudadano"


def test_registro_limita_por_ip(client, monkeypatch):
    from controllers import auth_controller as ac
    monkeypatch.setattr(ac._registros, "max_events", 5)
    ac._registros._events.clear()
    codigos = []
    for i in range(7):
        codigos.append(client.post(f"{API}/auth/registro", json={**REG, "dni": f"4100000{i}", "email": f"lim{i}@example.com"}).status_code)
    assert 429 in codigos


# ---------- Recuperación de contraseña ----------
@pytest.fixture()
def correos(monkeypatch):
    """Captura los correos de recuperación en lugar de enviarlos."""
    enviados = []
    from controllers import auth_controller as ac
    monkeypatch.setattr(ac, "correo_inmediato", lambda dest, asunto, texto: enviados.append((dest, asunto, texto)))
    for lim in (ac._olvidos_ip, ac._olvidos_dni, ac._intentos_codigo):
        lim._events.clear()
    return enviados


def _codigo_de(correos):
    import re
    return re.search(r"\b(\d{6})\b", correos[-1][2]).group(1)


def test_recuperar_clave_flujo_completo(client, correos):
    client.post(f"{API}/auth/registro", json={**REG, "dni": "42000001", "email": "rec1@example.com"})
    r = client.post(f"{API}/auth/olvide-clave", json={"dni": "42000001"})
    assert r.status_code == 200 and len(correos) == 1 and correos[0][0] == "rec1@example.com"
    codigo = _codigo_de(correos)
    mal = "000000" if codigo != "000000" else "111111"
    assert client.post(f"{API}/auth/restablecer-clave", json={"dni": "42000001", "codigo": mal, "nueva_clave": "NuevaClave456"}).status_code == 400
    ok = client.post(f"{API}/auth/restablecer-clave", json={"dni": "42000001", "codigo": codigo, "nueva_clave": "NuevaClave456"})
    assert ok.status_code == 200
    assert client.post(f"{API}/auth/login", data={"username": "42000001", "password": "ClaveSegura123"}).status_code == 401
    assert _login(client, "42000001", "NuevaClave456")
    # el código no se reutiliza
    assert client.post(f"{API}/auth/restablecer-clave", json={"dni": "42000001", "codigo": codigo, "nueva_clave": "OtraClave789"}).status_code == 400


def test_recuperar_no_revela_si_la_cuenta_existe(client, correos):
    existe = client.post(f"{API}/auth/olvide-clave", json={"dni": "12345678"}).json()
    no_existe = client.post(f"{API}/auth/olvide-clave", json={"dni": "99999999"}).json()
    assert existe == no_existe
    assert len(correos) == 1  # solo se envió el de la cuenta real


def test_codigo_se_quema_tras_demasiados_intentos(client, correos):
    client.post(f"{API}/auth/registro", json={**REG, "dni": "42000002", "email": "rec2@example.com"})
    client.post(f"{API}/auth/olvide-clave", json={"dni": "42000002"})
    codigo = _codigo_de(correos)
    mal = "000000" if codigo != "000000" else "111111"
    for _ in range(5):
        assert client.post(f"{API}/auth/restablecer-clave", json={"dni": "42000002", "codigo": mal, "nueva_clave": "NuevaClave456"}).status_code == 400
    # aunque ahora acierte, el código ya está quemado
    assert client.post(f"{API}/auth/restablecer-clave", json={"dni": "42000002", "codigo": codigo, "nueva_clave": "NuevaClave456"}).status_code == 400


def test_nuevo_codigo_invalida_el_anterior(client, correos):
    client.post(f"{API}/auth/registro", json={**REG, "dni": "42000003", "email": "rec3@example.com"})
    client.post(f"{API}/auth/olvide-clave", json={"dni": "42000003"})
    viejo = _codigo_de(correos)
    client.post(f"{API}/auth/olvide-clave", json={"dni": "42000003"})
    nuevo = _codigo_de(correos)
    if viejo != nuevo:
        assert client.post(f"{API}/auth/restablecer-clave", json={"dni": "42000003", "codigo": viejo, "nueva_clave": "NuevaClave456"}).status_code == 400
    assert client.post(f"{API}/auth/restablecer-clave", json={"dni": "42000003", "codigo": nuevo, "nueva_clave": "NuevaClave456"}).status_code == 200


def test_pedir_codigo_tiene_limite_por_dni(client, correos):
    estados = [client.post(f"{API}/auth/olvide-clave", json={"dni": "12345678"}).status_code for _ in range(5)]
    assert estados[:3] == [200, 200, 200] and 429 in estados


# ---------- Consulta pública ----------
def test_consulta_publica_de_solicitud(client, h_ciudadano):
    s = nueva(client, h_ciudadano, descripcion="Texto privado que no debe aparecer en la consulta pública, jamás.")
    r = client.get(f"{API}/publico/seguimiento", params={"codigo": s["codigo"].lower(), "dni": "12345678"})
    assert r.status_code == 200
    d = r.json()
    assert d["codigo"] == s["codigo"] and d["estado"] == "Recibida" and d["eventos"][0]["titulo"] == "Registrada"
    texto = r.text
    assert "Texto privado" not in texto and "DELGADO" not in texto and "descripcion" not in texto


def test_consulta_publica_misma_respuesta_si_falla(client, h_ciudadano):
    s = nueva(client, h_ciudadano)
    dni_malo = client.get(f"{API}/publico/seguimiento", params={"codigo": s["codigo"], "dni": "87654321"})
    codigo_malo = client.get(f"{API}/publico/seguimiento", params={"codigo": "QJ-2026-99999", "dni": "12345678"})
    formato_malo = client.get(f"{API}/publico/seguimiento", params={"codigo": "cualquier cosa", "dni": "12345678"})
    assert dni_malo.status_code == codigo_malo.status_code == formato_malo.status_code == 404
    assert dni_malo.json() == codigo_malo.json() == formato_malo.json()


def test_consulta_publica_de_tramite(client, h_otro, h_admin):
    t = client.post(f"{API}/tramites/", headers=h_otro, json={"tipo": "PARTIDA_NACIMIENTO"}).json()
    dni = client.get(f"{API}/auth/me", headers=h_otro).json()["dni"]
    d = client.get(f"{API}/publico/seguimiento", params={"codigo": t["expediente"], "dni": dni}).json()
    assert d["tipo"].startswith("Trámite") and d["eventos"][0]["titulo"] == "Trámite registrado"
    assert client.get(f"{API}/publico/seguimiento", params={"codigo": t["expediente"], "dni": "12345678"}).status_code == 404


def test_consulta_publica_limita_por_ip(client):
    from controllers import publico_controller as pc
    pc._limite._events.clear()
    codigos = [client.get(f"{API}/publico/seguimiento", params={"codigo": "QJ-2026-00001", "dni": "00000000"}).status_code for _ in range(25)]
    assert 429 in codigos


def test_pagina_publica_de_seguimiento(client):
    r = client.get("/seguimiento")
    assert r.status_code == 200 and "Consulta de seguimiento" in r.text


# ---------- Reportes y auditoría ----------
def test_reportes_de_gestion(client, h_admin, h_ciudadano):
    s = nueva(client, h_ciudadano, clase="RECLAMO", categoria="COBRO_INDEBIDO")
    client.put(f"{API}/solicitudes/{s['id']}/gestionar", headers=h_admin, json={"estado": "ATENDIDA", "respuesta": "Cobro corregido y devuelto."})
    r = client.get(f"{API}/admin/reportes", headers=h_admin)
    assert r.status_code == 200
    d = r.json()
    assert d["solicitudes"]["total"] >= 1 and d["solicitudes"]["atendidas"] >= 1 and d["solicitudes"]["en_plazo_pct"] is not None
    assert d["solicitudes"]["tiempo_promedio_dias"] is not None and d["tramites"]["total"] >= 0
    rentas = next(a for a in d["por_area"] if a["area"] == "RENTAS")
    assert rentas["atendidas"] >= 1 and len(d["por_area"]) == 6
    assert client.get(f"{API}/admin/reportes", headers=h_ciudadano).status_code == 403


def test_auditoria_registra_acciones_del_personal(client, h_admin, h_staff, h_ciudadano):
    _funcionario(client, h_admin, "30000009", "OBRAS")
    s = nueva(client, h_ciudadano, clase="RECLAMO", categoria="ALUMBRADO")
    client.put(f"{API}/solicitudes/{s['id']}/derivar", headers=h_staff, json={"area": "OBRAS", "motivo": "Requiere obra de postes"})
    client.put(f"{API}/solicitudes/{s['id']}/gestionar", headers=h_admin, json={"estado": "IMPROCEDENTE", "respuesta": "No corresponde al municipio."})
    log = client.get(f"{API}/admin/auditoria", headers=h_admin, params={"q": s["codigo"]}).json()
    acciones = {e["accion"] for e in log}
    assert {"SOLICITUD_DERIVADA", "SOLICITUD_IMPROCEDENTE"} <= acciones
    derivada = next(e for e in log if e["accion"] == "SOLICITUD_DERIVADA")
    assert derivada["usuario_dni"] == "11223344" and "Obras y Desarrollo Urbano" in derivada["detalle"]
    assert client.get(f"{API}/admin/auditoria", headers=h_admin, params={"accion": "USUARIO_CREADO"}).json()
    assert client.get(f"{API}/admin/auditoria", headers=h_ciudadano).status_code == 403


# ---------- Avisos por correo y WhatsApp ----------
class _Inline:
    """Ejecuta los envíos en el acto (en la app real van a un hilo)."""
    def submit(self, fn, *args):
        fn(*args)


@pytest.fixture()
def canales(monkeypatch):
    from services import mensajeria
    correos, whatsapps = [], []

    class FakeSMTP:
        def __init__(self, host, port, timeout=0): self.datos = (host, port)
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def starttls(self, context=None): pass
        def login(self, u, p): self.cred = (u, p)
        def send_message(self, msg): correos.append(msg)

    class FakeResp:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(config, "EMAIL_ACTIVO", True)
    monkeypatch.setattr(config, "SMTP_HOST", "smtp.prueba.test")
    monkeypatch.setattr(config, "SMTP_USER", "muni@prueba.test")
    monkeypatch.setattr(config, "SMTP_FROM", "muni@prueba.test")
    monkeypatch.setattr(config, "SMTP_PASSWORD", "x")
    monkeypatch.setattr(config, "WHATSAPP_ACTIVO", True)
    monkeypatch.setattr(config, "CALLMEBOT_PHONE", "+51999888777")
    monkeypatch.setattr(config, "CALLMEBOT_APIKEY", "123456")
    monkeypatch.setattr(mensajeria, "_pool", _Inline())
    monkeypatch.setattr(mensajeria.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(mensajeria.urllib.request, "urlopen", lambda url, timeout=0: (whatsapps.append(url), FakeResp())[1])
    return correos, whatsapps


def test_aviso_por_correo_al_ciudadano_y_whatsapp_al_personal(client, h_ciudadano, canales):
    correos, whatsapps = canales
    s = nueva(client, h_ciudadano)
    para_ciudadano = [m for m in correos if m["To"] == "jcdelgado@example.com"]
    assert para_ciudadano and s["codigo"] in para_ciudadano[-1].get_content()
    assert "no responda" in para_ciudadano[-1].get_content().lower()
    assert whatsapps and "phone=%2B51999888777" in whatsapps[0] and "apikey=123456" in whatsapps[0]
    assert len(whatsapps) == 1  # un solo WhatsApp al número configurado, no uno por funcionario


def test_si_la_solicitud_falla_no_se_envia_ningun_aviso(client, h_ciudadano, canales):
    correos, whatsapps = canales
    r = client.post(f"{API}/solicitudes/", headers=h_ciudadano, json={**QUEJA, "descripcion": "corta"})
    assert r.status_code == 422 and not correos and not whatsapps


def test_un_error_de_correo_no_rompe_la_peticion(client, h_ciudadano, canales, monkeypatch):
    from services import mensajeria

    class Roto:
        def __init__(self, *a, **k): raise OSError("sin red")
    monkeypatch.setattr(mensajeria.smtplib, "SMTP", Roto)
    monkeypatch.setattr(mensajeria.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError("sin red")))
    assert client.post(f"{API}/solicitudes/", headers=h_ciudadano, json=QUEJA).status_code == 201


def test_sin_configuracion_no_se_envia_nada(client, h_ciudadano, monkeypatch):
    from services import mensajeria
    llamadas = []
    monkeypatch.setattr(mensajeria, "_pool", type("P", (), {"submit": lambda self, *a: llamadas.append(a)})())
    nueva(client, h_ciudadano)
    assert not llamadas
