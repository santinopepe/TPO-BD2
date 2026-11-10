"""Integración de q15 con MongoDB real: completar pendientes, rechazos sin cambios e idempotencia."""

from datetime import UTC, datetime

import pytest

from farmared.clock import inicio_dia_utc
from farmared.consultas.q15 import q15_actualizar_stock
from farmared.errores import ErrorDominio

FECHA_VIEJA = datetime(2026, 9, 20, 3, 0, tzinfo=UTC)  # creada en septiembre


def pendiente(id, items, *, id_cliente="B-C001", id_farmaceutico="B-F001", id_receta=None, **cambios):
    """Pendiente con la forma que produce el loader de A para ventas CSV."""
    lineas = [{"id_detalle": f"{id}-D{n}", "id_producto": p, "cantidad": c, "precio_unit": precio,
               "subtotal": c * precio, "asignaciones_lotes": [],
               "importacion": {"huella": "x" * 64, "archivo": "detalle_ventas.csv", "fila": n}}
              for n, (p, c, precio) in enumerate(items, start=1)]
    doc = {"_id": id, "id_cliente": id_cliente, "id_farmaceutico": id_farmaceutico, "id_sucursal": "B-S001",
           "id_receta": id_receta, "fecha": FECHA_VIEJA, "tipo": "Con receta" if id_receta else "Venta libre",
           "medio_pago": "Efectivo", "estado": "Pendiente", "total": sum(l["subtotal"] for l in lineas),
           "items": lineas, "stock_aplicado": False, "receta_aplicada": False, "origen": "csv",
           "trazabilidad_lotes": "no_aplicada", "fecha_creacion_pendiente": FECHA_VIEJA}
    doc.update(cambios)
    return doc


def insertar(db, *docs):
    db.ventas.insert_many(list(docs))


def unidades(db, *ids):
    return tuple(db.stock_lotes.find_one({"_id": i})["unidades"] for i in ids)


def rechazo(db, reloj, id_venta):
    with pytest.raises(ErrorDominio) as exc:
        q15_actualizar_stock(db, id_venta, reloj)
    return exc.value.codigo


# --- Éxito -----------------------------------------------------------------

def test_completa_pendiente_con_fefo_precio_y_fecha_actuales(db, escenario, reloj):
    insertar(db, pendiente("B-VP1", [("B-P001", 6, 2000)]))  # precio viejo 2000; catálogo hoy 2800
    resultado = q15_actualizar_stock(db, "B-VP1", reloj)

    venta = db.ventas.find_one({"_id": "B-VP1"})
    assert resultado["reutilizada"] is False and len(resultado["eventos"]) == 1
    assert resultado["documento"] == venta
    assert unidades(db, "B-L001", "B-L002", "B-L003") == (0, 8, 100)
    assert (venta["estado"], venta["stock_aplicado"], venta["receta_aplicada"]) == ("Completada", True, False)
    assert venta["fecha"] == inicio_dia_utc(reloj.today())        # ingresos del mes de finalización
    assert venta["fecha_creacion_pendiente"] == FECHA_VIEJA       # fecha original conservada
    assert (venta["total"], venta["items"][0]["precio_unit"], venta["items"][0]["subtotal"]) == (16800, 2800, 16800)
    assert venta["items"][0]["asignaciones_lotes"] == [{"id_lote": "B-L001", "cantidad": 4},
                                                       {"id_lote": "B-L002", "cantidad": 2}]
    assert venta["items"][0]["importacion"]["fila"] == 1           # traza de importación conservada
    assert (venta["origen"], venta["trazabilidad_lotes"]) == ("csv", "registrada")
    assert "request_hash" not in venta
    evento = db.outbox.find_one({"_id": resultado["eventos"][0]})
    assert evento["afectadas"] == [{"coleccion": "ventas", "id": "B-VP1"}]


def test_pendiente_con_receta_consume_dispensa(db, escenario, reloj):
    insertar(db, pendiente("B-VP2", [("B-P003", 2, 3000)], id_receta="B-RC001"))
    resultado = q15_actualizar_stock(db, "B-VP2", reloj)

    venta = resultado["documento"]
    assert (venta["tipo"], venta["receta_aplicada"], venta["total"]) == ("Con receta", True, 8000)
    receta = db.recetas.find_one({"_id": "B-RC001"})
    assert (receta["dispensas_realizadas"], receta["estado"]) == (2, "Vigente")
    assert unidades(db, "B-L005") == (18,)
    evento = db.outbox.find_one({"_id": resultado["eventos"][0]})
    assert evento["afectadas"] == [{"coleccion": "ventas", "id": "B-VP2"}, {"coleccion": "recetas", "id": "B-RC001"}]


def test_pendiente_sin_fecha_creacion_toma_su_fecha_original(db, escenario, reloj):
    doc = pendiente("B-VP3", [("B-P002", 1, 3500)])
    del doc["fecha_creacion_pendiente"]
    insertar(db, doc)
    q15_actualizar_stock(db, "B-VP3", reloj)
    assert db.ventas.find_one({"_id": "B-VP3"})["fecha_creacion_pendiente"] == FECHA_VIEJA


# --- Rechazos: la pendiente queda exactamente igual --------------------------

@pytest.mark.parametrize(("doc", "preparar", "codigo"), [
    (pendiente("B-VR1", [("B-P001", 15, 2800)]), None, "STOCK_INSUFICIENTE"),         # vigente 14
    (pendiente("B-VR2", [("B-P001", 1, 2800), ("B-P002", 6, 3500)]), None, "STOCK_INSUFICIENTE"),
    (pendiente("B-VR3", [("B-P001", 1, 2800)], id_farmaceutico="B-F002"), None, "VALIDACION"),  # hoy inactivo
    (pendiente("B-VR4", [("B-P001", 1, 2800)], id_cliente="B-C003"), None, "VALIDACION"),       # cliente de baja
    (pendiente("B-VR5", [("B-P005", 1, 1000)]), None, "VALIDACION"),                  # producto discontinuado
    (pendiente("B-VR6", [("B-P003", 1, 4000)], id_receta="B-RC004"), None, "RECETA_INVALIDA"),  # completada
    (pendiente("B-VR7", [("B-P003", 1, 4000)], id_receta="B-RC001"),
     {"dispensas_realizadas": 3}, "RECETA_INVALIDA"),                                  # agotada desde que se creó
])
def test_rechazo_conserva_pendiente_lotes_y_receta(db, escenario, estado_db, reloj, doc, preparar, codigo):
    insertar(db, doc)
    if preparar:
        db.recetas.update_one({"_id": "B-RC001"}, {"$set": preparar})
    antes = estado_db()
    assert rechazo(db, reloj, doc["_id"]) == codigo
    assert estado_db() == antes


# --- Estados distintos de Pendiente ------------------------------------------

def test_doble_finalizacion_no_repite_efectos(db, escenario, reloj):
    insertar(db, pendiente("B-VP1", [("B-P001", 6, 2800)]))
    primero = q15_actualizar_stock(db, "B-VP1", reloj)
    segundo = q15_actualizar_stock(db, "B-VP1", reloj)

    assert segundo == {"documento": primero["documento"], "eventos": [], "reutilizada": True}
    assert unidades(db, "B-L001", "B-L002") == (0, 8)
    assert db.outbox.count_documents({}) == 1


def test_completada_historica_del_csv_se_reconoce_sin_tocar_stock(db, escenario, estado_db, reloj):
    insertar(db, pendiente("B-VH1", [("B-P001", 1, 2800)], estado="Completada", stock_aplicado=True,
                           trazabilidad_lotes="desconocida", fecha_creacion_pendiente=FECHA_VIEJA))
    antes = estado_db()
    resultado = q15_actualizar_stock(db, "B-VH1", reloj)
    assert resultado["reutilizada"] is True and resultado["eventos"] == []
    assert estado_db() == antes


@pytest.mark.parametrize(("cambios", "codigo"), [
    ({"estado": "Anulada"}, "VALIDACION"),
    ({"estado": "Completada"}, "INTEGRIDAD"),                    # completada sin stock aplicado
    ({"stock_aplicado": True}, "INTEGRIDAD"),                    # pendiente con marcas incoherentes
    ({"receta_aplicada": True}, "INTEGRIDAD"),
])
def test_estados_o_marcas_no_procesables(db, escenario, estado_db, reloj, cambios, codigo):
    insertar(db, pendiente("B-VX1", [("B-P001", 1, 2800)], **cambios))
    antes = estado_db()
    assert rechazo(db, reloj, "B-VX1") == codigo
    assert estado_db() == antes


def test_pendiente_mal_formada_es_integridad(db, escenario, estado_db, reloj):
    # Cantidad 0 la rechaza el validador de A; se desactiva solo para simular un documento corrupto.
    db.command("collMod", "ventas", validationLevel="off")
    insertar(db, pendiente("B-VX2", [("B-P001", 0, 2800)]))
    antes = estado_db()
    assert rechazo(db, reloj, "B-VX2") == "INTEGRIDAD"
    assert estado_db() == antes


@pytest.mark.parametrize(("id_venta", "codigo"), [("B-V404", "NO_EXISTE"), ("", "VALIDACION"),
                                                  (" B-VP1", "VALIDACION"), (None, "VALIDACION")])
def test_id_inexistente_o_invalido(db, escenario, reloj, id_venta, codigo):
    assert rechazo(db, reloj, id_venta) == codigo
