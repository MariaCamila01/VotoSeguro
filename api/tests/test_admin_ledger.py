"""Administración, RBAC, ledger, anonimato y habeas data (secciones 2.3, 3.3–3.5, 5)."""
import base64
import json
from datetime import timedelta


# ---------------------------------------------------------------- RBAC (2.3)
def test_rbac(cliente, eleccion):
    eid = eleccion["id"]
    votante = cliente.jwt_votante("EST0001", eid)
    auditor = cliente.login("auditor")
    admin = eleccion["admin"]

    assert cliente.get(f"/reportes/{eid}").status_code == 401                    # sin token
    assert cliente.get(f"/reportes/{eid}", token=votante).status_code == 403     # votante
    assert cliente.post("/elecciones", {}, token=auditor).status_code == 403     # auditor no crea
    assert cliente.get(f"/ledger/{eid}/cadena", token=admin).status_code == 403  # cadena: solo auditor
    assert cliente.get(f"/ledger/{eid}/cadena", token=auditor).status_code == 200
    assert cliente.get(f"/ledger/{eid}/verificar", token=auditor).status_code == 200
    assert cliente.post("/votos", {"opcionId": eleccion["opciones"]["Lista A"]}, token=admin).status_code == 403


def test_token_manipulado_o_alg_none(cliente, eleccion):
    admin = eleccion["admin"]
    cab, carga, firma = admin.split(".")
    datos = json.loads(base64.urlsafe_b64decode(carga + "=="))
    datos["role"] = "auditor"
    carga2 = base64.urlsafe_b64encode(json.dumps(datos).encode()).decode().rstrip("=")
    assert cliente.get("/auditoria", token=f"{cab}.{carga2}.{firma}").status_code == 401
    none = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').decode().rstrip("=")
    assert cliente.get("/auditoria", token=f"{none}.{carga}.").status_code == 401


def test_logout_revoca_el_token(cliente, cuentas):
    token = cliente.login()
    assert cliente.get("/auditoria", token=token).status_code == 200
    assert cliente.post("/auth/logout", token=token).status_code == 200
    r = cliente.get("/auditoria", token=token)
    assert r.status_code == 401 and r.get_json()["error"]["codigo"] == "TOKEN_REVOCADO"


def test_login_limita_intentos(cliente, cuentas):
    for _ in range(5):
        assert cliente.post("/auth/admin/login", {"usuario": "admin", "password": "mala"}).status_code == 401
    r = cliente.post("/auth/admin/login", {"usuario": "admin", "password": "Clave-segura-123"})
    assert r.status_code == 429


# ------------------------------------------------- Ciclo de la elección (3.3)
def test_ciclo_de_vida_de_la_eleccion(cliente, cuentas):
    from app.db import ahora
    admin = cliente.login()
    t = ahora()
    r = cliente.post("/elecciones", {"nombre": "Comité de Bienestar",
                                     "fechaInicio": (t - timedelta(minutes=5)).isoformat() + "Z",
                                     "fechaFin": (t + timedelta(hours=3)).isoformat() + "Z"}, token=admin)
    assert r.status_code == 201 and r.get_json()["estado"] == "BORRADOR"
    eid = r.get_json()["id"]

    # BORRADOR: no visible para votantes, no se puede abrir sin opciones
    assert cliente.get("/elecciones").get_json() == []
    assert cliente.get(f"/elecciones/{eid}/opciones").status_code == 404
    assert cliente.post(f"/elecciones/{eid}/abrir", token=admin).status_code == 422

    r = cliente.put(f"/elecciones/{eid}/opciones",
                    {"opciones": [{"nombre": "Ana"}, {"nombre": "Luis"}, {"nombre": "Voto en blanco"}]}, token=admin)
    assert r.status_code == 200 and len(r.get_json()) == 3
    op = {o["nombre"]: o["id"] for o in r.get_json()}
    assert cliente.post(f"/elecciones/{eid}/abrir", token=admin).status_code == 200

    # ABIERTA: no se editan opciones ni hay resultados parciales
    assert cliente.put(f"/elecciones/{eid}/opciones", {"opciones": [{"nombre": "X"}, {"nombre": "Y"}]},
                       token=admin).status_code == 409
    assert cliente.get(f"/reportes/{eid}", token=admin).status_code == 409

    cliente.post("/votantes", {"votantes": [{"documentoInstitucional": f"V{i:04d}", "correo": f"v{i}@umb.edu.co"}
                                            for i in range(5)]}, token=admin)
    for i, nombre in enumerate(["Ana", "Ana", "Luis", "Ana", "Voto en blanco"]):
        assert cliente.votar(f"V{i:04d}", eid, op[nombre]).status_code == 201

    # Cerrar dispara la verificación del ledger
    r = cliente.post(f"/elecciones/{eid}/cerrar", token=admin)
    assert r.status_code == 200
    assert r.get_json()["estado"] == "CERRADA" and r.get_json()["verificacion"]["integro"] is True
    assert cliente.post(f"/elecciones/{eid}/cerrar", token=admin).status_code == 409

    # Ya no se puede votar
    r = cliente.post("/auth/otp/solicitar", {"documentoInstitucional": "EST0001", "eleccionId": eid,
                                             "aceptaTratamientoDatos": True})
    assert r.status_code == 409

    rep = cliente.get(f"/reportes/{eid}", token=admin).get_json()
    assert rep["totalVotos"] == 5
    assert [(x["nombre"], x["votos"]) for x in rep["resultados"]] == [("Ana", 3), ("Luis", 1), ("Voto en blanco", 1)]
    assert rep["resultados"][0]["porcentaje"] == 60.0
    assert rep["integridad"]["integro"] is True and rep["integridad"]["anclaVerificada"] is True

    acciones = {a["accion"] for a in cliente.get("/auditoria", token=admin).get_json()}
    assert {"CREAR_ELECCION", "DEFINIR_OPCIONES", "ABRIR_ELECCION", "CERRAR_ELECCION",
            "ANCLA_LEDGER", "GENERAR_REPORTE", "CARGAR_PADRON"} <= acciones


def test_fechas_invalidas(cliente, cuentas):
    admin = cliente.login()
    r = cliente.post("/elecciones", {"nombre": "Mal", "fechaInicio": "2026-09-20T18:00:00Z",
                                     "fechaFin": "2026-09-20T08:00:00Z"}, token=admin)
    assert r.status_code == 422


# ----------------------------------------------------- Ledger (3.4 y 5.1)
def _votar_varios(cliente, eleccion, n):
    for i in range(1, n + 1):
        assert cliente.votar(f"EST{i:04d}", eleccion["id"], eleccion["opciones"]["Lista A"]).status_code == 201


def test_detecta_voto_alterado(cliente, eleccion, bd):
    _votar_varios(cliente, eleccion, 4)
    eid, auditor = eleccion["id"], cliente.login("auditor")
    assert cliente.get(f"/ledger/{eid}/verificar", token=auditor).get_json()["integro"] is True

    # Un atacante con acceso total a la BD cambia el voto del bloque 2
    bd.execute("ALTER TABLE voto DISABLE TRIGGER trg_voto_inmutable")
    bd.execute("UPDATE voto SET opcion_id = %s WHERE id = (SELECT voto_id FROM bloque_ledger "
               "WHERE eleccion_id = %s AND indice = 2)", (eleccion["opciones"]["Lista B"], eid))
    bd.execute("ALTER TABLE voto ENABLE TRIGGER trg_voto_inmutable")

    v = cliente.get(f"/ledger/{eid}/verificar", token=auditor).get_json()
    assert v["integro"] is False and v["indiceFalla"] == 2
    assert "alterado" in v["motivo"]
    alertas = cliente.get("/auditoria?accion=INTEGRIDAD_COMPROMETIDA", token=auditor).get_json()
    assert alertas and alertas[0]["detalle"]["indiceFalla"] == 2


def test_detecta_bloque_recalculado(cliente, eleccion, bd):
    """Aunque el atacante recalcule hash_voto y hash_actual del bloque, se rompe el enlace con el siguiente."""
    from app.servicios.ledger import calcular_hash_bloque
    _votar_varios(cliente, eleccion, 3)
    eid = eleccion["id"]
    b = bd.execute("SELECT * FROM bloque_ledger WHERE eleccion_id = %s AND indice = 1", (eid,)).fetchone()
    nuevo = calcular_hash_bloque(eid, 1, b["hash_anterior"], "f" * 64, b["timestamp_bloque"])
    bd.execute("ALTER TABLE bloque_ledger DISABLE TRIGGER trg_bloque_inmutable")
    bd.execute("UPDATE bloque_ledger SET hash_actual = %s WHERE id = %s", (nuevo, b["id"]))
    bd.execute("ALTER TABLE bloque_ledger ENABLE TRIGGER trg_bloque_inmutable")
    v = cliente.get(f"/ledger/{eid}/verificar", token=eleccion["admin"]).get_json()
    assert v["integro"] is False and v["indiceFalla"] == 1


def test_detecta_borrado_del_ultimo_bloque_tras_el_cierre(cliente, eleccion, bd):
    _votar_varios(cliente, eleccion, 3)
    eid, admin = eleccion["id"], eleccion["admin"]
    cliente.post(f"/elecciones/{eid}/cerrar", token=admin)
    bd.execute("ALTER TABLE bloque_ledger DISABLE TRIGGER trg_bloque_inmutable")
    bd.execute("ALTER TABLE voto DISABLE TRIGGER trg_voto_inmutable")
    bd.execute("WITH b AS (DELETE FROM bloque_ledger WHERE eleccion_id = %s AND indice = 2 RETURNING voto_id) "
               "DELETE FROM voto WHERE id IN (SELECT voto_id FROM b)", (eid,))
    bd.execute("ALTER TABLE bloque_ledger ENABLE TRIGGER trg_bloque_inmutable")
    bd.execute("ALTER TABLE voto ENABLE TRIGGER trg_voto_inmutable")
    v = cliente.get(f"/ledger/{eid}/verificar", token=admin).get_json()
    assert v["integro"] is False and "ancla" in v["motivo"]
    assert v["advertencias"]                              # 3 emisiones vs 2 votos


def test_detecta_votos_insertados_por_fuera(cliente, eleccion, bd):
    _votar_varios(cliente, eleccion, 2)
    eid = eleccion["id"]
    tok = bd.execute("INSERT INTO token_voto (eleccion_id, hash, usado) VALUES (%s, %s, TRUE) RETURNING id",
                     (eid, "a" * 64)).fetchone()["id"]
    bd.execute("INSERT INTO voto (token_voto_id, opcion_id, hash_voto) VALUES (%s, %s, %s)",
               (tok, eleccion["opciones"]["Lista B"], "b" * 64))
    v = cliente.get(f"/ledger/{eid}/verificar", token=eleccion["admin"]).get_json()
    assert v["integro"] is False


def test_cadena_no_expone_identidad_ni_opcion(cliente, eleccion):
    _votar_varios(cliente, eleccion, 2)
    r = cliente.get(f"/ledger/{eleccion['id']}/cadena", token=cliente.login("auditor")).get_json()
    assert r["totalBloques"] == 2
    assert set(r["bloques"][0]) == {"indice", "hashAnterior", "hashActual", "hashVoto", "timestamp"}
    assert r["bloques"][1]["hashAnterior"] == r["bloques"][0]["hashActual"]


# ------------------------------------------- Separación identidad–voto (5.1)
def test_ninguna_ruta_de_claves_foraneas_une_voto_con_votante(bd):
    fks = bd.execute("""
        SELECT tc.table_name AS origen, ccu.table_name AS destino
          FROM information_schema.table_constraints tc
          JOIN information_schema.constraint_column_usage ccu ON ccu.constraint_name = tc.constraint_name
         WHERE tc.constraint_type = 'FOREIGN KEY'""").fetchall()
    grafo = {}
    for f in fks:
        grafo.setdefault(f["origen"], set()).add(f["destino"])
        grafo.setdefault(f["destino"], set()).add(f["origen"])   # en un JOIN la dirección no importa

    # Quitando las tablas "hub" que comparten todos (eleccion, administrador),
    # no debe existir ningún camino entre voto y votante.
    hubs = {"eleccion", "administrador", "opcion_voto"}
    visitados, pila = set(), ["voto"]
    while pila:
        t = pila.pop()
        if t in visitados or t in hubs:
            continue
        visitados.add(t)
        pila.extend(grafo.get(t, ()))
    assert "votante" not in visitados, visitados
    assert "emision_token" not in visitados


def test_datos_personales_cifrados_en_reposo(cliente, eleccion, bd):
    fila = bd.execute("SELECT * FROM votante LIMIT 1").fetchone()
    crudo = json.dumps({k: (bytes(v).hex() if isinstance(v, (bytes, memoryview)) else str(v))
                        for k, v in fila.items()})
    assert "EST" not in crudo and "umb.edu.co" not in crudo
    assert "documento_institucional" not in fila and "correo" not in fila


# ----------------------------------------------------- Habeas data (5.2)
def test_supresion_de_datos(cliente, eleccion, bd):
    eid, admin = eleccion["id"], eleccion["admin"]
    cliente.votar("EST0001", eid, eleccion["opciones"]["Lista A"])

    r = cliente.post("/votantes/suprimir", {"documentoInstitucional": "EST0001"}, token=admin)
    assert r.status_code == 409                       # elección todavía abierta

    cliente.post(f"/elecciones/{eid}/cerrar", token=admin)
    assert cliente.post("/votantes/suprimir", {"documentoInstitucional": "EST0001"}, token=admin).status_code == 200
    assert cliente.post("/votantes/suprimir", {"documentoInstitucional": "EST0001"}, token=admin).status_code == 404

    # El voto sigue contado y la cadena sigue íntegra
    rep = cliente.get(f"/reportes/{eid}", token=admin).get_json()
    assert rep["totalVotos"] == 1 and rep["integridad"]["integro"] is True
    assert bd.execute("SELECT count(*) AS n FROM emision_token WHERE votante_id IS NULL").fetchone()["n"] == 1
