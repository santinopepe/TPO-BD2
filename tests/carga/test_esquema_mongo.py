"""Integración del esquema sobre MongoDB real; cada prueba usa su propia base."""

import os
import json
import subprocess
import sys
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from bson import Int64, json_util
from pymongo.errors import DuplicateKeyError, WriteError

from farmared.config import Config
from farmared.conexiones import obtener_mongo
from farmared.errores import ErrorDominio
from farmared.esquema.base_mongo import INDICES, VALIDADORES, preparar_mongo_base

pytestmark = pytest.mark.skipif(
    not any(os.environ.get(k) == "1" for k in ("FARMARED_TEST_MONGO", "FARMARED_TEST_INTEGRACION")),
    reason="Activar FARMARED_TEST_MONGO=1 con MongoDB replica set de prueba.",
)


@pytest.fixture
def db():
    nombre = f"farmared_test_a_esquema_{uuid4().hex}"
    database = obtener_mongo(replace(Config.from_env(), mongo_db=nombre))
    try:
        yield database
    finally:
        database.client.drop_database(nombre)
        database.client.close()


@pytest.fixture
def documentos():
    ruta = Path(__file__).resolve().parents[2] / "docs/ejemplos/documentos_mongo.json"
    return json_util.loads(ruta.read_text())


def _catalogo(db):
    return {
        info["name"]: {"options": info.get("options", {}), "indices": db[info["name"]].index_information()}
        for info in db.list_collections()
    }


def test_ejemplos_idempotencia_y_preservacion_operacional(db, documentos):
    preparar_mongo_base(db)
    assert set(db.list_collection_names()) == set(VALIDADORES)
    for nombre, doc in documentos.items():
        db[nombre].insert_one(doc)
    db.stock_lotes.update_one({}, {"$set": {"unidades": 4}})
    db.recetas.update_one({}, {"$set": {"dispensas_realizadas": 1, "estado": "Completada"}})
    db.clientes.update_one({}, {"$set": {"activo": False}})
    db.outbox.update_one({}, {"$set": {"procesado": True, "intentos": 2}})
    db.ventas.create_index([("estado", 1)], name="indice_otro_frente")
    db.clientes.create_index("dni", name="otro_indice_misma_clave", unique=False)
    db.create_collection("coleccion_otro_frente")
    antes = {nombre: list(db[nombre].find()) for nombre in db.list_collection_names()}
    catalogo = _catalogo(db)
    preparar_mongo_base(db)
    assert _catalogo(db) == catalogo
    assert {nombre: list(db[nombre].find()) for nombre in db.list_collection_names()} == antes
    for nombre, validador in VALIDADORES.items():
        opciones = catalogo[nombre]["options"]
        assert opciones["validator"] == validador
        assert opciones["validationLevel"] == "strict"
        assert opciones["validationAction"] == "error"
    for nombre, modelos in INDICES.items():
        for modelo in modelos:
            assert modelo.document["name"] in catalogo[nombre]["indices"]


@pytest.mark.parametrize("coleccion,campo,valor", [
    ("clientes", "_id", 123), ("clientes", "dni", 123),
    ("clientes", "telefono", 123), ("clientes", "activo", "True"),
    ("clientes", "nombre", ""), ("clientes", "obra_social", "No acordada"),
    ("farmaceuticos", "cargo", "Vendedor"), ("proveedores", "cuit", 30000000000),
    ("sucursales", "tipo", "Local"), ("productos", "precio_unit", 10.0),
    ("productos", "precio_unit", True), ("productos", "precio_unit", -1),
    ("productos", "condicion_venta", "Libre"), ("stock_lotes", "unidades", -1),
    ("stock_lotes", "vencimiento", "2027-01-01"),
    ("recetas", "dispensas_autorizadas", 4), ("recetas", "dispensas_realizadas", -1),
    ("recetas", "proxima_dispensa", "2026-11-10"), ("recetas", "estado", "Activa"),
    ("ventas", "total", 1.0), ("ventas", "estado", "Pagada"),
    ("ventas", "medio_pago", "Cheque"), ("ventas", "origen", "inventado"),
    ("ventas", "stock_aplicado", 1), ("ventas", "items", []),
    ("ventas", "items", None), ("ventas", "items", [1]),
    ("outbox", "afectadas", []), ("outbox", "creado_en", "2026-11-09T15:30:00Z"),
    ("outbox", "afectadas", [{"coleccion": "stock_lotes", "id": "A-EJ-L001"}]),
])
def test_rechaza_tipos_rangos_y_enums(db, documentos, coleccion, campo, valor):
    preparar_mongo_base(db)
    documento = documentos[coleccion]
    documento[campo] = valor
    with pytest.raises(WriteError) as exc:
        db[coleccion].insert_one(documento)
    assert exc.value.code == 121
    assert db[coleccion].count_documents({}) == 0


@pytest.mark.parametrize("coleccion", list(VALIDADORES))
def test_campos_requeridos(db, documentos, coleccion):
    preparar_mongo_base(db)
    documento = documentos[coleccion]
    # _id no se prueba aquí porque PyMongo lo genera si se omite.
    campo = next(k for k in documento if k != "_id")
    del documento[campo]
    with pytest.raises(WriteError) as exc:
        db[coleccion].insert_one(documento)
    assert exc.value.code == 121


@pytest.mark.parametrize("campo,valor", [
    ("cantidad", 0), ("cantidad", 1.5), ("precio_unit", 1.0),
    ("subtotal", -1), ("asignaciones_lotes", [{"id_lote": "A-L1", "cantidad": 0}]),
])
def test_valida_detalle_embebido(db, documentos, campo, valor):
    preparar_mongo_base(db)
    documento = documentos["ventas"]
    documento["items"][0][campo] = valor
    with pytest.raises(WriteError) as exc:
        db.ventas.insert_one(documento)
    assert exc.value.code == 121


def test_detalles_unicos_por_venta_y_producto_repetible(db, documentos):
    preparar_mongo_base(db)
    venta = documentos["ventas"]
    segunda = deepcopy(venta["items"][0])
    segunda["id_detalle"] = "A-EJ-D002"
    venta["items"].append(segunda)
    venta["total"] = 2000
    db.ventas.insert_one(venta)  # Mismo producto en dos líneas es válido.
    with pytest.raises(WriteError) as exc:
        db.ventas.update_one({"_id": venta["_id"]}, {"$set": {"items.1.id_detalle": "A-EJ-D001"}})
    assert exc.value.code == 121
    assert db.ventas.find_one()["items"][1]["id_detalle"] == "A-EJ-D002"
    otra = deepcopy(venta)
    otra["_id"] = "A-EJ-V002"
    db.ventas.insert_one(otra)  # El detalle no es único global en la persistencia.


@pytest.mark.parametrize("coleccion,campo", [("clientes", "dni"), ("farmaceuticos", "matricula")])
def test_unicidad_global_incluye_inactivos(db, documentos, coleccion, campo):
    preparar_mongo_base(db)
    uno = documentos[coleccion]
    uno["activo"] = False
    db[coleccion].insert_one(uno)
    otro = deepcopy(uno)
    otro["_id"] += "-OTRO"
    otro["activo"] = True
    with pytest.raises(DuplicateKeyError) as exc:
        db[coleccion].insert_one(otro)
    assert exc.value.code == 11000
    assert db[coleccion].count_documents({campo: uno[campo]}) == 1


def test_int64_nulos_y_numero_lote_no_unico(db, documentos):
    preparar_mongo_base(db)
    producto = documentos["productos"]
    producto["precio_unit"] = Int64(2**63 - 1)
    db.productos.insert_one(producto)
    assert db.productos.find_one()["precio_unit"] == 2**63 - 1
    lote = documentos["stock_lotes"]
    db.stock_lotes.insert_one(lote)
    otro = deepcopy(lote)
    otro.update({"_id": "A-EJ-L002", "id_sucursal": "A-EJ-S002", "unidades": 0})
    db.stock_lotes.insert_one(otro)
    assert db.stock_lotes.count_documents({"nro_lote": lote["nro_lote"]}) == 2


def test_no_es_clave_foranea_ni_regla_entre_campos(db, documentos):
    preparar_mongo_base(db)
    venta = documentos["ventas"]
    # Tipos válidos: la carga/servicios deberán rechazar estos valores por negocio.
    venta["id_cliente"] = "A-NO-EXISTE"
    venta["total"] = 999
    db.ventas.insert_one(venta)
    assert db.ventas.count_documents({}) == 1


def test_adopta_coleccion_valida_sin_validador_y_respeta_indice_equivalente(db, documentos):
    db.clientes.insert_one(documentos["clientes"])
    db.clientes.create_index("dni", unique=True, name="dni_preexistente")
    preparar_mongo_base(db)
    assert db.clientes.count_documents({}) == 1
    assert "dni_preexistente" in db.clientes.index_information()
    assert "uq_clientes_dni" not in db.clientes.index_information()
    assert db.clientes.options()["validationLevel"] == "strict"


def test_preflight_rechaza_datos_invalidos_antes_de_crear_otras_colecciones(db):
    db.productos.insert_one({"_id": "A-INVALIDO", "precio_unit": 2.0})
    antes = _catalogo(db)
    with pytest.raises(ErrorDominio, match="documentos que incumplen"):
        preparar_mongo_base(db)
    assert _catalogo(db) == antes
    assert db.productos.find_one()["precio_unit"] == 2.0


def test_preflight_rechaza_duplicados_sin_corregirlos(db, documentos):
    uno = documentos["clientes"]
    otro = deepcopy(uno)
    otro["_id"] += "-OTRO"
    db.clientes.insert_many([uno, otro])
    antes = _catalogo(db)
    with pytest.raises(ErrorDominio, match="duplicados en dni"):
        preparar_mongo_base(db)
    assert _catalogo(db) == antes
    assert db.clientes.count_documents({}) == 2


@pytest.mark.parametrize("situacion", ["validador", "indice", "vista"])
def test_no_reemplaza_definiciones_incompatibles(db, situacion):
    if situacion == "validador":
        db.create_collection("clientes", validator={"dni": {"$type": "string"}})
    elif situacion == "indice":
        db.clientes.create_index("dni", name="uq_clientes_dni", unique=False)
    else:
        db.create_collection("fuente_vista")
        db.command("create", "clientes", viewOn="fuente_vista", pipeline=[])
    antes = {info["name"]: info.get("options", {}) for info in db.list_collections()}
    with pytest.raises(ErrorDominio):
        preparar_mongo_base(db)
    assert {info["name"]: info.get("options", {}) for info in db.list_collections()} == antes


def test_cli_real_sin_neo4j_e_informa_conflicto_sin_exito(db):
    env = os.environ.copy()
    env["NEO4J_PASSWORD"] = ""
    comando = [sys.executable, "-m", "farmared", "preparar-mongo", "--base", db.name]
    resultado = subprocess.run(comando, env=env, capture_output=True, text=True)
    assert resultado.returncode == 0, resultado.stderr
    assert json.loads(resultado.stdout)["base"] == db.name
    assert json.loads(resultado.stdout)["esquema"] == "listo"
    assert all(db[n].count_documents({}) == 0 for n in VALIDADORES)
    # Simula datos heredados que el motor recibió con bypass administrativo.
    db.productos.insert_one({"_id": "A-LEGADO-INVALIDO"}, bypass_document_validation=True)
    resultado = subprocess.run(comando, env=env, capture_output=True, text=True)
    assert resultado.returncode == 1
    assert resultado.stdout == ""
    assert "INTEGRIDAD" in resultado.stderr
    assert db.productos.count_documents({}) == 1
