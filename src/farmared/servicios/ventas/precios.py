"""Valorización de una venta con precios vigentes del catálogo, en enteros ARS."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from farmared.contratos import MAX_IMPORTE_ARS, validar_importe_ars
from farmared.errores import CodigoError, ErrorDominio
from farmared.servicios.ventas.pedido import ItemPedido


@dataclass(frozen=True)
class LineaValorizada:
    """Línea con el precio capturado al vender; ese precio queda como histórico."""

    id_detalle: str
    id_producto: str
    cantidad: int
    precio_unit: int
    subtotal: int


def valorizar(items: Iterable[ItemPedido],
              productos: Mapping[str, Mapping]) -> tuple[tuple[LineaValorizada, ...], int]:
    """Captura `productos[id].precio_unit` en cada línea y devuelve (líneas, total).

    subtotal = cantidad × precio_unit; total = suma de subtotales. Todo entero
    ARS representable en int64; un desborde se rechaza con VALIDACION.
    """
    lineas: list[LineaValorizada] = []
    total = 0
    for item in items:
        producto = productos.get(item.id_producto)
        if producto is None:
            raise ErrorDominio(CodigoError.NO_EXISTE, f"No existe el producto {item.id_producto}.")
        precio = producto.get("precio_unit")
        if type(precio) is not int or not 0 <= precio <= MAX_IMPORTE_ARS:
            raise ErrorDominio(CodigoError.INTEGRIDAD, f"El producto {item.id_producto} no tiene un precio entero ARS válido.")
        subtotal = validar_importe_ars(item.cantidad * precio)
        total = validar_importe_ars(total + subtotal)
        lineas.append(LineaValorizada(item.id_detalle, item.id_producto, item.cantidad, precio, subtotal))
    return tuple(lineas), total
