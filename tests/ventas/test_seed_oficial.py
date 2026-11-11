"""q14/q15 sobre el seed oficial de A (originales + adicionales), sin reproducir historia.

Datos relevantes de los CSV:
- V011: Pendiente, C007 con RC006 (Simple, Vigente, 0/1), F006 → S004, 1 × PRD007 a 4800.
  S004 tiene L014 (PRD007, 45 u., vence 2027-04-30): se puede completar.
- V012: Pendiente, F005 → S003, PRD002 y PRD011. No hay lotes de esos productos en
  S003: q15 la rechaza por stock, sin cambios.
- V003: Completada histórica (stock incorporado al corte): q15 la reconoce sin tocar stock.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from farmared.carga.mongo import cargar_mongo
from farmared.carga.validacion import rutas_desde_directorios
from farmared.consultas.q14 import q14_registrar_venta
from farmared.consultas.q15 import q15_actualizar_stock
from farmared.errores import ErrorDominio

RAIZ = Path(__file__).resolve().parents[2]
RUTAS = rutas_desde_directorios(RAIZ / "data/originales", RAIZ / "data/adicionales")


@pytest.fixture
def seed(db):
    return cargar_mongo(db, RUTAS)


def unidades(db, id_lote):
    return db.stock_lotes.find_one({"_id": id_lote})["unidades"]


def test_q15_completa_v011_con_receta_simple(db, seed, reloj):
    resultado = q15_actualizar_stock(db, "V011", reloj)

    venta = resultado["documento"]
    assert (venta["estado"], venta["tipo"], venta["total"]) == ("Completada", "Con receta", 4800)
    assert venta["fecha"] == datetime(2026, 11, 10, 3, 0, tzinfo=UTC)
    assert venta["fecha_creacion_pendiente"] == datetime(2026, 10, 12, 3, 0, tzinfo=UTC)
    assert venta["items"][0]["asignaciones_lotes"] == [{"id_lote": "L014", "cantidad": 1}]
    assert unidades(db, "L014") == 44
    receta = db.recetas.find_one({"_id": "RC006"})
    assert (receta["dispensas_realizadas"], receta["estado"], receta["proxima_dispensa"]) == (1, "Completada", None)


def test_q15_rechaza_v012_por_falta_de_lotes_en_su_sucursal(db, seed, reloj):
    antes = db.ventas.find_one({"_id": "V012"})
    with pytest.raises(ErrorDominio) as exc:
        q15_actualizar_stock(db, "V012", reloj)
    assert exc.value.codigo == "STOCK_INSUFICIENTE"
    assert "S003" in exc.value.mensaje
    assert db.ventas.find_one({"_id": "V012"}) == antes


def test_q15_reconoce_completada_historica_sin_descontar(db, seed, reloj):
    lotes_antes = list(db.stock_lotes.find({}).sort("_id", 1))
    resultado = q15_actualizar_stock(db, "V003", reloj)
    assert resultado["reutilizada"] is True
    assert list(db.stock_lotes.find({}).sort("_id", 1)) == lotes_antes


def test_q14_sobre_datos_oficiales_y_reseed_no_repone_stock(db, seed, reloj):
    q14_registrar_venta(db, {"id_venta": "B-VS1", "id_cliente": "C001", "id_farmaceutico": "F001",
                             "medio_pago": "Efectivo", "items": [{"id_producto": "PRD001", "cantidad": 2}]}, reloj)
    q15_actualizar_stock(db, "V011", reloj)
    assert (unidades(db, "L001"), unidades(db, "L014")) == (118, 44)

    segunda = cargar_mongo(db, RUTAS)  # repetir el seed tras operar
    assert segunda["reutilizada"] is True and segunda["eventos"] == []
    assert (unidades(db, "L001"), unidades(db, "L014")) == (118, 44)
    assert db.recetas.find_one({"_id": "RC006"})["estado"] == "Completada"
    assert db.ventas.find_one({"_id": "V011"})["estado"] == "Completada"
    assert db.ventas.count_documents({"_id": "B-VS1"}) == 1
