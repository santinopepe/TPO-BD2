"""Pruebas puras de valorización: precio de catálogo, subtotales y total."""

import pytest
from bson.int64 import Int64

from farmared.errores import ErrorDominio
from farmared.servicios.ventas.pedido import ItemPedido
from farmared.servicios.ventas.precios import LineaValorizada, valorizar

CATALOGO = {
    "B-P001": {"_id": "B-P001", "precio_unit": 2800},
    "B-P002": {"_id": "B-P002", "precio_unit": 3500},
    "B-P003": {"_id": "B-P003", "precio_unit": 0},
}


def test_captura_precio_de_catalogo_y_calcula_total():
    items = [ItemPedido("D1", "B-P001", 2), ItemPedido("D2", "B-P002", 1)]
    lineas, total = valorizar(items, CATALOGO)
    assert lineas == (
        LineaValorizada("D1", "B-P001", 2, 2800, 5600),
        LineaValorizada("D2", "B-P002", 1, 3500, 3500),
    )
    assert total == 9100


def test_mismo_producto_en_dos_lineas_mantiene_subtotales_por_linea():
    lineas, total = valorizar([ItemPedido("D1", "B-P001", 1), ItemPedido("D2", "B-P001", 3)], CATALOGO)
    assert [linea.subtotal for linea in lineas] == [2800, 8400]
    assert total == 11200


def test_precio_cero_es_valido():
    assert valorizar([ItemPedido("D1", "B-P003", 5)], CATALOGO)[1] == 0


def test_total_es_entero_python_no_float():
    _, total = valorizar([ItemPedido("D1", "B-P001", 3)], CATALOGO)
    assert type(total) is int


def test_producto_inexistente_es_no_existe():
    with pytest.raises(ErrorDominio) as exc:
        valorizar([ItemPedido("D1", "B-P999", 1)], CATALOGO)
    assert exc.value.codigo == "NO_EXISTE"


def test_precio_bson_int64_es_valido_y_se_captura_como_int():
    lineas, total = valorizar([ItemPedido("D1", "X", 2)], {"X": {"precio_unit": Int64(2800)}})
    assert lineas == (LineaValorizada("D1", "X", 2, 2800, 5600),) and total == 5600
    assert type(lineas[0].precio_unit) is int


@pytest.mark.parametrize("precio", [None, 10.5, "2800", -1, True])
def test_precio_de_catalogo_invalido_es_integridad(precio):
    with pytest.raises(ErrorDominio) as exc:
        valorizar([ItemPedido("D1", "X", 1)], {"X": {"precio_unit": precio}})
    assert exc.value.codigo == "INTEGRIDAD"


def test_desborde_de_subtotal_o_total_es_validacion():
    caro = {"X": {"precio_unit": 2**62}}
    with pytest.raises(ErrorDominio) as exc:
        valorizar([ItemPedido("D1", "X", 2)], caro)  # subtotal = 2**63
    assert exc.value.codigo == "VALIDACION"
    with pytest.raises(ErrorDominio) as exc:
        valorizar([ItemPedido("D1", "X", 1), ItemPedido("D2", "X", 1)], caro)  # total = 2**63
    assert exc.value.codigo == "VALIDACION"
