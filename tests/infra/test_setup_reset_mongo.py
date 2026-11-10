"""Ciclo de demo en MongoDB real; solo bases UUID propias con prefijo de demo."""

import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from farmared.config import Config
from farmared.conexiones import obtener_mongo
from farmared.demo import resetear_demo_mongo

pytestmark = pytest.mark.skipif(
    not any(os.environ.get(k) == "1" for k in ("FARMARED_TEST_MONGO", "FARMARED_TEST_INTEGRACION")),
    reason="Activar FARMARED_TEST_MONGO=1 con replica set de prueba.",
)
RAIZ = Path(__file__).resolve().parents[2]


@pytest.fixture
def db():
    nombre = f"farmared_demo_test_a_{uuid4().hex}"
    database = obtener_mongo(replace(Config.from_env(), mongo_db=nombre))
    try:
        yield database
    finally:
        database.client.drop_database(nombre)
        database.client.close()


def ejecutar(*args):
    env = os.environ.copy()
    env["NEO4J_PASSWORD"] = ""
    return subprocess.run([sys.executable, "-m", "farmared", *args], env=env, capture_output=True, text=True)


def setup(db, *directorios):
    argumentos = ["setup", "--solo-mongo", "--base", db.name]
    for directorio in directorios:
        argumentos += ["--directorio", str(directorio)]
    r = ejecutar(*argumentos)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def snapshot(db):
    return {n: list(db[n].find().sort("_id", 1)) for n in db.list_collection_names()}


def test_setup_y_reset_explicito_sin_afectar_otra_base(db):
    fuentes = (RAIZ / "data/originales", RAIZ / "data/adicionales")
    primero = setup(db, *fuentes)
    assert primero["setup"] == "mongo_listo" and primero["alcance"] == "solo_mongo"
    assert sum(primero["conteos_iniciales"].values()) == 169
    assert primero["eventos_emitidos"] == db.outbox.count_documents({}) == 120
    assert primero["proyeccion"] == "no_comprobada" and len(primero["pendientes"]) == 3
    db.stock_lotes.update_one({"_id": "A-L002"}, {"$set": {"unidades": 2}})
    db.recetas.update_one({"_id": "A-RC001"}, {"$set": {"dispensas_realizadas": 2}})
    antes = snapshot(db)
    segundo = setup(db, *fuentes)
    assert segundo["reutilizada"] is True and segundo["eventos_emitidos"] == 0
    assert snapshot(db) == antes

    otro_nombre = f"farmared_test_a_guard_{uuid4().hex}"
    otro = db.client[otro_nombre]
    try:
        otro.fixture.insert_one({"_id": "preservar"})
        previo = ejecutar("reset-demo", "--solo-mongo", "--base", db.name)
        assert previo.returncode == 0, previo.stderr
        plan = json.loads(previo.stdout)
        assert plan["modo"] == "vista_previa" and plan["ejecutado"] is False
        assert plan["destino"]["base"] == db.name and plan["destino"]["servidores"]
        assert snapshot(db) == antes
        errado = ejecutar("reset-demo", "--solo-mongo", "--base", db.name, "--confirmar-base", "otra_base")
        assert errado.returncode == 1 and "VALIDACION" in errado.stderr
        assert snapshot(db) == antes
        confirmado = ejecutar("reset-demo", "--solo-mongo", "--base", db.name, "--confirmar-base", db.name)
        assert confirmado.returncode == 0, confirmado.stderr
        assert json.loads(confirmado.stdout)["ejecutado"] is True
        assert json.loads(confirmado.stderr)["reset_confirmado"]["base"] == db.name
        assert db.list_collection_names() == []
        assert otro.fixture.find_one({"_id": "preservar"}) == {"_id": "preservar"}
        # Reset y carga son pasos distintos. Solo esta base nueva se recarga.
        nuevo = setup(db, *fuentes)
        assert nuevo["reutilizada"] is False and nuevo["eventos_emitidos"] == 120
    finally:
        db.client.drop_database(otro_nombre)


def test_setup_fuente_distinta_no_reinicia(db):
    setup(db, RAIZ / "data/originales")
    antes = snapshot(db)
    r = ejecutar("setup", "--solo-mongo", "--base", db.name,
                 "--directorio", str(RAIZ / "data/originales"), "--directorio", str(RAIZ / "data/adicionales"))
    assert r.returncode == 1 and "CONFLICTO_ID" in r.stderr
    assert snapshot(db) == antes


def test_reset_confirmado_repetible_sobre_base_vacia(db):
    config = replace(Config.from_env(), mongo_db=db.name)
    uno = resetear_demo_mongo(config, confirmar_base=db.name)
    dos = resetear_demo_mongo(config, confirmar_base=db.name)
    assert uno["ejecutado"] is dos["ejecutado"] is True
    assert db.list_collection_names() == []
