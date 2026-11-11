from datetime import UTC, date, datetime
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import pytest

from farmared.consultas.q03 import q03_historial
from farmared.grafo import preparar_grafo
from farmared.proyeccion import sincronizar, verificar_proyeccion


pytestmark = pytest.mark.skipif(
    os.environ.get("FARMARED_TEST_SYNC") != "1",
    reason="Activar FARMARED_TEST_SYNC=1 para ambos motores aislados.",
)
RAIZ = Path(__file__).resolve().parents[2]
COLECCIONES = ("clientes", "sucursales", "farmaceuticos", "proveedores", "productos",
               "stock_lotes", "recetas", "ventas", "outbox")


def _fecha_json(valor):
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()
    raise TypeError(type(valor).__name__)


def test_q13_cli_outbox_sync_y_baja_con_historia(db_sync, mongo_config, driver, fuente, tmp_path):
    db = db_sync
    entorno = {**os.environ, "MONGO_URI": mongo_config.mongo_uri, "MONGO_DB": db.name,
               "NEO4J_PASSWORD": "", "PYTHONPATH": str(RAIZ / "src")}
    comandos, etapas = [], []
    lock = tmp_path / "sync.lock"

    def cli(*args, datos=None, esperado=0):
        resultado = subprocess.run(
            [sys.executable, "-m", "farmared", *args], cwd=RAIZ, env=entorno,
            input=json.dumps(datos) if datos is not None else None,
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        registro = dict(comando=["python", "-m", "farmared", *args], entrada=datos,
                        codigo=resultado.returncode, stderr=resultado.stderr.strip(),
                        salida=json.loads(resultado.stdout) if resultado.stdout.strip() else None)
        comandos.append(registro)
        assert resultado.returncode == esperado, registro
        return registro["salida"]

    def estado():
        with driver.session() as sesion:
            clientes = sesion.run(
                "MATCH (c:Cliente) RETURN properties(c) AS cliente ORDER BY c.id"
            ).data()
        return dict(mongo={c: list(db[c].find().sort("_id", 1)) for c in COLECCIONES},
                    neo4j_clientes=clientes, historial=q03_historial(driver, id_cliente) if id_cliente else [])

    def sincronizar_y_comprobar(eventos):
        resultado = sincronizar(db, driver, lock)
        assert resultado["procesados"] == len(eventos)
        assert set(resultado["eventos_procesados"]) == set(eventos)
        assert resultado["pendientes_observados"] == 0 and resultado["fallidos"] == []
        verificacion = verificar_proyeccion(db, driver, lock, confirmar_escrituras_pausadas=True)
        assert verificacion["equivalente"] and verificacion["diferencias"] == []
        return dict(sync=resultado, verificacion=verificacion)

    cli("preparar-mongo", "--base", db.name)
    indice = db.clientes.index_information()["uq_clientes_dni"]
    assert indice["unique"] and indice["key"] == [("dni", 1)]
    assert not indice.get("sparse", False) and "partialFilterExpression" not in indice
    preparar_grafo(driver)
    id_cliente = None
    inicial = estado()
    assert inicial["neo4j_clientes"] == []
    assert all(not documentos for documentos in inicial["mongo"].values())
    datos = json.loads((RAIZ / "docs/ejemplos/q13_alta_cliente.json").read_text(encoding="utf-8"))
    alta = cli("q13", "--base", db.name, "alta", "--datos", "-", datos=datos)
    id_cliente = alta["documento"]["_id"]
    antes_sync = estado()
    assert antes_sync["mongo"]["clientes"] == [alta["documento"]]
    assert antes_sync["neo4j_clientes"] == [] and alta["proyeccion"] == "pendiente_sync"
    assert len(alta["eventos"]) == 1
    assert antes_sync["mongo"]["outbox"][0]["procesado"] is False
    assert isinstance(antes_sync["mongo"]["outbox"][0]["creado_en"], datetime)
    sincronizacion = sincronizar_y_comprobar(alta["eventos"])
    despues_sync = estado()
    assert despues_sync["neo4j_clientes"] == [dict(cliente=dict(
        id=id_cliente, nombre=datos["nombre"], apellido=datos["apellido"], activo=True))]
    etapas.append(dict(accion="alta", antes=inicial, mongo_confirmado=antes_sync,
                       sincronizacion=sincronizacion, despues_sync=despues_sync))

    fuente["recetas"]["id_cliente"] = id_cliente
    fuente["ventas"]["id_cliente"] = id_cliente
    evento_historia = dict(_id=str(uuid4()), procesado=False, creado_en=datetime.now(UTC),
                          afectadas=[dict(coleccion="ventas", id=fuente["ventas"]["_id"])])
    with db.client.start_session() as sesion:
        with sesion.start_transaction():
            for coleccion, documento in fuente.items():
                if coleccion != "clientes":
                    db[coleccion].insert_one(documento, session=sesion)
            db.outbox.insert_one(evento_historia, session=sesion)
    historia_sync = sincronizar_y_comprobar([evento_historia["_id"]])
    con_historia = estado()
    assert len(con_historia["historial"]) == 2

    cambios = json.loads((RAIZ / "docs/ejemplos/q13_cambios_cliente.json").read_text(encoding="utf-8"))
    modificacion = cli("q13", "--base", db.name, "modificar", "--id-cliente", id_cliente,
                       "--datos", "-", datos=cambios)
    antes_sync = estado()
    assert antes_sync["mongo"]["clientes"] == [{**alta["documento"], **cambios}]
    assert antes_sync["neo4j_clientes"] == con_historia["neo4j_clientes"]
    sincronizacion = sincronizar_y_comprobar(modificacion["eventos"])
    despues_sync = estado()
    assert despues_sync["neo4j_clientes"] == con_historia["neo4j_clientes"]
    assert despues_sync["historial"] == con_historia["historial"]
    etapas.append(dict(accion="modificar", antes=con_historia, mongo_confirmado=antes_sync,
                       sincronizacion=sincronizacion, despues_sync=despues_sync))

    antes_rechazo = estado()
    assert cli("q13", "--base", db.name, "modificar", "--id-cliente", id_cliente,
               "--datos", "-", datos={"obra_social": "Sin cobertura"}, esperado=1) is None
    assert "VALIDACION" in comandos[-1]["stderr"]
    despues_rechazo = estado()
    assert despues_rechazo == antes_rechazo
    etapas.append(dict(accion="rechazo_cobertura_incoherente", antes=antes_rechazo,
                       despues=despues_rechazo, sin_cambios=True))

    baja = cli("q13", "--base", db.name, "baja", "--id-cliente", id_cliente)
    antes_sync = estado()
    assert antes_sync["mongo"]["clientes"] == [{**modificacion["documento"], "activo": False}]
    assert antes_sync["neo4j_clientes"][0]["cliente"]["activo"] is True
    sincronizacion = sincronizar_y_comprobar(baja["eventos"])
    despues_sync = estado()
    assert despues_sync["neo4j_clientes"][0]["cliente"]["activo"] is False
    for coleccion in COLECCIONES:
        if coleccion not in ("clientes", "outbox"):
            assert despues_sync["mongo"][coleccion] == con_historia["mongo"][coleccion]
    assert despues_sync["historial"] == con_historia["historial"]
    assert db.outbox.count_documents({"procesado": True}) == 4
    etapas.append(dict(accion="baja", antes=despues_rechazo, mongo_confirmado=antes_sync,
                       sincronizacion=sincronizacion, despues_sync=despues_sync))
    assert sincronizar(db, driver, lock)["procesados"] == 0
    with driver.session() as sesion:
        version_neo4j = sesion.run("CALL dbms.components() YIELD versions RETURN versions").single()["versions"]
    evidencia = dict(origen="fixture_sintetico_q13_no_dataset_oficial", base=db.name,
                     fecha=datetime.now(UTC), mongodb=db.client.server_info()["version"],
                     replica_set=db.client.admin.command("hello")["setName"], neo4j=version_neo4j,
                     indice_dni=indice, comandos=comandos, preparacion_historia=historia_sync,
                     etapas=etapas, eventos_q13=alta["eventos"] + modificacion["eventos"] + baja["eventos"])
    destino = os.environ.get("FARMARED_EVIDENCIAS_C")
    if destino:
        carpeta = Path(destino)
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / "q13_etapa7_recorrido.json").write_text(
            json.dumps(evidencia, ensure_ascii=False, indent=2, default=_fecha_json) + "\n", encoding="utf-8")
