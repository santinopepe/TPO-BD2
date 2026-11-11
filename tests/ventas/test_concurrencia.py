"""Concurrencia real: dos clientes MongoDB independientes compitiendo por el mismo recurso.

Para que la carrera ocurra siempre (y no dependa del planificador de hilos), cada
transacción espera en una barrera justo después de leer sus lotes: ambas tienen
ya su snapshot y su plan antes de que cualquiera escriba. Solo el primer intento
de cada hilo espera; los reintentos del driver pasan directo.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from farmared.config import Config
from farmared.conexiones import obtener_mongo
from farmared.consultas.q14 import q14_registrar_venta
from farmared.consultas.q15 import q15_actualizar_stock
from farmared.errores import ErrorDominio
from farmared.servicios.ventas import coordinador


@pytest.fixture
def sincronizar_lecturas(monkeypatch):
    """Devuelve `activar()`: desde ahí, los dos próximos intentos se esperan tras leer lotes."""
    def activar():
        barrera = threading.Barrier(2, timeout=10)
        ya_esperaron: set[int] = set()
        original = coordinador.leer_lotes_vigentes

        def leer_y_esperar(*args, **kwargs):
            lotes = original(*args, **kwargs)
            hilo = threading.get_ident()
            if hilo not in ya_esperaron:
                ya_esperaron.add(hilo)
                barrera.wait()
            return lotes

        monkeypatch.setattr(coordinador, "leer_lotes_vigentes", leer_y_esperar)
    return activar


def en_paralelo(db, *operaciones):
    """Corre cada `operacion(db_propia)` en su hilo con su propio MongoClient.

    Devuelve [("ok", resultado) | ("error", codigo)] en el orden recibido.
    """
    config = replace(Config.from_env(), mongo_db=db.name)

    def correr(operacion):
        propia = obtener_mongo(config)
        try:
            return ("ok", operacion(propia))
        except ErrorDominio as error:
            return ("error", error.codigo)
        finally:
            propia.client.close()

    with ThreadPoolExecutor(len(operaciones)) as ejecutor:
        futuros = [ejecutor.submit(correr, op) for op in operaciones]
        return [f.result(timeout=60) for f in futuros]


def pedido(id_venta, producto, cantidad, id_receta=None):
    return {"id_venta": id_venta, "id_cliente": "B-C001", "id_farmaceutico": "B-F001",
            "medio_pago": "Débito", "id_receta": id_receta,
            "items": [{"id_producto": producto, "cantidad": cantidad}]}


def unidades(db, id_lote):
    return db.stock_lotes.find_one({"_id": id_lote})["unidades"]


def test_dos_ventas_de_cuatro_con_saldo_cinco_confirma_una(db, escenario, reloj, sincronizar_lecturas):
    sincronizar_lecturas()
    resultados = en_paralelo(
        db,
        lambda d: q14_registrar_venta(d, pedido("B-VC1", "B-P002", 4), reloj),
        lambda d: q14_registrar_venta(d, pedido("B-VC2", "B-P002", 4), reloj),
    )
    assert sorted(estado for estado, _ in resultados) == ["error", "ok"]
    assert ("error", "STOCK_INSUFICIENTE") in resultados
    assert unidades(db, "B-L004") == 1
    assert db.ventas.count_documents({}) == 1 and db.outbox.count_documents({}) == 1


def test_dos_ventas_por_la_ultima_dispensa_confirma_una(db, escenario, reloj, sincronizar_lecturas):
    # Productos de lotes distintos (B-P003 → B-L005, B-P004 → B-L006): el único documento que
    # ambas transacciones escriben es la receta, así que la carrera se decide allí y no en un lote.
    db.recetas.update_one({"_id": "B-RC001"}, {"$set": {"dispensas_realizadas": 2}})  # queda 1 de 3
    sincronizar_lecturas()
    resultados = en_paralelo(
        db,
        lambda d: q14_registrar_venta(d, pedido("B-VC1", "B-P003", 1, "B-RC001"), reloj),
        lambda d: q14_registrar_venta(d, pedido("B-VC2", "B-P004", 1, "B-RC001"), reloj),
    )
    assert ("error", "RECETA_INVALIDA") in resultados
    assert sum(estado == "ok" for estado, _ in resultados) == 1
    receta = db.recetas.find_one({"_id": "B-RC001"})
    assert (receta["dispensas_realizadas"], receta["estado"], receta["proxima_dispensa"]) == (3, "Completada", None)
    assert unidades(db, "B-L005") + unidades(db, "B-L006") == 20 + 3 - 1  # una sola venta descontó stock
    assert db.ventas.count_documents({}) == 1


def test_dos_q14_con_el_mismo_id_aplican_una_vez(db, escenario, reloj, sincronizar_lecturas):
    sincronizar_lecturas()
    resultados = en_paralelo(
        db,
        lambda d: q14_registrar_venta(d, pedido("B-VC1", "B-P001", 6), reloj),
        lambda d: q14_registrar_venta(d, pedido("B-VC1", "B-P001", 6), reloj),
    )
    assert [estado for estado, _ in resultados] == ["ok", "ok"]
    assert sorted(r["reutilizada"] for _, r in resultados) == [False, True]
    assert (unidades(db, "B-L001"), unidades(db, "B-L002")) == (0, 8)
    assert db.ventas.count_documents({}) == 1 and db.outbox.count_documents({}) == 1


def test_dos_q15_sobre_la_misma_pendiente_transicionan_una_vez(db, escenario, reloj, sincronizar_lecturas):
    q14_registrar_venta(db, pedido("B-VBASE", "B-P002", 1), reloj)  # venta válida como molde
    pendiente = db.ventas.find_one({"_id": "B-VBASE"})
    pendiente.update(_id="B-VP1", estado="Pendiente", stock_aplicado=False,
                     trazabilidad_lotes="no_aplicada", fecha_creacion_pendiente=pendiente["fecha"])
    pendiente["items"][0].update(id_detalle="B-VP1-D1", asignaciones_lotes=[])
    db.ventas.insert_one(pendiente)
    saldo = unidades(db, "B-L004")

    sincronizar_lecturas()
    resultados = en_paralelo(
        db,
        lambda d: q15_actualizar_stock(d, "B-VP1", reloj),
        lambda d: q15_actualizar_stock(d, "B-VP1", reloj),
    )
    assert [estado for estado, _ in resultados] == ["ok", "ok"]
    assert sorted(r["reutilizada"] for _, r in resultados) == [False, True]
    assert unidades(db, "B-L004") == saldo - 1
    assert db.ventas.find_one({"_id": "B-VP1"})["estado"] == "Completada"
    assert db.outbox.count_documents({"afectadas.id": "B-VP1"}) == 1
