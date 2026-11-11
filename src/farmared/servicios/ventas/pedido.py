"""Pedido de venta de q14: normalización y validación de forma, sin acceso a motores.

Solo valida lo que se puede decidir con el pedido en la mano. Existencia,
actividad, receta, precios y stock se validan contra el snapshot de MongoDB.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import get_args

from farmared.contratos import MAX_IMPORTE_ARS, MedioPago
from farmared.errores import CodigoError, ErrorDominio

CAMPOS_PEDIDO = frozenset({"id_venta", "id_cliente", "id_farmaceutico", "medio_pago", "items", "id_receta"})
OBLIGATORIOS_PEDIDO = ("id_venta", "id_cliente", "id_farmaceutico", "medio_pago", "items")
CAMPOS_ITEM = frozenset({"id_detalle", "id_producto", "cantidad"})
MEDIOS_PAGO = frozenset(get_args(MedioPago))


@dataclass(frozen=True)
class ItemPedido:
    id_detalle: str
    id_producto: str
    cantidad: int


@dataclass(frozen=True)
class PedidoVenta:
    """Pedido ya normalizado. `id_venta` es la identidad estable para reintentos."""

    id_venta: str
    id_cliente: str
    id_farmaceutico: str
    medio_pago: str
    items: tuple[ItemPedido, ...]
    id_receta: str | None = None


def id_detalle_generado(id_venta: str, posicion: int) -> str:
    """Id determinístico de la línea `posicion` (1-based) cuando el pedido no lo trae."""
    return f"{id_venta}-D{posicion}"


def _identificador(valor, campo: str, errores: list[str]) -> str | None:
    if type(valor) is not str or not valor.strip():
        errores.append(f"{campo} debe ser un string no vacío.")
        return None
    if valor != valor.strip():
        errores.append(f"{campo} no admite espacios al inicio/final; no se normaliza automáticamente.")
        return None
    return valor


def _cantidad(valor, campo: str, errores: list[str]) -> int | None:
    # bool es subclase de int y no es una cantidad; Int64 (BSON long de una pendiente) sí lo es.
    if isinstance(valor, bool) or not isinstance(valor, int) or not 1 <= valor <= MAX_IMPORTE_ARS:
        errores.append(f"{campo} debe ser un entero positivo.")
        return None
    return int(valor)


def normalizar_pedido(datos: Mapping) -> PedidoVenta:
    """Convierte el pedido de entrada en un `PedidoVenta` o rechaza con VALIDACION.

    Reúne todos los problemas de forma en un único error. Las líneas sin
    `id_detalle` reciben `<id_venta>-D<posición>`; luego se exige unicidad.
    """
    if not isinstance(datos, Mapping):
        raise ErrorDominio(CodigoError.VALIDACION, "El pedido debe ser un objeto con campos.")
    errores: list[str] = []
    desconocidos = sorted(map(str, set(datos) - CAMPOS_PEDIDO))
    if desconocidos:
        errores.append(f"Campos no admitidos en el pedido: {', '.join(desconocidos)}.")
    faltantes = [campo for campo in OBLIGATORIOS_PEDIDO if campo not in datos]
    if faltantes:
        errores.append(f"Faltan campos obligatorios: {', '.join(faltantes)}.")

    id_venta = _identificador(datos["id_venta"], "id_venta", errores) if "id_venta" in datos else None
    id_cliente = _identificador(datos["id_cliente"], "id_cliente", errores) if "id_cliente" in datos else None
    id_farmaceutico = (_identificador(datos["id_farmaceutico"], "id_farmaceutico", errores)
                       if "id_farmaceutico" in datos else None)
    id_receta = datos.get("id_receta")
    if id_receta is not None:
        id_receta = _identificador(id_receta, "id_receta", errores)

    medio_pago = datos.get("medio_pago")
    if "medio_pago" in datos and medio_pago not in MEDIOS_PAGO:
        errores.append(f"medio_pago debe ser uno de: {', '.join(sorted(MEDIOS_PAGO))}.")

    items: list[ItemPedido] = []
    crudos = datos.get("items")
    if "items" in datos:
        if isinstance(crudos, (str, bytes, Mapping)) or not isinstance(crudos, Sequence):
            errores.append("items debe ser una lista de líneas.")
        elif not crudos:
            errores.append("La venta debe tener al menos un ítem.")
        else:
            for posicion, crudo in enumerate(crudos, start=1):
                item = _normalizar_item(crudo, posicion, id_venta, errores)
                if item is not None:
                    items.append(item)
            vistos: set[str] = set()
            for item in items:
                if item.id_detalle in vistos:
                    errores.append(f"id_detalle repetido dentro de la venta: {item.id_detalle}.")
                vistos.add(item.id_detalle)

    if errores:
        raise ErrorDominio(CodigoError.VALIDACION, "Pedido de venta inválido: " + " ".join(errores))
    return PedidoVenta(
        id_venta=id_venta, id_cliente=id_cliente, id_farmaceutico=id_farmaceutico,
        medio_pago=medio_pago, items=tuple(items), id_receta=id_receta,
    )


def _normalizar_item(crudo, posicion: int, id_venta: str | None, errores: list[str]) -> ItemPedido | None:
    prefijo = f"items[{posicion}]"
    if not isinstance(crudo, Mapping):
        errores.append(f"{prefijo} debe ser un objeto con campos.")
        return None
    cantidad_errores = len(errores)
    desconocidos = sorted(map(str, set(crudo) - CAMPOS_ITEM))
    if desconocidos:
        errores.append(f"{prefijo}: campos no admitidos: {', '.join(desconocidos)}.")
    for campo in ("id_producto", "cantidad"):
        if campo not in crudo:
            errores.append(f"{prefijo}: falta {campo}.")
    id_producto = (_identificador(crudo["id_producto"], f"{prefijo}.id_producto", errores)
                   if "id_producto" in crudo else None)
    cantidad = _cantidad(crudo["cantidad"], f"{prefijo}.cantidad", errores) if "cantidad" in crudo else None
    if crudo.get("id_detalle") is not None:
        id_detalle = _identificador(crudo["id_detalle"], f"{prefijo}.id_detalle", errores)
    elif id_venta is not None:
        id_detalle = id_detalle_generado(id_venta, posicion)
    else:
        id_detalle = None  # Sin id_venta válido ya hay un error reportado.
    if len(errores) > cantidad_errores or id_detalle is None:
        return None
    return ItemPedido(id_detalle=id_detalle, id_producto=id_producto, cantidad=cantidad)
