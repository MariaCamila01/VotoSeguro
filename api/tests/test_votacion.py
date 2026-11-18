"""Flujo del votante: OTP → JWT → voto → comprobante (secciones 3.1 y 3.2)."""
import hashlib
import threading

import psycopg


def test_flujo_completo(cliente, eleccion):
    eid, op = eleccion["id"], eleccion["opciones"]

    # El votante ve la elección abierta sin autenticarse
    abiertas = cliente.get("/elecciones").get_json()
    assert [e["id"] for e in abiertas] == [eid]

    r = cliente.post("/auth/otp/solicitar", {"documentoInstitucional": "est0001", "eleccionId": eid,
                                             "aceptaTratamientoDatos": True})
    assert r.status_code == 200
    cuerpo = r.get_json()
    assert cuerpo["mensaje"] == "OTP enviado" and cuerpo["expiraEn"] == 300
    assert cuerpo["destino"] == "e***1@umb.edu.co"           # correo enmascarado

    r = cliente.post("/auth/otp/verificar", {"documentoInstitucional": "EST0001", "eleccionId": eid,
                                             "codigoOTP": cliente.ultimo_otp()})
    assert r.status_code == 200 and r.get_json()["expiraEn"] == 600
    token = r.get_json()["token"]

    r = cliente.post("/votos", {"opcionId": op["Lista A"]}, token=token)
    assert r.status_code == 201, r.get_json()
    comp = r.get_json()
    assert comp["indiceBloque"] == 0 and len(comp["hashBloque"]) == 64

    # Comprobante público: confirma inclusión sin revelar la opción
    r = cliente.get(f"/ledger/comprobante/{comp['confirmacion']}")
    assert r.status_code == 200
    assert r.get_json()["hashBloque"] == comp["hashBloque"]
    assert "opcion" not in str(r.get_json()).lower()

    # El JWT ya no sirve para votar (409) pero sí para consultar el estado
    assert cliente.post("/votos", {"opcionId": op["Lista B"]}, token=token).status_code == 409
    estado = cliente.get(f"/elecciones/{eid}/estado", token=token).get_json()
    assert estado == {**estado, "estado": "ABIERTA", "totalVotosEmitidos": 1, "yaVoto": True}

    # Y no puede pedir otro OTP
    r = cliente.post("/auth/otp/solicitar", {"documentoInstitucional": "EST0001", "eleccionId": eid,
                                             "aceptaTratamientoDatos": True})
    assert r.status_code == 403 and r.get_json()["error"]["codigo"] == "YA_VOTO"


def test_requiere_autorizacion_de_datos(cliente, eleccion):
    r = cliente.post("/auth/otp/solicitar", {"documentoInstitucional": "EST0001", "eleccionId": eleccion["id"]})
    assert r.status_code == 400
    assert r.get_json()["error"]["codigo"] == "AUTORIZACION_DATOS_REQUERIDA"


def test_consentimiento_queda_registrado(cliente, eleccion, bd):
    cliente.jwt_votante("EST0002", eleccion["id"])
    fila = bd.execute("SELECT count(*) AS n FROM votante WHERE fecha_autorizacion_datos IS NOT NULL "
                      "AND version_politica_datos = '1.0'").fetchone()
    assert fila["n"] == 1


def test_documento_fuera_del_padron(cliente, eleccion):
    r = cliente.post("/auth/otp/solicitar", {"documentoInstitucional": "NOEXISTE1", "eleccionId": eleccion["id"],
                                             "aceptaTratamientoDatos": True})
    assert r.status_code == 404


def test_payload_mal_formado(cliente, eleccion):
    assert cliente.post("/auth/otp/solicitar", {"documentoInstitucional": "x"}).status_code == 400
    assert cliente.post("/auth/otp/verificar", {"documentoInstitucional": "EST0001", "eleccionId": eleccion["id"],
                                                "codigoOTP": "12ab"}).status_code == 400


def test_limite_de_solicitudes_otp(cliente, eleccion):
    datos = {"documentoInstitucional": "EST0003", "eleccionId": eleccion["id"], "aceptaTratamientoDatos": True}
    for _ in range(3):
        assert cliente.post("/auth/otp/solicitar", datos).status_code == 200
    r = cliente.post("/auth/otp/solicitar", datos)
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) > 0


def test_otp_se_bloquea_tras_5_intentos(cliente, eleccion):
    eid = eleccion["id"]
    cliente.post("/auth/otp/solicitar", {"documentoInstitucional": "EST0004", "eleccionId": eid,
                                         "aceptaTratamientoDatos": True})
    correcto = cliente.ultimo_otp()
    incorrecto = "000000" if correcto != "000000" else "111111"
    for restantes in (4, 3, 2, 1):
        r = cliente.post("/auth/otp/verificar", {"documentoInstitucional": "EST0004", "eleccionId": eid,
                                                 "codigoOTP": incorrecto})
        assert r.status_code == 401 and r.get_json()["error"]["intentosRestantes"] == restantes
    r = cliente.post("/auth/otp/verificar", {"documentoInstitucional": "EST0004", "eleccionId": eid,
                                             "codigoOTP": incorrecto})
    assert r.get_json()["error"]["codigo"] == "OTP_BLOQUEADO"
    # Ni el código correcto sirve ya
    r = cliente.post("/auth/otp/verificar", {"documentoInstitucional": "EST0004", "eleccionId": eid,
                                             "codigoOTP": correcto})
    assert r.status_code == 401


def test_otp_expirado(cliente, eleccion, bd):
    eid = eleccion["id"]
    cliente.post("/auth/otp/solicitar", {"documentoInstitucional": "EST0005", "eleccionId": eid,
                                         "aceptaTratamientoDatos": True})
    bd.execute("UPDATE codigo_otp SET fecha_generacion = fecha_generacion - interval '1 hour', "
               "fecha_expiracion = fecha_expiracion - interval '1 hour'")
    r = cliente.post("/auth/otp/verificar", {"documentoInstitucional": "EST0005", "eleccionId": eid,
                                             "codigoOTP": cliente.ultimo_otp()})
    assert r.status_code == 401 and r.get_json()["error"]["codigo"] == "OTP_EXPIRADO"


def test_otp_no_se_guarda_en_claro_ni_con_sha256_simple(cliente, eleccion, bd):
    cliente.post("/auth/otp/solicitar", {"documentoInstitucional": "EST0006", "eleccionId": eleccion["id"],
                                         "aceptaTratamientoDatos": True})
    codigo = cliente.ultimo_otp()
    guardado = bd.execute("SELECT codigo_hash FROM codigo_otp").fetchone()["codigo_hash"]
    assert codigo not in guardado
    assert guardado != hashlib.sha256(codigo.encode()).hexdigest()


def test_doble_voto_con_dos_jwt_distintos(cliente, eleccion):
    eid, op = eleccion["id"], eleccion["opciones"]
    jwt1 = cliente.jwt_votante("EST0007", eid)
    jwt2 = cliente.jwt_votante("EST0007", eid)
    assert cliente.post("/votos", {"opcionId": op["Lista A"]}, token=jwt1).status_code == 201
    r = cliente.post("/votos", {"opcionId": op["Lista B"]}, token=jwt2)
    assert r.status_code == 403 and r.get_json()["error"]["codigo"] == "YA_VOTO"


def test_opcion_de_otra_eleccion_y_jwt_consumido(cliente, eleccion):
    token = cliente.jwt_votante("EST0008", eleccion["id"])
    r = cliente.post("/votos", {"opcionId": "00000000-0000-4000-8000-000000000000"}, token=token)
    assert r.status_code == 422
    # Sección 5.3: el JWT se invalida aunque el voto falle
    r = cliente.post("/votos", {"opcionId": eleccion["opciones"]["Lista A"]}, token=token)
    assert r.status_code == 409
    # Puede volver a pedir OTP y votar, porque no quedó emisión registrada
    assert cliente.votar("EST0008", eleccion["id"], eleccion["opciones"]["Lista A"]).status_code == 201


def test_votos_concurrentes_mantienen_la_cadena(cliente, eleccion, app):
    eid, op = eleccion["id"], eleccion["opciones"]
    tokens = [cliente.jwt_votante(f"EST{i:04d}", eid) for i in range(1, 11)]
    resultados = []

    def votar(tok):
        c = app.test_client()
        r = c.post("/api/v1/votos", json={"opcionId": op["Lista B"]}, headers={"Authorization": f"Bearer {tok}"})
        resultados.append(r.status_code)

    hilos = [threading.Thread(target=votar, args=(t,)) for t in tokens]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    assert resultados == [201] * 10
    v = cliente.get(f"/ledger/{eid}/verificar", token=eleccion["admin"]).get_json()
    assert v["integro"] and v["totalBloques"] == 10


def test_la_aplicacion_no_puede_modificar_votos(cliente, eleccion):
    """El rol de la API no tiene permiso UPDATE/DELETE sobre voto ni bloque_ledger."""
    from conftest import APP_URL
    cliente.votar("EST0009", eleccion["id"], eleccion["opciones"]["Lista A"])
    with psycopg.connect(APP_URL) as c:
        for sql in ("UPDATE voto SET hash_voto = 'x'", "DELETE FROM bloque_ledger",
                    "DELETE FROM registro_auditoria"):
            try:
                c.execute(sql)
                raise AssertionError(f"Debió fallar: {sql}")
            except psycopg.errors.InsufficientPrivilege:
                c.rollback()
