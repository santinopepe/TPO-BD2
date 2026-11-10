"""Conversión pura de documentos MongoDB a la proyección acordada."""

from collections.abc import Mapping
from datetime import date, datetime
from typing import get_args

from farmared import contratos as c
from farmared.clock import ZONA_COMERCIAL
from farmared.errores import CodigoError, ErrorDominio

ETIQUETAS = dict(clientes="Cliente", sucursales="Sucursal", farmaceuticos="Farmaceutico",
                 recetas="Receta", productos="Producto", ventas="Venta")
CAMPOS = {
    "clientes": ("nombre", "apellido", "activo"),
    "sucursales": ("nombre", "tipo"),
    "farmaceuticos": ("nombre", "apellido", "matricula", "activo"),
    "recetas": ("medico", "tipo", "fecha_emision", "proxima_dispensa", "estado",
                "dispensas_realizadas", "dispensas_autorizadas"),
    "productos": ("nombre", "categoria"),
    "ventas": ("fecha", "tipo", "estado", "medio_pago", "total"),
}
ENUMS = {("sucursales", "tipo"): c.TipoSucursal, ("recetas", "tipo"): c.TipoReceta,
         ("recetas", "estado"): c.EstadoReceta, ("ventas", "tipo"): c.TipoVenta,
         ("ventas", "estado"): c.EstadoVenta, ("ventas", "medio_pago"): c.MedioPago}
# tipo de relación -> (colección de destino, campo fuente, dirección entrante)
RELACIONES = {
    "farmaceuticos": {"TRABAJA_EN": ("sucursales", "id_sucursal", False)},
    "recetas": {"TIENE_RECETA": ("clientes", "id_cliente", True)},
    "ventas": {"REALIZO": ("clientes", "id_cliente", True),
               "ATENDIDA_POR": ("farmaceuticos", "id_farmaceutico", False),
               "USA_RECETA": ("recetas", "id_receta", False)},
}


def _error(campo):
    return ErrorDominio(CodigoError.VALIDACION, f"Documento de proyección inválido: {campo}.")


def _texto(valor, campo):
    if not isinstance(valor, str) or not valor.strip():
        raise _error(campo)
    return valor


def _entero(valor, campo, minimo=0, maximo=c.MAX_IMPORTE_ARS):
    # BSON Int64 es una subclase de int; bool no es un entero de negocio.
    if isinstance(valor, bool) or not isinstance(valor, int) or not minimo <= valor <= maximo:
        raise _error(campo)
    return int(valor)


def fecha_comercial(valor) -> date:
    """BSON datetime consciente de zona → día Buenos Aires; acepta date nativo.

    Rechaza datetime naive: obtener_mongo ya entrega UTC consciente de zona.
    """
    if isinstance(valor, datetime):
        if valor.tzinfo is None or valor.utcoffset() is None:
            raise _error("fecha sin zona horaria")
        return valor.astimezone(ZONA_COMERCIAL).date()
    if type(valor) is date:
        return valor
    raise _error("fecha comercial")


def mapear_documento(coleccion: str, documento: Mapping) -> dict:
    """Devuelve etiqueta, propiedades planas, referencias e items sin mutar la fuente.

    Valida los campos usados por el grafo, no reimplementa el validador MongoDB
    de los campos operacionales que se omiten. Requiere el estado autoritativo,
    nunca un parche. Opcionales ausentes se convierten a None.
    """
    if not isinstance(coleccion, str) or coleccion not in ETIQUETAS:
        raise _error("colección no proyectada")
    if not isinstance(documento, Mapping):
        raise _error("se requiere un documento")
    props = {"id": _texto(documento.get("_id"), "_id")}
    for campo in CAMPOS[coleccion]:
        valor = documento.get(campo)
        if campo in ("fecha", "fecha_emision", "proxima_dispensa"):
            valor = None if campo == "proxima_dispensa" and valor is None else fecha_comercial(valor)
        elif campo == "activo":
            if type(valor) is not bool:
                raise _error(campo)
        elif campo == "total":
            valor = c.validar_importe_ars(valor) if type(valor) is int else _entero(valor, campo)
        elif campo in ("dispensas_realizadas", "dispensas_autorizadas"):
            valor = _entero(valor, campo, 1 if campo == "dispensas_autorizadas" else 0, 3)
        else:
            valor = _texto(valor, campo)
            enum = ENUMS.get((coleccion, campo))
            if enum is not None and valor not in get_args(enum):
                raise _error(campo)
        props[campo] = valor
    referencias = {}
    for relacion, (_, campo, _) in RELACIONES.get(coleccion, {}).items():
        valor = documento.get(campo)
        referencias[relacion] = None if campo == "id_receta" and valor is None else _texto(valor, campo)
    items = []
    if coleccion == "ventas":
        fuente = documento.get("items")
        if not isinstance(fuente, list) or not fuente:
            raise _error("items debe ser una lista no vacía, como en MongoDB")
        vistos = set()
        for orden, item in enumerate(fuente):
            if not isinstance(item, Mapping):
                raise _error("item")
            id_detalle = _texto(item.get("id_detalle"), "id_detalle")
            if id_detalle in vistos:
                raise _error("id_detalle repetido en la venta")
            vistos.add(id_detalle)
            nombre = item.get("nombre_al_vender")
            if nombre is not None:
                nombre = _texto(nombre, "nombre_al_vender")
            items.append({"id_producto": _texto(item.get("id_producto"), "id_producto"),
                          "propiedades": {"id_detalle": id_detalle, "orden": orden,
                              "cantidad": _entero(item.get("cantidad"), "cantidad", 1),
                              "precio_unit": _entero(item.get("precio_unit"), "precio_unit"),
                              "subtotal": _entero(item.get("subtotal"), "subtotal"),
                              "nombre_al_vender": nombre}})
    return {"etiqueta": ETIQUETAS[coleccion], "propiedades": props,
            "referencias": referencias, "items": items}
