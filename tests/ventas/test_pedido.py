"""Pruebas puras del pedido de venta (q14): forma, tipos e identificadores de línea."""

import pytest
from bson.int64 import Int64

from farmared.errores import ErrorDominio
from farmared.servicios.ventas.pedido import ItemPedido, PedidoVenta, normalizar_pedido


def pedido(**cambios):
    base = {
        "id_venta": "B-V001",
        "id_cliente": "B-C001",
        "id_farmaceutico": "B-F001",
        "medio_pago": "Débito",
        "items": [
            {"id_detalle": "B-D001", "id_producto": "B-P001", "cantidad": 2},
            {"id_detalle": "B-D002", "id_producto": "B-P002", "cantidad": 1},
        ],
    }
    base.update(cambios)
    return base


def rechazo(datos) -> str:
    with pytest.raises(ErrorDominio) as exc:
        normalizar_pedido(datos)
    assert exc.value.codigo == "VALIDACION"
    return exc.value.mensaje


def test_pedido_valido_sin_receta():
    resultado = normalizar_pedido(pedido())
    assert resultado == PedidoVenta(
        id_venta="B-V001", id_cliente="B-C001", id_farmaceutico="B-F001", medio_pago="Débito",
        items=(ItemPedido("B-D001", "B-P001", 2), ItemPedido("B-D002", "B-P002", 1)),
        id_receta=None,
    )


def test_pedido_con_receta_y_receta_nula_explicita():
    assert normalizar_pedido(pedido(id_receta="B-RC001")).id_receta == "B-RC001"
    assert normalizar_pedido(pedido(id_receta=None)).id_receta is None


def test_pedido_es_inmutable():
    resultado = normalizar_pedido(pedido())
    with pytest.raises(AttributeError):
        resultado.id_cliente = "otro"  # type: ignore[misc]
    assert isinstance(resultado.items, tuple)


def test_genera_id_detalle_deterministico_si_falta():
    datos = pedido(items=[
        {"id_producto": "B-P001", "cantidad": 1},
        {"id_producto": "B-P002", "cantidad": 3, "id_detalle": None},
    ])
    assert [i.id_detalle for i in normalizar_pedido(datos).items] == ["B-V001-D1", "B-V001-D2"]
    assert normalizar_pedido(datos) == normalizar_pedido(datos)


def test_mismo_producto_en_dos_lineas_se_conserva_por_linea():
    datos = pedido(items=[
        {"id_detalle": "B-D001", "id_producto": "B-P001", "cantidad": 2},
        {"id_detalle": "B-D002", "id_producto": "B-P001", "cantidad": 3},
    ])
    assert [(i.id_producto, i.cantidad) for i in normalizar_pedido(datos).items] == [("B-P001", 2), ("B-P001", 3)]


@pytest.mark.parametrize("medio", ["Efectivo", "Débito", "Crédito", "Transferencia", "Obra social"])
def test_acepta_los_medios_de_pago_del_contrato(medio):
    assert normalizar_pedido(pedido(medio_pago=medio)).medio_pago == medio


@pytest.mark.parametrize("datos", [None, [], "pedido", 3])
def test_rechaza_pedido_que_no_es_objeto(datos):
    rechazo(datos)


@pytest.mark.parametrize("campo", ["id_venta", "id_cliente", "id_farmaceutico", "medio_pago", "items"])
def test_rechaza_campo_obligatorio_faltante(campo):
    datos = pedido()
    del datos[campo]
    assert campo in rechazo(datos)


def test_rechaza_campos_desconocidos_en_pedido_y_en_item():
    assert "total" in rechazo(pedido(total=1000))
    assert "precio_unit" in rechazo(pedido(items=[{"id_producto": "B-P001", "cantidad": 1, "precio_unit": 10}]))


@pytest.mark.parametrize("valor", ["", "   ", " B-V001", "B-V001 ", 1, None])
def test_rechaza_identificadores_invalidos(valor):
    assert "id_venta" in rechazo(pedido(id_venta=valor))


def test_rechaza_id_receta_vacia():
    assert "id_receta" in rechazo(pedido(id_receta=""))


@pytest.mark.parametrize("medio", ["debito", "Tarjeta", "", None])
def test_rechaza_medio_de_pago_fuera_del_enum(medio):
    assert "medio_pago" in rechazo(pedido(medio_pago=medio))


@pytest.mark.parametrize("items", [[], (), "B-P001", {"id_producto": "B-P001", "cantidad": 1}, None])
def test_rechaza_items_vacios_o_que_no_son_lista(items):
    mensaje = rechazo(pedido(items=items))
    assert "ítem" in mensaje or "items" in mensaje


def test_cantidad_bson_int64_se_acepta_como_entero_python():
    # Una pendiente persistida puede traer la cantidad como BSON long (Int64, subclase de int).
    item = normalizar_pedido(pedido(items=[{"id_producto": "B-P001", "cantidad": Int64(2)}])).items[0]
    assert item.cantidad == 2 and type(item.cantidad) is int


@pytest.mark.parametrize("cantidad", [0, -1, 2.0, 1.5, "2", True, None, 2**63])
def test_rechaza_cantidades_no_enteras_positivas(cantidad):
    assert "cantidad" in rechazo(pedido(items=[{"id_producto": "B-P001", "cantidad": cantidad}]))


def test_rechaza_item_que_no_es_objeto_y_campos_de_item_faltantes():
    assert "items[1]" in rechazo(pedido(items=["B-P001"]))
    mensaje = rechazo(pedido(items=[{"id_detalle": "B-D001"}]))
    assert "id_producto" in mensaje and "cantidad" in mensaje


def test_rechaza_id_detalle_repetido():
    datos = pedido(items=[
        {"id_detalle": "B-D001", "id_producto": "B-P001", "cantidad": 1},
        {"id_detalle": "B-D001", "id_producto": "B-P002", "cantidad": 1},
    ])
    assert "B-D001" in rechazo(datos)


def test_rechaza_id_explicito_que_choca_con_uno_generado():
    datos = pedido(items=[
        {"id_producto": "B-P001", "cantidad": 1},
        {"id_detalle": "B-V001-D1", "id_producto": "B-P002", "cantidad": 1},
    ])
    assert "B-V001-D1" in rechazo(datos)


def test_reune_todos_los_errores_en_un_unico_rechazo():
    mensaje = rechazo(pedido(id_cliente="", medio_pago="Cheque", items=[{"id_producto": "B-P001", "cantidad": 0}]))
    assert "id_cliente" in mensaje and "medio_pago" in mensaje and "cantidad" in mensaje
