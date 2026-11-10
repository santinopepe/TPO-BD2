"""Nombres y tipos compartidos; no implementa reglas de B, C ni D."""

from datetime import datetime
from typing import Any, Literal, TypedDict

from farmared.errores import CodigoError, ErrorDominio

ColeccionNegocio = Literal[
    "clientes", "sucursales", "farmaceuticos", "proveedores",
    "productos", "stock_lotes", "recetas", "ventas",
]
ColeccionProyectada = Literal[
    "clientes", "sucursales", "farmaceuticos", "productos", "recetas", "ventas",
]
EstadoVenta = Literal["Completada", "Pendiente", "Anulada"]
TipoVenta = Literal["Venta libre", "Con receta"]
CondicionVenta = Literal["Venta libre", "Bajo receta", "Bajo receta archivada"]
EstadoReceta = Literal["Vigente", "Completada", "Vencida"]
TipoReceta = Literal["Simple", "Archivada", "Tratamiento prolongado"]
MedioPago = Literal["Efectivo", "Débito", "Crédito", "Transferencia", "Obra social"]
OrigenVenta = Literal["csv", "servicio"]
TipoSucursal = Literal["Farmacia", "Droguería"]
TipoProveedor = Literal["Laboratorio", "Droguería"]
CargoFarmaceutico = Literal["Director Técnico", "Farmacéutico"]
ObraSocial = Literal["OSDE", "Swiss Medical", "PAMI", "IOMA", "Galeno", "Sin cobertura"]

MAX_IMPORTE_ARS = 2**63 - 1


class EntidadAfectada(TypedDict):
    coleccion: ColeccionProyectada
    id: str


class EventoOutbox(TypedDict):
    _id: str
    afectadas: list[EntidadAfectada]
    procesado: bool
    creado_en: datetime


class ResultadoEscritura(TypedDict):
    documento: dict[str, Any]
    eventos: list[str]
    reutilizada: bool


def validar_importe_ars(valor: int) -> int:
    """Acepta enteros ARS no negativos representables en BSON int64.

    También se aplica a subtotales y totales calculados, antes de persistir.
    La conversión desde texto CSV corresponde al lector de datasets.
    """
    if type(valor) is not int or not 0 <= valor <= MAX_IMPORTE_ARS:
        raise ErrorDominio(
            CodigoError.VALIDACION,
            f"El importe debe ser un entero ARS entre 0 y {MAX_IMPORTE_ARS}.",
        )
    return valor
