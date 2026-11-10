"""Persistencia y transacciones sobre replica set real, en bases exclusivas."""

import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from threading import Barrier, Lock, get_ident
from uuid import uuid4

import pytest
from pymongo.synchronous.collection import Collection
from pymongo.synchronous.client_session import ClientSession
from pymongo.errors import OperationFailure

from farmared.carga import mongo as loader
from farmared.carga.adicionales import generar_adicionales
from farmared.carga.modelos import ErrorDatasets
from farmared.carga.validacion import rutas_desde_directorios
from farmared.clock import FixedClock
from farmared.config import Config
from farmared.conexiones import obtener_mongo
from farmared.errores import ErrorDominio
from farmared.esquema.base_mongo import preparar_mongo_base
from farmared.esquema.manifiestos import COLECCION_MANIFIESTOS, ID_MANIFIESTO, preparar_manifiestos

pytestmark = pytest.mark.skipif(
    not any(os.environ.get(k) == "1" for k in ("FARMARED_TEST_MONGO", "FARMARED_TEST_INTEGRACION")),
    reason="Activar FARMARED_TEST_MONGO=1 con replica set de prueba.",
)
ORIGINALES = Path(__file__).resolve().parents[2] / "data/originales"
RUTAS = rutas_desde_directorios(ORIGINALES)


@pytest.fixture
def db():
    nombre = f"farmared_test_a_loader_{uuid4().hex}"
    database = obtener_mongo(replace(Config.from_env(), mongo_db=nombre))
    try:
        yield database
    finally:
        database.client.drop_database(nombre)
        database.client.close()


def snapshot(db):
    return {n: list(db[n].find().sort("_id", 1)) for n in db.list_collection_names()}


def test_carga_completa_y_segunda_carga_preserva_operaciones(db, monkeypatch):
    instante = datetime(2026, 11, 10, 1, 30, tzinfo=UTC)  # Día comercial 9/11.
    monkeypatch.setattr(loader, "SystemClock", lambda: FixedClock(instante))
    primera = loader.cargar_mongo(db, RUTAS)
    m = primera["documento"]
    assert primera["reutilizada"] is False and len(primera["eventos"]) == 58
    assert sum(m["conteos"].values()) == 81
    assert m["base_date"] == datetime(2026, 11, 9, 3, tzinfo=UTC)
    assert db[COLECCION_MANIFIESTOS].count_documents({}) == 1
    assert db[COLECCION_MANIFIESTOS].find_one({"_id": ID_MANIFIESTO}) == m
    assert db.outbox.count_documents({"procesado": False}) == 58
    for coleccion, cantidad in m["conteos"].items():
        assert db[coleccion].count_documents({}) == cantidad
    assert db.ventas.find_one({"_id": "V001"})["items"][0]["precio_unit"] == 3850
    assert db.stock_lotes.find_one({"_id": "L001"})["unidades"] == 120
    assert db.recetas.find_one({"_id": "RC002"})["dispensas_realizadas"] == 2
    assert all(e["creado_en"] == instante for e in db.outbox.find())
    assert len(m["avisos"]) == 3
    # Cambios de fixtures operacionales, sin simular q13/q14/q15 como implementados.
    db.stock_lotes.update_one({"_id": "L001"}, {"$set": {"unidades": 113}})
    db.recetas.update_one({"_id": "RC002"}, {"$set": {
        "dispensas_realizadas": 3, "estado": "Completada", "proxima_dispensa": None,
    }})
    db.clientes.update_one({"_id": "C001"}, {"$set": {"activo": False, "email": "operacional@example.test"}})
    db.outbox.update_one({"_id": primera["eventos"][0]}, {"$set": {"procesado": True, "intentos": 2}})
    nuevo = deepcopy(db.clientes.find_one({"_id": "C002"}))
    nuevo.update({"_id": "A-OPERACIONAL-C", "dni": "99999999"})
    nuevo.pop("importacion")
    db.clientes.insert_one(nuevo)
    antes = snapshot(db)
    monkeypatch.setattr(loader, "SystemClock", lambda: FixedClock(datetime(2030, 1, 1, 15, tzinfo=UTC)))
    segunda = loader.cargar_mongo(db, RUTAS)
    assert segunda["reutilizada"] is True and segunda["eventos"] == []
    assert snapshot(db) == antes
    assert segunda["documento"]["base_date"] == m["base_date"]
    assert segunda["documento"]["creado_en"] == instante


def test_fuente_cambiada_conflicto_sin_sobrescritura(db, tmp_path):
    loader.cargar_mongo(db, RUTAS)
    antes = snapshot(db)
    copia = shutil.copytree(ORIGINALES, tmp_path / "fuente")
    assert loader.cargar_mongo(db, rutas_desde_directorios(copia))["reutilizada"] is True
    assert snapshot(db) == antes
    with (copia / "clientes.csv").open("ab") as f:
        f.write(b"\n")
    with pytest.raises(ErrorDominio) as exc:
        loader.cargar_mongo(db, rutas_desde_directorios(copia))
    assert exc.value.codigo == "CONFLICTO_ID"
    assert snapshot(db) == antes


def test_invalidos_no_crean_catalogo(db, tmp_path):
    with pytest.raises(ErrorDatasets):
        loader.cargar_mongo(db, rutas_desde_directorios(tmp_path))
    assert db.list_collection_names() == []


@pytest.mark.parametrize("coleccion", ["clientes", "outbox"])
def test_no_adopta_base_poblada_sin_manifiesto(db, coleccion):
    preparar_mongo_base(db)
    from bson import json_util
    raiz = Path(__file__).resolve().parents[2]
    docs = json_util.loads((raiz / "docs/ejemplos/documentos_mongo.json").read_text())
    db[coleccion].insert_one(docs[coleccion])
    previo = db[coleccion].find_one()
    with pytest.raises(ErrorDominio) as exc:
        loader.cargar_mongo(db, RUTAS)
    assert exc.value.codigo == "CONFLICTO_ID"
    assert db[coleccion].find_one() == previo
    assert db[COLECCION_MANIFIESTOS].count_documents({}) == 0


@pytest.mark.parametrize("coleccion", ["stock_lotes", "outbox"])
def test_no_repara_carga_danada_desde_csv(db, coleccion):
    loader.cargar_mongo(db, RUTAS)
    identificador = db[coleccion].find_one()["_id"]
    db[coleccion].delete_one({"_id": identificador})  # Corrupción administrativa solo del fixture.
    antes = snapshot(db)
    with pytest.raises(ErrorDominio) as exc:
        loader.cargar_mongo(db, RUTAS)
    assert exc.value.codigo == "INTEGRIDAD"
    assert snapshot(db) == antes


@pytest.mark.parametrize("campo,valor,codigo", [
    ("version_carga", 2, "CONFLICTO_ID"), ("estado", "incompleta", "INTEGRIDAD"),
    ("fuentes.0.sha256", "0" * 64, "INTEGRIDAD"),
])
def test_manifiesto_incompatible_o_danado_no_anuncia_exito(db, campo, valor, codigo):
    loader.cargar_mongo(db, RUTAS)
    db[COLECCION_MANIFIESTOS].update_one(
        {"_id": ID_MANIFIESTO}, {"$set": {campo: valor}}, bypass_document_validation=True,
    )
    antes = snapshot(db)
    with pytest.raises(ErrorDominio) as exc:
        loader.cargar_mongo(db, RUTAS)
    assert exc.value.codigo == codigo
    assert snapshot(db) == antes


def test_manifiesto_sin_campo_requerido_no_se_reutiliza(db):
    loader.cargar_mongo(db, RUTAS)
    db[COLECCION_MANIFIESTOS].update_one(
        {"_id": ID_MANIFIESTO}, {"$unset": {"avisos": ""}}, bypass_document_validation=True,
    )
    antes = snapshot(db)
    with pytest.raises(ErrorDominio) as exc:
        loader.cargar_mongo(db, RUTAS)
    assert exc.value.codigo == "INTEGRIDAD"
    assert snapshot(db) == antes


def test_commit_real_con_respuesta_perdida_inyectada(db, monkeypatch):
    original = ClientSession.commit_transaction
    commits = []

    def perder_primera_respuesta(sesion):
        original(sesion)  # El motor confirma de verdad antes de simular pérdida de ACK.
        if sesion.client is db.client:
            commits.append(sesion.session_id)
            if len(commits) == 1:
                raise OperationFailure("ACK perdido: fallo inyectado", code=91,
                                       details={"errorLabels": ["UnknownTransactionCommitResult"]})

    monkeypatch.setattr(ClientSession, "commit_transaction", perder_primera_respuesta)
    resultado = loader.cargar_mongo(db, RUTAS)
    assert len(commits) >= 2
    assert resultado["reutilizada"] is False
    assert db[COLECCION_MANIFIESTOS].count_documents({}) == 1
    assert db.outbox.count_documents({}) == 58
    assert db.ventas.count_documents({}) == 16
    assert loader.cargar_mongo(db, RUTAS)["reutilizada"] is True


@pytest.mark.parametrize("punto", ["ventas", "outbox"])
def test_falla_inyectada_rollback_real_y_reintento(db, monkeypatch, punto):
    original = Collection.insert_many

    def fallar(self, documentos, *args, **kwargs):
        if self.database.name == db.name and self.name == punto:
            raise RuntimeError("Interrupción inyectada antes del commit")
        return original(self, documentos, *args, **kwargs)

    with monkeypatch.context() as m:
        m.setattr(Collection, "insert_many", fallar)
        with pytest.raises(RuntimeError, match="Interrupción inyectada"):
            loader.cargar_mongo(db, RUTAS)
    assert all(db[n].count_documents({}) == 0 for n in db.list_collection_names())
    recuperada = loader.cargar_mongo(db, RUTAS)
    assert recuperada["reutilizada"] is False
    assert len(recuperada["eventos"]) == db.outbox.count_documents({}) == 58


def test_dos_seeds_con_snapshots_simultaneos(db, monkeypatch):
    preparar_mongo_base(db)
    preparar_manifiestos(db)
    barrera, lock = Barrier(2, timeout=15), Lock()
    vistos, sesiones = set(), []
    original = loader._buscar_manifiesto

    def coordinar(database, sesion):
        encontrado = original(database, sesion)
        esperar = False
        with lock:
            hilo = get_ident()
            if encontrado is None and hilo not in vistos:
                vistos.add(hilo)
                sesiones.append(sesion.session_id)
                esperar = True
        if esperar:
            barrera.wait()  # Ambos ya leyeron ausencia en snapshots distintos.
        return encontrado

    monkeypatch.setattr(loader, "_buscar_manifiesto", coordinar)

    def intentar():
        independiente = obtener_mongo(replace(Config.from_env(), mongo_db=db.name))
        try:
            return loader.cargar_mongo(independiente, RUTAS)
        finally:
            independiente.client.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        tareas = [pool.submit(intentar), pool.submit(intentar)]
        resultados = [t.result(timeout=45) for t in tareas]
    assert len(sesiones) == 2 and sesiones[0] != sesiones[1]
    assert sorted(r["reutilizada"] for r in resultados) == [False, True]
    assert db[COLECCION_MANIFIESTOS].count_documents({}) == 1
    assert db.outbox.count_documents({}) == 58
    assert db.ventas.count_documents({}) == 16


def test_cli_seed_sin_neo4j_y_reintento(db):
    env = os.environ.copy()
    env["NEO4J_PASSWORD"] = ""
    comando = [sys.executable, "-m", "farmared", "seed", "--base", db.name, "--directorio", str(ORIGINALES)]
    primera = subprocess.run(comando, env=env, capture_output=True, text=True)
    assert primera.returncode == 0, primera.stderr
    resultado = json.loads(primera.stdout)
    assert resultado["eventos_emitidos"] == 58 and resultado["reutilizada"] is False
    assert resultado["proyeccion"] == "no_comprobada"
    segunda = subprocess.run(comando, env=env, capture_output=True, text=True)
    assert segunda.returncode == 0, segunda.stderr
    assert json.loads(segunda.stdout)["reutilizada"] is True
    assert json.loads(segunda.stdout)["eventos_emitidos"] == 0


def test_adicionales_fecha_persistida_minimos_y_repeticion(db, tmp_path, monkeypatch):
    adicionales = tmp_path / "adicionales"
    generar_adicionales(adicionales, ORIGINALES, base_date=date(2026, 11, 10))
    rutas = rutas_desde_directorios(ORIGINALES, adicionales)
    instante = datetime(2030, 1, 1, 12, tzinfo=UTC)
    monkeypatch.setattr(loader, "SystemClock", lambda: FixedClock(instante))
    primera = loader.cargar_mongo(db, rutas)
    m = primera["documento"]
    base = datetime(2026, 11, 10, 3, tzinfo=UTC)
    assert m["base_date"] == m["generaciones"][0]["base_date"] == base
    assert m["creado_en"] == instante  # El seed no vuelve a usar hoy para los casos.
    assert sum(m["conteos"].values()) == 169
    assert len(primera["eventos"]) == db.outbox.count_documents({}) == 120
    for coleccion, cantidad in m["conteos"].items():
        assert db[coleccion].count_documents({}) == cantidad
        assert db[coleccion].count_documents({"_id": {"$regex": "^A-"}}) >= 10
    assert sum(len(v["items"]) for v in db.ventas.find({"_id": {"$regex": "^A-"}})) == 16
    assert db.stock_lotes.find_one({"_id": "A-L002"})["vencimiento"] == base
    assert db.recetas.find_one({"_id": "A-RC001"})["dispensas_realizadas"] == 1
    assert db.ventas.find_one({"_id": "A-V001"})["items"][0]["asignaciones_lotes"] is None
    for id_venta in ("A-V005", "A-V006"):
        venta = db.ventas.find_one({"_id": id_venta})
        assert venta["stock_aplicado"] is venta["receta_aplicada"] is False
        assert all(i["asignaciones_lotes"] == [] for i in venta["items"])
    # Fixtures operacionales: los servicios B/C/D continúan fuera de alcance.
    db.stock_lotes.update_one({"_id": "A-L002"}, {"$set": {"unidades": 2}})
    db.recetas.update_one({"_id": "A-RC001"}, {"$set": {"dispensas_realizadas": 2}})
    db.outbox.update_one({"_id": primera["eventos"][0]}, {"$set": {"procesado": True}})
    antes = snapshot(db)
    monkeypatch.setattr(loader, "SystemClock", lambda: FixedClock(datetime(2035, 1, 1, 12, tzinfo=UTC)))
    segunda = loader.cargar_mongo(db, rutas)
    assert segunda["reutilizada"] is True and segunda["eventos"] == []
    assert segunda["documento"]["base_date"] == base
    assert snapshot(db) == antes


def test_otra_generacion_no_migra_ni_reemplaza_destino(db, tmp_path):
    uno, dos = tmp_path / "uno", tmp_path / "dos"
    generar_adicionales(uno, ORIGINALES, base_date=date(2026, 11, 10))
    generar_adicionales(dos, ORIGINALES, base_date=date(2026, 11, 11))
    loader.cargar_mongo(db, rutas_desde_directorios(ORIGINALES, uno))
    antes = snapshot(db)
    with pytest.raises(ErrorDominio) as exc:
        loader.cargar_mongo(db, rutas_desde_directorios(ORIGINALES, dos))
    assert exc.value.codigo == "CONFLICTO_ID"
    assert snapshot(db) == antes


@pytest.mark.parametrize("campo,valor", [
    ("generaciones.0.base_date", "2026-11-10"),
    ("generaciones.0.sha256", "0" * 64),
    ("base_date", datetime(2026, 11, 11, 3, tzinfo=UTC)),
])
def test_manifiesto_generado_danado_no_se_reutiliza(db, tmp_path, campo, valor):
    adicionales = tmp_path / "adicionales"
    generar_adicionales(adicionales, ORIGINALES, base_date=date(2026, 11, 10))
    rutas = rutas_desde_directorios(ORIGINALES, adicionales)
    loader.cargar_mongo(db, rutas)
    db[COLECCION_MANIFIESTOS].update_one(
        {"_id": ID_MANIFIESTO}, {"$set": {campo: valor}}, bypass_document_validation=True,
    )
    antes = snapshot(db)
    with pytest.raises(ErrorDominio) as exc:
        loader.cargar_mongo(db, rutas)
    assert exc.value.codigo == "INTEGRIDAD"
    assert snapshot(db) == antes
