"""Habilitación de una venta según los documentos leídos en el snapshot.

Funciones puras: reciben el documento (o None si no existe) y rechazan con
ErrorDominio. No consultan el ABM de clientes (q13): leen el estado persistido.
"""

from collections.abc import Iterable, Mapping

from farmared.errores import CodigoError, ErrorDominio


def validar_cliente(cliente: Mapping | None, id_cliente: str) -> None:
    if cliente is None:
        raise ErrorDominio(CodigoError.NO_EXISTE, f"No existe el cliente {id_cliente}.")
    if cliente.get("activo") is not True:
        raise ErrorDominio(CodigoError.VALIDACION, f"El cliente {id_cliente} está dado de baja.")


def validar_farmaceutico(farmaceutico: Mapping | None, id_farmaceutico: str) -> str:
    """Devuelve el `id_sucursal` del farmacéutico: allí se vende y se descuenta stock."""
    if farmaceutico is None:
        raise ErrorDominio(CodigoError.NO_EXISTE, f"No existe el farmacéutico {id_farmaceutico}.")
    if farmaceutico.get("activo") is not True:
        raise ErrorDominio(CodigoError.VALIDACION, f"El farmacéutico {id_farmaceutico} no está activo.")
    id_sucursal = farmaceutico.get("id_sucursal")
    if type(id_sucursal) is not str or not id_sucursal:
        raise ErrorDominio(CodigoError.INTEGRIDAD, f"El farmacéutico {id_farmaceutico} no tiene sucursal asignada.")
    return id_sucursal


def validar_sucursal(sucursal: Mapping | None, id_sucursal: str) -> None:
    """Solo vende una sucursal de tipo Farmacia y activa; la droguería tiene stock central."""
    if sucursal is None:
        raise ErrorDominio(CodigoError.INTEGRIDAD, f"La sucursal {id_sucursal} del farmacéutico no existe.")
    if sucursal.get("tipo") != "Farmacia":
        raise ErrorDominio(CodigoError.VALIDACION, f"La sucursal {id_sucursal} es {sucursal.get('tipo')}; solo vende una Farmacia.")
    if sucursal.get("activo") is not True:
        raise ErrorDominio(CodigoError.VALIDACION, f"La sucursal {id_sucursal} no está activa.")


def validar_productos(productos: Mapping[str, Mapping], ids: Iterable[str]) -> None:
    """Todos los productos pedidos deben existir y estar activos; informa todos los problemas."""
    pedidos = sorted(set(ids))
    faltantes = [i for i in pedidos if i not in productos]
    if faltantes:
        raise ErrorDominio(CodigoError.NO_EXISTE, f"No existen los productos: {', '.join(faltantes)}.")
    inactivos = [i for i in pedidos if productos[i].get("activo") is not True]
    if inactivos:
        raise ErrorDominio(CodigoError.VALIDACION, f"Productos discontinuados/inactivos: {', '.join(inactivos)}.")
