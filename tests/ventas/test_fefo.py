"""Pruebas puras de FEFO: demanda agregada, plan todo-o-nada y asignación a líneas."""

from datetime import UTC, date, datetime, timedelta

import pytest

from farmared.clock import inicio_dia_utc
from farmared.errores import ErrorDominio
from farmared.servicios.ventas.fefo import (
    Asignacion,
    ConsumoLote,
    demanda_por_producto,
    dia_comercial,
    distribuir_asignaciones,
    planificar_fefo,
)
from farmared.servicios.ventas.pedido import ItemPedido

HOY = date(2026, 11, 10)
SUC = "B-S001"


def lote(id_lote, unidades, dias, producto="B-P001", sucursal=SUC):
    """Lote con vencimiento HOY + dias, guardado como inicio de día comercial (como el seed)."""
    return {"_id": id_lote, "id_producto": producto, "id_sucursal": sucursal,
            "nro_lote": "N-" + id_lote, "unidades": unidades,
            "vencimiento": inicio_dia_utc(HOY + timedelta(days=dias))}


def plan(demanda, lotes):
    return planificar_fefo(demanda, lotes, HOY, SUC)


def rechazo(demanda, lotes, codigo):
    with pytest.raises(ErrorDominio) as exc:
        plan(demanda, lotes)
    assert exc.value.codigo == codigo
    return exc.value.mensaje


# --- Demanda ---------------------------------------------------------------

def test_demanda_suma_lineas_del_mismo_producto():
    items = [ItemPedido("D1", "B-P001", 2), ItemPedido("D2", "B-P002", 1), ItemPedido("D3", "B-P001", 3)]
    assert demanda_por_producto(items) == {"B-P001": 5, "B-P002": 1}


def test_demanda_rechaza_overflow_int64():
    items = [ItemPedido("D1", "B-P001", 2**63 - 1), ItemPedido("D2", "B-P001", 1)]
    with pytest.raises(ErrorDominio) as exc:
        demanda_por_producto(items)
    assert exc.value.codigo == "VALIDACION"


# --- Plan FEFO -------------------------------------------------------------

def test_ejemplo_del_plan_vencido_intacto_y_dos_lotes_por_vencimiento():
    lotes = [lote("L2", 10, 30), lote("L0", 100, -1), lote("L1", 4, 10)]
    assert plan({"B-P001": 6}, lotes) == (ConsumoLote("L1", "B-P001", 4), ConsumoLote("L2", "B-P001", 2))


def test_lote_que_vence_hoy_se_dispensa_y_el_de_ayer_no():
    assert plan({"B-P001": 1}, [lote("AYER", 5, -1), lote("HOY", 5, 0)]) == (ConsumoLote("HOY", "B-P001", 1),)


def test_empate_de_vencimiento_se_ordena_por_id_de_lote():
    lotes = [lote("B-L010", 5, 20), lote("B-L002", 5, 20)]
    assert plan({"B-P001": 6}, lotes) == (ConsumoLote("B-L002", "B-P001", 5), ConsumoLote("B-L010", "B-P001", 1))


def test_plan_no_depende_del_orden_de_lectura():
    lotes = [lote("A", 3, 5), lote("B", 3, 1), lote("C", 3, 9)]
    assert plan({"B-P001": 7}, lotes) == plan({"B-P001": 7}, list(reversed(lotes)))


def test_ignora_lotes_vacios_y_de_otra_sucursal_o_producto():
    lotes = [
        lote("VACIO", 0, 1),
        lote("OTRA_SUC", 50, 1, sucursal="B-S002"),
        lote("OTRO_PROD", 50, 1, producto="B-P999"),
        lote("OK", 5, 30),
    ]
    assert plan({"B-P001": 5}, lotes) == (ConsumoLote("OK", "B-P001", 5),)


def test_demanda_exacta_agota_los_lotes():
    resultado = plan({"B-P001": 9}, [lote("A", 4, 1), lote("B", 5, 2)])
    assert sum(c.cantidad for c in resultado) == 9
    assert resultado == (ConsumoLote("A", "B-P001", 4), ConsumoLote("B", "B-P001", 5))


def test_varios_productos_en_orden_de_id():
    lotes = [lote("X1", 5, 3, producto="B-P002"), lote("Y1", 5, 3, producto="B-P001")]
    assert plan({"B-P002": 1, "B-P001": 2}, lotes) == (
        ConsumoLote("Y1", "B-P001", 2), ConsumoLote("X1", "B-P002", 1),
    )


def test_unidades_vencidas_no_cuentan_como_disponibles():
    mensaje = rechazo({"B-P001": 5}, [lote("VENCIDO", 100, -1), lote("OK", 4, 1)], "STOCK_INSUFICIENTE")
    assert "B-P001: pedido 5, vigente 4" in mensaje


def test_un_producto_insuficiente_rechaza_toda_la_venta():
    lotes = [lote("OK", 50, 1, producto="B-P001"), lote("POCO", 1, 1, producto="B-P002")]
    mensaje = rechazo({"B-P001": 2, "B-P002": 3}, lotes, "STOCK_INSUFICIENTE")
    assert "B-P002: pedido 3, vigente 1" in mensaje
    assert "B-P001" not in mensaje


def test_informa_todos_los_faltantes_incluido_producto_sin_lotes():
    mensaje = rechazo({"B-P001": 2, "B-P002": 1}, [lote("POCO", 1, 1)], "STOCK_INSUFICIENTE")
    assert "B-P001: pedido 2, vigente 1" in mensaje and "B-P002: pedido 1, vigente 0" in mensaje


def test_lote_repetido_en_snapshot_es_error_de_integridad():
    rechazo({"B-P001": 1}, [lote("L1", 5, 1), lote("L1", 5, 2)], "INTEGRIDAD")


@pytest.mark.parametrize("unidades", [-1, 2.0, "5", None, True])
def test_unidades_invalidas_son_error_de_integridad(unidades):
    rechazo({"B-P001": 1}, [lote("L1", unidades, 1)], "INTEGRIDAD")


def test_vencimiento_naive_se_interpreta_utc():
    # 2026-11-10T02:59Z es todavía 09/11 en Buenos Aires (UTC-3).
    assert dia_comercial(datetime(2026, 11, 10, 2, 59)) == date(2026, 11, 9)
    assert dia_comercial(datetime(2026, 11, 10, 3, 0, tzinfo=UTC)) == date(2026, 11, 10)


# --- Asignación a líneas ---------------------------------------------------

def test_dos_lineas_del_mismo_producto_reparten_lotes_sin_duplicar():
    items = [ItemPedido("D1", "B-P001", 2), ItemPedido("D2", "B-P001", 3)]
    consumo = plan(demanda_por_producto(items), [lote("L1", 4, 10), lote("L2", 10, 30)])
    assert distribuir_asignaciones(items, consumo) == {
        "D1": (Asignacion("L1", 2),),
        "D2": (Asignacion("L1", 2), Asignacion("L2", 1)),
    }


def test_cada_linea_suma_exactamente_su_cantidad():
    items = [ItemPedido("D1", "B-P001", 3), ItemPedido("D2", "B-P002", 4), ItemPedido("D3", "B-P001", 5)]
    lotes = [lote("A", 2, 1), lote("B", 2, 2), lote("C", 10, 3),
             lote("Z", 1, 1, producto="B-P002"), lote("W", 9, 2, producto="B-P002")]
    asignaciones = distribuir_asignaciones(items, plan(demanda_por_producto(items), lotes))
    for item in items:
        assert sum(a.cantidad for a in asignaciones[item.id_detalle]) == item.cantidad


def test_plan_que_no_cubre_las_lineas_es_error_de_integridad():
    with pytest.raises(ErrorDominio) as exc:
        distribuir_asignaciones([ItemPedido("D1", "B-P001", 3)], [ConsumoLote("L1", "B-P001", 2)])
    assert exc.value.codigo == "INTEGRIDAD"


def test_plan_que_sobra_es_error_de_integridad():
    with pytest.raises(ErrorDominio) as exc:
        distribuir_asignaciones([ItemPedido("D1", "B-P001", 1)], [ConsumoLote("L1", "B-P001", 2)])
    assert exc.value.codigo == "INTEGRIDAD"
