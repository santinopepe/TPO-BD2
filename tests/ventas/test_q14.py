"""Integración de q14 con MongoDB real: éxito, rechazos sin efectos e idempotencia."""

from datetime import UTC, datetime

import pytest

from farmared.consultas import q14 as modulo_q14
from farmared.consultas.q14 import q14_registrar_venta
from farmared.errores import ErrorDominio


def pedido(**cambios):
    base = {"id_venta": "B-V001", "id_cliente": "B-C001", "id_farmaceutico": "B-F001",
            "medio_pago": "Débito", "items": [{"id_producto": "B-P001", "cantidad": 6}]}
    base.update(cambios)
    return base


def unidades(db, *ids):
    return tuple(db.stock_lotes.find_one({"_id": i})["unidades"] for i in ids)


def rechazo(db, reloj, datos):
    with pytest.raises(ErrorDominio) as exc:
        q14_registrar_venta(db, datos, reloj)
    return exc.value.codigo


# --- Éxito -----------------------------------------------------------------

def test_venta_libre_consume_dos_lotes_por_fefo(db, escenario, reloj):
    resultado = q14_registrar_venta(db, pedido(), reloj)

    assert resultado["reutilizada"] is False and len(resultado["eventos"]) == 1
    assert unidades(db, "B-L001", "B-L002", "B-L003") == (0, 8, 100)  # vencido intacto
    venta = db.ventas.find_one({"_id": "B-V001"})
    assert venta == resultado["documento"]
    assert venta["items"] == [{
        "id_detalle": "B-V001-D1", "id_producto": "B-P001", "cantidad": 6,
        "precio_unit": 2800, "subtotal": 16800,
        "asignaciones_lotes": [{"id_lote": "B-L001", "cantidad": 4}, {"id_lote": "B-L002", "cantidad": 2}],
    }]
    assert {k: venta[k] for k in ("id_sucursal", "id_receta", "tipo", "estado", "total", "stock_aplicado",
                                  "receta_aplicada", "origen", "trazabilidad_lotes")} == {
        "id_sucursal": "B-S001", "id_receta": None, "tipo": "Venta libre", "estado": "Completada",
        "total": 16800, "stock_aplicado": True, "receta_aplicada": False, "origen": "servicio",
        "trazabilidad_lotes": "registrada",
    }
    assert venta["fecha"] == datetime(2026, 11, 10, 3, 0, tzinfo=UTC)  # inicio del día comercial
    assert len(venta["request_hash"]) == 64
    evento = db.outbox.find_one({"_id": resultado["eventos"][0]})
    assert evento["afectadas"] == [{"coleccion": "ventas", "id": "B-V001"}] and evento["procesado"] is False


def test_venta_con_receta_dispensa_una_vez_por_venta(db, escenario, reloj):
    datos = pedido(id_receta="B-RC001", items=[
        {"id_producto": "B-P003", "cantidad": 2},
        {"id_producto": "B-P003", "cantidad": 1},
        {"id_producto": "B-P001", "cantidad": 1},
    ])
    resultado = q14_registrar_venta(db, datos, reloj)

    venta = resultado["documento"]
    assert venta["tipo"] == "Con receta" and venta["receta_aplicada"] is True
    assert venta["total"] == 3 * 4000 + 2800
    receta = db.recetas.find_one({"_id": "B-RC001"})
    assert (receta["dispensas_realizadas"], receta["estado"]) == (2, "Vigente")  # 1 → 2, no 1 → 4
    assert receta["proxima_dispensa"] == datetime(2026, 12, 10, 3, 0, tzinfo=UTC)
    assert unidades(db, "B-L005", "B-L001") == (17, 3)
    evento = db.outbox.find_one({"_id": resultado["eventos"][0]})
    assert evento["afectadas"] == [{"coleccion": "ventas", "id": "B-V001"}, {"coleccion": "recetas", "id": "B-RC001"}]


def test_archivado_con_receta_simple_usa_lote_que_vence_hoy_y_completa_receta(db, escenario, reloj):
    q14_registrar_venta(db, pedido(id_receta="B-RC002", items=[{"id_producto": "B-P004", "cantidad": 3}]), reloj)
    assert unidades(db, "B-L006") == (0,)
    receta = db.recetas.find_one({"_id": "B-RC002"})
    assert (receta["dispensas_realizadas"], receta["estado"], receta["proxima_dispensa"]) == (1, "Completada", None)


def test_producto_repetido_en_dos_lineas_agrega_demanda(db, escenario, reloj):
    datos = pedido(items=[{"id_detalle": "X1", "id_producto": "B-P001", "cantidad": 2},
                          {"id_detalle": "X2", "id_producto": "B-P001", "cantidad": 3}])
    venta = q14_registrar_venta(db, datos, reloj)["documento"]
    assert unidades(db, "B-L001", "B-L002") == (0, 9)
    assert [i["asignaciones_lotes"] for i in venta["items"]] == [
        [{"id_lote": "B-L001", "cantidad": 2}],
        [{"id_lote": "B-L001", "cantidad": 2}, {"id_lote": "B-L002", "cantidad": 1}],
    ]


# --- Rechazos sin efectos --------------------------------------------------

@pytest.mark.parametrize(("cambios", "codigo"), [
    ({"id_cliente": "B-C404"}, "NO_EXISTE"),
    ({"id_cliente": "B-C003"}, "VALIDACION"),                   # cliente dado de baja
    ({"id_farmaceutico": "B-F404"}, "NO_EXISTE"),
    ({"id_farmaceutico": "B-F002"}, "VALIDACION"),              # farmacéutico inactivo
    ({"id_farmaceutico": "B-F003"}, "VALIDACION"),              # de droguería
    ({"id_farmaceutico": "B-F004"}, "VALIDACION"),              # farmacia inactiva
    ({"items": [{"id_producto": "B-P404", "cantidad": 1}]}, "NO_EXISTE"),
    ({"items": [{"id_producto": "B-P005", "cantidad": 1}]}, "VALIDACION"),  # discontinuado
    ({"items": [{"id_producto": "B-P001", "cantidad": 15}]}, "STOCK_INSUFICIENTE"),  # vigente 14
    ({"items": [{"id_producto": "B-P001", "cantidad": 2},
                {"id_producto": "B-P002", "cantidad": 6}]}, "STOCK_INSUFICIENTE"),  # uno no alcanza
    ({"items": [{"id_producto": "B-P003", "cantidad": 1}]}, "RECETA_INVALIDA"),     # falta receta
    ({"items": [{"id_producto": "B-P003", "cantidad": 1}], "id_receta": "B-RC404"}, "NO_EXISTE"),
    ({"items": [{"id_producto": "B-P003", "cantidad": 1}], "id_receta": "B-RC003"}, "RECETA_INVALIDA"),  # ajena
    ({"items": [{"id_producto": "B-P003", "cantidad": 1}], "id_receta": "B-RC004"}, "RECETA_INVALIDA"),  # completada
    ({"id_receta": "B-RC001"}, "VALIDACION"),                   # receta en venta libre
    ({"items": []}, "VALIDACION"),
])
def test_rechazo_no_modifica_nada(db, escenario, estado_db, reloj, cambios, codigo):
    antes = estado_db()
    assert rechazo(db, reloj, pedido(**cambios)) == codigo
    assert estado_db() == antes


def test_receta_sin_dispensas_rechaza_y_conserva_stock(db, escenario, estado_db, reloj):
    db.recetas.update_one({"_id": "B-RC001"}, {"$set": {"dispensas_realizadas": 3}})
    antes = estado_db()
    datos = pedido(id_receta="B-RC001", items=[{"id_producto": "B-P003", "cantidad": 1}])
    assert rechazo(db, reloj, datos) == "RECETA_INVALIDA"
    assert estado_db() == antes


# --- Idempotencia ----------------------------------------------------------

def test_reintento_del_mismo_pedido_no_repite_efectos(db, escenario, reloj):
    primero = q14_registrar_venta(db, pedido(), reloj)
    segundo = q14_registrar_venta(db, pedido(), reloj)

    assert segundo == {"documento": primero["documento"], "eventos": [], "reutilizada": True}
    assert unidades(db, "B-L001", "B-L002") == (0, 8)
    assert db.ventas.count_documents({}) == 1 and db.outbox.count_documents({}) == 1


def test_mismo_id_con_otro_pedido_es_conflicto(db, escenario, estado_db, reloj):
    q14_registrar_venta(db, pedido(), reloj)
    antes = estado_db()
    assert rechazo(db, reloj, pedido(items=[{"id_producto": "B-P001", "cantidad": 1}])) == "CONFLICTO_ID"
    assert estado_db() == antes


def test_id_de_venta_importada_del_csv_es_conflicto(db, escenario, estado_db, reloj):
    q14_registrar_venta(db, pedido(id_venta="B-CSV1"), reloj)
    db.ventas.update_one({"_id": "B-CSV1"}, {"$set": {"origen": "csv"}, "$unset": {"request_hash": ""}})
    antes = estado_db()
    assert rechazo(db, reloj, pedido(id_venta="B-CSV1")) == "CONFLICTO_ID"
    assert estado_db() == antes


def test_colision_de_id_entre_lectura_e_insert_recupera_la_confirmada(db, escenario, reloj, monkeypatch):
    primero = q14_registrar_venta(db, pedido(), reloj)
    # Simula que otro intento confirmó después de nuestra lectura: la lectura no ve la venta.
    monkeypatch.setattr(modulo_q14, "leer_venta", lambda *args: None)
    segundo = q14_registrar_venta(db, pedido(), reloj)

    assert segundo["reutilizada"] is True and segundo["documento"] == primero["documento"]
    assert unidades(db, "B-L001", "B-L002") == (0, 8)
    assert db.outbox.count_documents({}) == 1
