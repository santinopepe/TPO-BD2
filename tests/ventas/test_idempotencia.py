"""Pruebas puras del request_hash de q14."""

import re

from farmared.servicios.ventas.idempotencia import request_hash
from farmared.servicios.ventas.pedido import normalizar_pedido


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
    return normalizar_pedido(base)


def test_hash_es_sha256_hex_y_estable():
    valor = request_hash(pedido())
    assert re.fullmatch(r"[0-9a-f]{64}", valor)
    assert valor == request_hash(pedido())


def test_pedidos_equivalentes_tienen_el_mismo_hash():
    # Receta ausente = receta nula; id_detalle generado = el mismo id explícito.
    assert request_hash(pedido()) == request_hash(pedido(id_receta=None))
    sin_ids = pedido(items=[{"id_producto": "B-P001", "cantidad": 2}])
    con_ids = pedido(items=[{"id_detalle": "B-V001-D1", "id_producto": "B-P001", "cantidad": 2}])
    assert request_hash(sin_ids) == request_hash(con_ids)


def test_hash_cambia_con_cualquier_campo_del_pedido():
    base = request_hash(pedido())
    variantes = [
        pedido(id_venta="B-V002"),
        pedido(id_cliente="B-C002"),
        pedido(id_farmaceutico="B-F002"),
        pedido(medio_pago="Efectivo"),
        pedido(id_receta="B-RC001"),
        pedido(items=[
            {"id_detalle": "B-D001", "id_producto": "B-P001", "cantidad": 3},
            {"id_detalle": "B-D002", "id_producto": "B-P002", "cantidad": 1},
        ]),
    ]
    hashes = [request_hash(v) for v in variantes]
    assert base not in hashes
    assert len(set(hashes)) == len(hashes)


def test_orden_de_lineas_es_parte_del_pedido():
    invertido = pedido(items=[
        {"id_detalle": "B-D002", "id_producto": "B-P002", "cantidad": 1},
        {"id_detalle": "B-D001", "id_producto": "B-P001", "cantidad": 2},
    ])
    assert request_hash(invertido) != request_hash(pedido())
