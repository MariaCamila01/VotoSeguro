"""Módulo de Ledger (hash-chain) — persistido en la tabla bloque_ledger.

Cada bloque guarda el hash del bloque anterior, así que cambiar un voto ya
registrado obliga a recalcular todos los bloques siguientes; la verificación
lo detecta. No hay prueba de trabajo (minado): en un sistema con un único
operador no aporta seguridad y solo añade latencia.

    hash_voto   = SHA256("voto"   | hash_token | opcion_id | eleccion_id | timestamp_voto)
    hash_actual = SHA256("bloque" | eleccion_id | indice | hash_anterior | hash_voto | timestamp_bloque)
"""
import json

from ..db import ahora, iso
from ..seguridad.cripto import sha256_hex

GENESIS = "0" * 64


def _ts(dt):
    return dt.isoformat(timespec="microseconds")


def calcular_hash_voto(hash_token, opcion_id, eleccion_id, timestamp_voto):
    return sha256_hex("|".join(["voto", hash_token, str(opcion_id), str(eleccion_id), _ts(timestamp_voto)]))


def calcular_hash_bloque(eleccion_id, indice, hash_anterior, hash_voto, timestamp_bloque):
    return sha256_hex("|".join([
        "bloque", str(eleccion_id), str(indice), hash_anterior, hash_voto, _ts(timestamp_bloque),
    ]))


def agregar_bloque(cur, eleccion_id, voto_id, hash_voto):
    """Agrega un bloque. El llamador debe tener bloqueada la fila de la
    elección (SELECT ... FOR UPDATE) para que dos votos simultáneos no
    calculen el mismo índice."""
    cur.execute(
        "SELECT indice, hash_actual FROM bloque_ledger WHERE eleccion_id = %s "
        "ORDER BY indice DESC LIMIT 1",
        (eleccion_id,),
    )
    ultimo = cur.fetchone()
    indice = 0 if ultimo is None else ultimo["indice"] + 1
    hash_anterior = GENESIS if ultimo is None else ultimo["hash_actual"]
    ts = ahora()
    hash_actual = calcular_hash_bloque(eleccion_id, indice, hash_anterior, hash_voto, ts)
    cur.execute(
        "INSERT INTO bloque_ledger (eleccion_id, voto_id, hash_anterior, hash_actual, timestamp_bloque, indice) "
        "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
        (eleccion_id, voto_id, hash_anterior, hash_actual, ts, indice),
    )
    return {"id": str(cur.fetchone()["id"]), "indice": indice, "hash_actual": hash_actual, "timestamp": ts}


def obtener_ancla(cur, eleccion_id):
    """Hash final guardado al cerrar la elección (protege contra borrar los
    últimos bloques, que la cadena por sí sola no detecta)."""
    cur.execute(
        "SELECT detalle FROM registro_auditoria WHERE accion = 'ANCLA_LEDGER' "
        "AND (detalle::jsonb ->> 'eleccionId') = %s ORDER BY timestamp_accion DESC LIMIT 1",
        (str(eleccion_id),),
    )
    fila = cur.fetchone()
    return json.loads(fila["detalle"]) if fila else None


def verificar(cur, eleccion_id):
    cur.execute(
        """
        SELECT b.indice, b.hash_anterior, b.hash_actual, b.timestamp_bloque, b.voto_id,
               v.id AS v_id, v.opcion_id, v.timestamp_voto, v.hash_voto,
               t.hash AS token_hash, t.usado AS token_usado, t.eleccion_id AS token_eleccion,
               o.eleccion_id AS opcion_eleccion
          FROM bloque_ledger b
          LEFT JOIN voto v        ON v.id = b.voto_id
          LEFT JOIN token_voto t  ON t.id = v.token_voto_id
          LEFT JOIN opcion_voto o ON o.id = v.opcion_id
         WHERE b.eleccion_id = %s
         ORDER BY b.indice
        """,
        (eleccion_id,),
    )
    bloques = cur.fetchall()

    integro = True
    indice_falla = None
    motivo = None
    anterior = GENESIS
    eid = str(eleccion_id)

    for esperado, b in enumerate(bloques):
        problema = None
        if b["indice"] != esperado:
            problema = f"Falta el bloque {esperado} (la cadena salta al {b['indice']})"
        elif b["hash_anterior"] != anterior:
            problema = "hash_anterior no coincide con el hash del bloque previo"
        elif calcular_hash_bloque(eid, b["indice"], b["hash_anterior"], b["hash_voto"] or "",
                                  b["timestamp_bloque"]) != b["hash_actual"]:
            problema = "El contenido del bloque fue alterado (hash_actual no coincide)"
        elif b["v_id"] is None:
            problema = "El voto asociado al bloque no existe"
        elif (b["token_hash"] is None or not b["token_usado"]
              or str(b["token_eleccion"]) != eid or str(b["opcion_eleccion"]) != eid):
            problema = "El voto no corresponde a un token usado u opción de esta elección"
        elif calcular_hash_voto(b["token_hash"], b["opcion_id"], eid, b["timestamp_voto"]) != b["hash_voto"]:
            problema = "El voto fue alterado después de registrado (hash_voto no coincide)"

        if problema:
            integro, indice_falla, motivo = False, esperado, problema
            break
        anterior = b["hash_actual"]

    # Conteos cruzados: identidad (emisiones) vs. votos anónimos vs. bloques
    cur.execute("SELECT count(*) AS n FROM emision_token WHERE eleccion_id = %s", (eleccion_id,))
    emisiones = cur.fetchone()["n"]
    cur.execute(
        "SELECT count(*) AS n FROM voto v JOIN token_voto t ON t.id = v.token_voto_id WHERE t.eleccion_id = %s",
        (eleccion_id,),
    )
    votos = cur.fetchone()["n"]
    cur.execute(
        "SELECT count(*) AS n FROM voto v JOIN token_voto t ON t.id = v.token_voto_id "
        "LEFT JOIN bloque_ledger b ON b.voto_id = v.id WHERE t.eleccion_id = %s AND b.id IS NULL",
        (eleccion_id,),
    )
    votos_sin_bloque = cur.fetchone()["n"]

    advertencias = []
    if integro and votos_sin_bloque:
        integro, indice_falla = False, len(bloques)
        motivo = f"Hay {votos_sin_bloque} voto(s) sin bloque en el ledger"
    if integro and votos > emisiones:
        integro, indice_falla = False, None
        motivo = (f"Hay más votos ({votos}) que tokens emitidos a votantes ({emisiones}): "
                  "posibles votos insertados por fuera del sistema")
    if emisiones > votos:
        advertencias.append(
            f"Se emitieron {emisiones} tokens pero hay {votos} votos: un voto pudo interrumpirse "
            "o se borraron bloques del final de la cadena"
        )

    ancla = obtener_ancla(cur, eleccion_id)
    if integro and ancla:
        ultimo_hash = bloques[-1]["hash_actual"] if bloques else GENESIS
        if ancla.get("totalBloques") != len(bloques) or ancla.get("hashFinal") != ultimo_hash:
            integro, indice_falla = False, min(len(bloques), ancla.get("totalBloques", 0))
            motivo = "La cadena no coincide con el ancla registrada al cerrar la elección"

    return {
        "integro": integro,
        "totalBloques": len(bloques),
        "ultimaVerificacion": iso(ahora()),
        "indiceFalla": indice_falla,
        "motivo": motivo,
        "hashFinal": bloques[-1]["hash_actual"] if bloques else GENESIS,
        "consistencia": {"tokensEmitidos": emisiones, "votos": votos, "bloques": len(bloques)},
        "advertencias": advertencias,
        "anclaVerificada": bool(ancla) and integro,
    }
