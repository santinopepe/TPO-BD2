"""Integración con MongoDB real: transacción, lectura de snapshot y escrituras condicionales."""

from datetime import UTC, datetime

import pytest
from pymongo.errors import DuplicateKeyError

from farmared.errores import ErrorDominio
from farmared.servicios.ventas.escritura import aplicar_dispensa, descontar_lotes, registrar_evento
from farmared.servicios.ventas.fefo import ConsumoLote, planificar_fefo
from farmared.servicios.ventas.lectura import leer_lotes_vigentes, leer_snapshot, leer_venta
from farmared.servicios.ventas.receta import transicion_receta
from farmared.servicios.ventas.transaccion import ejecutar_transaccion

INSTANTE = datetime(2026, 11, 10, 15, 0, 0, 123456, tzinfo=UTC)


def unidades(db, id_lote):
    return db.stock_lotes.find_one({"_id": id_lote})["unidades"]


def codigo_error(db, operacion):
    with pytest.raises(ErrorDominio) as exc:
        ejecutar_transaccion(db, operacion)
    return exc.value.codigo


# --- Escenario y transacción -----------------------------------------------

def test_escenario_cumple_el_validador_de_a(db, escenario):
    for coleccion, docs in escenario.items():
        assert db[coleccion].count_documents({}) == len(docs)


def test_transaccion_confirma_y_devuelve_resultado(db, escenario):
    def operacion(sesion):
        db.clientes.update_one({"_id": "B-C001"}, {"$set": {"telefono": "1234"}}, session=sesion)
        return "ok"

    assert ejecutar_transaccion(db, operacion) == "ok"
    assert db.clientes.find_one({"_id": "B-C001"})["telefono"] == "1234"


def test_error_de_dominio_aborta_todo_y_se_propaga(db, escenario, estado_db):
    antes = estado_db()

    def operacion(sesion):
        db.stock_lotes.update_one({"_id": "B-L001"}, {"$inc": {"unidades": -1}}, session=sesion)
        db.recetas.update_one({"_id": "B-RC001"}, {"$set": {"estado": "Completada"}}, session=sesion)
        raise ErrorDominio("STOCK_INSUFICIENTE", "falla simulada después de escribir")

    assert codigo_error(db, operacion) == "STOCK_INSUFICIENTE"
    assert estado_db() == antes


def test_duplicate_key_se_propaga_sin_traducir_y_sin_efectos(db, escenario, estado_db):
    antes = estado_db()

    def operacion(sesion):
        db.stock_lotes.update_one({"_id": "B-L001"}, {"$inc": {"unidades": -1}}, session=sesion)
        db.clientes.insert_one({**escenario["clientes"][0], "_id": "B-C999"}, session=sesion)  # DNI repetido

    with pytest.raises(DuplicateKeyError):
        ejecutar_transaccion(db, operacion)
    assert estado_db() == antes


# --- Lecturas --------------------------------------------------------------

def test_leer_snapshot_trae_documentos_y_sucursal_del_farmaceutico(db, escenario):
    snap = ejecutar_transaccion(db, lambda s: leer_snapshot(
        db, s, id_cliente="B-C001", id_farmaceutico="B-F001",
        ids_productos=["B-P003", "B-P001", "B-P001", "B-P999"], id_receta="B-RC001"))
    assert snap.cliente["_id"] == "B-C001"
    assert snap.farmaceutico["_id"] == "B-F001"
    assert snap.sucursal["_id"] == "B-S001"
    assert sorted(snap.productos) == ["B-P001", "B-P003"]  # el inexistente no aparece
    assert snap.receta["_id"] == "B-RC001"


def test_leer_snapshot_con_inexistentes_y_sin_receta(db, escenario):
    snap = ejecutar_transaccion(db, lambda s: leer_snapshot(
        db, s, id_cliente="B-C404", id_farmaceutico="B-F404", ids_productos=[], id_receta=None))
    assert snap.cliente is None and snap.farmaceutico is None and snap.sucursal is None
    assert snap.productos == {} and snap.receta is None


def test_leer_lotes_vigentes_filtra_y_ordena(db, escenario, hoy):
    lotes = ejecutar_transaccion(db, lambda s: leer_lotes_vigentes(db, s, "B-S001", ["B-P001", "B-P002", "B-P004"], hoy))
    # Sin vencido (L003), sin droguería (L007), sin vacío (L008); L006 vence hoy y entra.
    assert [lote["_id"] for lote in lotes] == ["B-L006", "B-L001", "B-L002", "B-L004"]


def test_leer_venta_inexistente(db, escenario):
    assert ejecutar_transaccion(db, lambda s: leer_venta(db, s, "B-V404")) is None


# --- Descuento de lotes ----------------------------------------------------

def test_descuenta_plan_fefo_real(db, escenario, hoy):
    def operacion(sesion):
        lotes = leer_lotes_vigentes(db, sesion, "B-S001", ["B-P001"], hoy)
        plan = planificar_fefo({"B-P001": 6}, lotes, hoy, "B-S001")
        descontar_lotes(db, sesion, plan, "B-S001", hoy)
        return plan

    plan = ejecutar_transaccion(db, operacion)
    assert plan == (ConsumoLote("B-L001", "B-P001", 4), ConsumoLote("B-L002", "B-P001", 2))
    assert (unidades(db, "B-L001"), unidades(db, "B-L002"), unidades(db, "B-L003")) == (0, 8, 100)


@pytest.mark.parametrize("consumo", [
    ConsumoLote("B-L001", "B-P001", 5),   # más que el saldo (4)
    ConsumoLote("B-L003", "B-P001", 1),   # vencido
    ConsumoLote("B-L007", "B-P001", 1),   # otra sucursal
    ConsumoLote("B-L001", "B-P002", 1),   # producto equivocado
    ConsumoLote("B-L404", "B-P001", 1),   # inexistente
])
def test_descuento_que_no_cumple_condiciones_aborta_todo(db, escenario, estado_db, hoy, consumo):
    antes = estado_db()
    plan = [ConsumoLote("B-L002", "B-P001", 1), consumo]  # el primero sí aplicaría
    assert codigo_error(db, lambda s: descontar_lotes(db, s, plan, "B-S001", hoy)) == "INTEGRIDAD"
    assert estado_db() == antes


# --- Receta ----------------------------------------------------------------

def test_aplica_dispensa_de_tratamiento_prolongado(db, escenario, hoy):
    def operacion(sesion):
        receta = db.recetas.find_one({"_id": "B-RC001"}, session=sesion)
        aplicar_dispensa(db, sesion, receta, transicion_receta(receta, hoy))

    ejecutar_transaccion(db, operacion)
    receta = db.recetas.find_one({"_id": "B-RC001"})
    assert receta["dispensas_realizadas"] == 2 and receta["estado"] == "Vigente"
    assert receta["proxima_dispensa"].isoformat() == "2026-12-10T03:00:00+00:00"


def test_dispensa_con_contador_distinto_al_persistido_aborta(db, escenario, estado_db):
    antes = estado_db()
    leida = {**escenario["recetas"][0], "dispensas_realizadas": 0}  # persistida: 1
    assert codigo_error(db, lambda s: aplicar_dispensa(db, s, leida, {"dispensas_realizadas": 1})) == "INTEGRIDAD"
    assert estado_db() == antes


def test_dispensa_sobre_receta_que_ya_no_esta_vigente_aborta(db, escenario, estado_db):
    db.recetas.update_one({"_id": "B-RC001"}, {"$set": {"estado": "Vencida"}})
    antes = estado_db()
    leida = escenario["recetas"][0]  # lectura vieja: todavía Vigente
    assert codigo_error(db, lambda s: aplicar_dispensa(db, s, leida, {"dispensas_realizadas": 2})) == "INTEGRIDAD"
    assert estado_db() == antes


# --- Outbox ----------------------------------------------------------------

def test_evento_outbox_cumple_contrato(db, escenario):
    afectadas = [{"coleccion": "ventas", "id": "B-V001"}, {"coleccion": "recetas", "id": "B-RC001"}]
    id_evento = ejecutar_transaccion(db, lambda s: registrar_evento(db, s, afectadas, INSTANTE))
    evento = db.outbox.find_one({"_id": id_evento})
    assert evento == {
        "_id": id_evento,
        "afectadas": afectadas,
        "procesado": False,
        "creado_en": datetime(2026, 11, 10, 15, 0, 0, 123000, tzinfo=UTC),
    }


def test_evento_sin_afectadas_es_integridad(db, escenario):
    assert codigo_error(db, lambda s: registrar_evento(db, s, [], INSTANTE)) == "INTEGRIDAD"


# --- Atomicidad conjunta ---------------------------------------------------

def test_lotes_receta_y_evento_confirman_juntos(db, escenario, hoy):
    def operacion(sesion):
        lotes = leer_lotes_vigentes(db, sesion, "B-S001", ["B-P003"], hoy)
        descontar_lotes(db, sesion, planificar_fefo({"B-P003": 2}, lotes, hoy, "B-S001"), "B-S001", hoy)
        receta = db.recetas.find_one({"_id": "B-RC002"}, session=sesion)
        aplicar_dispensa(db, sesion, receta, transicion_receta(receta, hoy))
        return registrar_evento(db, sesion, [{"coleccion": "recetas", "id": "B-RC002"}], INSTANTE)

    id_evento = ejecutar_transaccion(db, operacion)
    assert unidades(db, "B-L005") == 18
    assert db.recetas.find_one({"_id": "B-RC002"})["estado"] == "Completada"
    assert db.outbox.count_documents({"_id": id_evento}) == 1


def test_falla_al_final_revierte_lotes_receta_y_evento(db, escenario, estado_db, hoy):
    antes = estado_db()

    def operacion(sesion):
        lotes = leer_lotes_vigentes(db, sesion, "B-S001", ["B-P003"], hoy)
        descontar_lotes(db, sesion, planificar_fefo({"B-P003": 2}, lotes, hoy, "B-S001"), "B-S001", hoy)
        receta = db.recetas.find_one({"_id": "B-RC002"}, session=sesion)
        aplicar_dispensa(db, sesion, receta, transicion_receta(receta, hoy))
        registrar_evento(db, sesion, [{"coleccion": "recetas", "id": "B-RC002"}], INSTANTE)
        raise ErrorDominio("INTEGRIDAD", "caída simulada antes del commit")

    assert codigo_error(db, operacion) == "INTEGRIDAD"
    assert estado_db() == antes
