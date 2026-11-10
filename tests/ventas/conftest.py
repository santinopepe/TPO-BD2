"""Fixtures de Persona B: base MongoDB aislada por test y escenario mínimo de venta.

Las pruebas que piden `db` se saltean salvo FARMARED_TEST_MONGO=1 o
FARMARED_TEST_INTEGRACION=1, con un replica set real (sin mocks).
"""

import os
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest

from farmared.clock import FixedClock, inicio_dia_utc
from farmared.config import Config

HOY = date(2026, 11, 10)
COLECCIONES = ("clientes", "sucursales", "farmaceuticos", "proveedores", "productos",
               "stock_lotes", "recetas", "ventas", "outbox")


@pytest.fixture
def hoy():
    return HOY


@pytest.fixture
def reloj():
    """Mediodía de HOY en Buenos Aires (15:00 UTC); explícito, nunca escondido."""
    return FixedClock(datetime(2026, 11, 10, 15, 0, tzinfo=UTC))


@pytest.fixture
def db():
    if not any(os.environ.get(k) == "1" for k in ("FARMARED_TEST_MONGO", "FARMARED_TEST_INTEGRACION")):
        pytest.skip("Activar FARMARED_TEST_MONGO=1 con replica set de prueba.")
    from farmared.conexiones import obtener_mongo
    from farmared.esquema.base_mongo import preparar_mongo_base

    nombre = f"farmared_test_b_ventas_{uuid4().hex}"
    database = obtener_mongo(replace(Config.from_env(), mongo_db=nombre))
    try:
        preparar_mongo_base(database)
        yield database
    finally:
        database.client.drop_database(nombre)
        database.client.close()


def _dia(delta: int) -> datetime:
    return inicio_dia_utc(HOY + timedelta(days=delta))


def _cliente(id, dni, activo=True, obra_social="OSDE"):
    return {"_id": id, "nombre": "Nombre " + id, "apellido": "Apellido", "dni": dni,
            "email": None, "telefono": None, "ciudad": "CABA", "provincia": "Buenos Aires",
            "obra_social": obra_social,
            "nro_afiliado": None if obra_social == "Sin cobertura" else "AF-" + id, "activo": activo}


def _sucursal(id, tipo="Farmacia", activo=True):
    return {"_id": id, "nombre": "Sucursal " + id, "tipo": tipo, "direccion": "Calle 123",
            "ciudad": "CABA", "provincia": "Buenos Aires", "telefono": None, "activo": activo}


def _farmaceutico(id, matricula, id_sucursal, activo=True):
    return {"_id": id, "nombre": "Farma", "apellido": id, "matricula": matricula,
            "cargo": "Farmacéutico", "id_sucursal": id_sucursal, "activo": activo}


def _producto(id, condicion, precio, activo=True):
    return {"_id": id, "nombre": "Producto " + id, "principio_activo": None, "categoria": "Test",
            "presentacion": "Caja", "condicion_venta": condicion, "precio_unit": precio,
            "id_proveedor": "B-PRV001", "activo": activo}


def _lote(id, producto, sucursal, unidades, dias):
    return {"_id": id, "id_producto": producto, "id_sucursal": sucursal,
            "nro_lote": "N-" + id, "unidades": unidades, "vencimiento": _dia(dias)}


def _receta(id, cliente, tipo, autorizadas, realizadas, estado="Vigente", proxima=None):
    return {"_id": id, "id_cliente": cliente, "medico": "Dra. Test", "matricula_medico": "MP-1",
            "fecha_emision": _dia(-40), "tipo": tipo, "dispensas_autorizadas": autorizadas,
            "dispensas_realizadas": realizadas, "proxima_dispensa": proxima, "estado": estado}


def documentos_escenario() -> dict[str, list[dict]]:
    """Escenario B con casos borde; todos los documentos cumplen el validador de A."""
    return {
        "clientes": [
            _cliente("B-C001", "90000001"),
            _cliente("B-C002", "90000002", obra_social="Sin cobertura"),
            _cliente("B-C003", "90000003", activo=False),
        ],
        "sucursales": [
            _sucursal("B-S001"),
            _sucursal("B-S002", tipo="Droguería"),
            _sucursal("B-S003", activo=False),
        ],
        "farmaceuticos": [
            _farmaceutico("B-F001", "MN-B1", "B-S001"),
            _farmaceutico("B-F002", "MN-B2", "B-S001", activo=False),
            _farmaceutico("B-F003", "MN-B3", "B-S002"),
            _farmaceutico("B-F004", "MN-B4", "B-S003"),
        ],
        "proveedores": [{"_id": "B-PRV001", "razon_social": "Lab B", "cuit": "30-00000000-1",
                         "tipo": "Laboratorio", "ciudad": "CABA", "provincia": "Buenos Aires",
                         "telefono": None, "activo": True}],
        "productos": [
            _producto("B-P001", "Venta libre", 2800),
            _producto("B-P002", "Venta libre", 3500),
            _producto("B-P003", "Bajo receta", 4000),
            _producto("B-P004", "Bajo receta archivada", 9000),
            _producto("B-P005", "Venta libre", 1000, activo=False),
        ],
        "stock_lotes": [
            _lote("B-L001", "B-P001", "B-S001", 4, 10),
            _lote("B-L002", "B-P001", "B-S001", 10, 30),
            _lote("B-L003", "B-P001", "B-S001", 100, -1),   # vencido
            _lote("B-L004", "B-P002", "B-S001", 5, 60),
            _lote("B-L005", "B-P003", "B-S001", 20, 90),
            _lote("B-L006", "B-P004", "B-S001", 3, 0),      # vence hoy: dispensable
            _lote("B-L007", "B-P001", "B-S002", 50, 30),    # droguería
            _lote("B-L008", "B-P002", "B-S001", 0, 5),      # vacío
        ],
        "recetas": [
            _receta("B-RC001", "B-C001", "Tratamiento prolongado", 3, 1, proxima=_dia(-10)),
            _receta("B-RC002", "B-C001", "Simple", 1, 0),
            _receta("B-RC003", "B-C002", "Simple", 1, 0),
            _receta("B-RC004", "B-C001", "Simple", 1, 1, estado="Completada"),
        ],
    }


@pytest.fixture
def escenario(db):
    documentos = documentos_escenario()
    for coleccion, docs in documentos.items():
        db[coleccion].insert_many(docs)
    return documentos


@pytest.fixture
def estado_db(db):
    """Foto completa de las nueve colecciones, para afirmar «nada cambió»."""
    def tomar():
        return {c: list(db[c].find({}).sort("_id", 1)) for c in COLECCIONES}
    return tomar
