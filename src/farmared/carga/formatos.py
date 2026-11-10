"""Formato de los nueve CSV oficiales; sin inferencia de tipos ni normalización silenciosa."""

import re
from datetime import date
from typing import get_args

from farmared import contratos as c
from farmared.clock import inicio_dia_utc

CAMPOS = {
    "clientes": "id_cliente,nombre,apellido,dni,email,telefono,ciudad,provincia,obra_social,nro_afiliado,activo",
    "sucursales": "id_sucursal,nombre,tipo,direccion,ciudad,provincia,telefono,activo",
    "farmaceuticos": "id_farmaceutico,nombre,apellido,matricula,cargo,id_sucursal,activo",
    "proveedores": "id_proveedor,razon_social,cuit,tipo,ciudad,provincia,telefono,activo",
    "productos": "id_producto,nombre,principio_activo,categoria,presentacion,condicion_venta,precio_unit,id_proveedor,activo",
    "stock_lotes": "id_lote,id_producto,id_sucursal,nro_lote,unidades,vencimiento",
    "recetas": "id_receta,id_cliente,medico,matricula_medico,fecha_emision,tipo,dispensas_autorizadas,dispensas_realizadas,proxima_dispensa,estado",
    "ventas": "id_venta,id_cliente,id_farmaceutico,id_receta,fecha,tipo,medio_pago,total,estado",
    "detalle_ventas": "id_detalle,id_venta,id_producto,cantidad,precio_unit",
}
CAMPOS = {nombre: tuple(campos.split(",")) for nombre, campos in CAMPOS.items()}
CLAVES = {nombre: campos[0] for nombre, campos in CAMPOS.items()}
NULOS = {
    "clientes": {"email", "telefono", "nro_afiliado"}, "sucursales": {"telefono"},
    "proveedores": {"telefono"}, "productos": {"principio_activo"},
    "recetas": {"proxima_dispensa"}, "ventas": {"id_receta"},
}
FECHAS = {"stock_lotes": {"vencimiento"}, "recetas": {"fecha_emision", "proxima_dispensa"}, "ventas": {"fecha"}}
ENTEROS = {
    "productos": {"precio_unit": (0, c.MAX_IMPORTE_ARS)},
    "stock_lotes": {"unidades": (0, c.MAX_IMPORTE_ARS)},
    "recetas": {"dispensas_autorizadas": (1, 3), "dispensas_realizadas": (0, 3)},
    "ventas": {"total": (0, c.MAX_IMPORTE_ARS)},
    "detalle_ventas": {"cantidad": (1, c.MAX_IMPORTE_ARS), "precio_unit": (0, c.MAX_IMPORTE_ARS)},
}
ENUMS = {
    ("clientes", "obra_social"): c.ObraSocial, ("sucursales", "tipo"): c.TipoSucursal,
    ("farmaceuticos", "cargo"): c.CargoFarmaceutico, ("proveedores", "tipo"): c.TipoProveedor,
    ("productos", "condicion_venta"): c.CondicionVenta, ("recetas", "tipo"): c.TipoReceta,
    ("recetas", "estado"): c.EstadoReceta, ("ventas", "tipo"): c.TipoVenta,
    ("ventas", "estado"): c.EstadoVenta, ("ventas", "medio_pago"): c.MedioPago,
}


def convertir(tabla: str, campo: str, texto: str):
    """ValueError contiene solo una razón; el lector adjunta archivo/fila/campo."""
    if texto == "":
        if campo in NULOS.get(tabla, ()):
            return None
        raise ValueError("Campo obligatorio vacío.")
    if texto.strip() != texto or not texto.strip():
        raise ValueError("Espacios al inicio/final o texto vacío; no se normaliza automáticamente.")
    if campo == "activo":
        if texto not in {"True", "False"}:
            raise ValueError("Booleano inválido; se requiere True o False.")
        return texto == "True"
    if campo in ENTEROS.get(tabla, {}):
        if not re.fullmatch(r"-?[0-9]+", texto):
            raise ValueError("Se requiere un entero decimal, sin float, separadores ni espacios.")
        minimo, maximo = ENTEROS[tabla][campo]
        # Limitar magnitud antes de int(), sin convertir vía float ni exceder su límite de dígitos.
        magnitud = texto.lstrip("-").lstrip("0") or "0"
        if len(magnitud) > 19:
            raise ValueError(f"Entero fuera del rango {minimo}..{maximo}.")
        valor = int(("-" if texto.startswith("-") else "") + magnitud)
        if not minimo <= valor <= maximo:
            raise ValueError(f"Entero fuera del rango {minimo}..{maximo}.")
        return valor
    if campo in FECHAS.get(tabla, ()):
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", texto):
            raise ValueError("Se requiere fecha ISO YYYY-MM-DD.")
        try:
            return inicio_dia_utc(date.fromisoformat(texto))
        except ValueError:
            raise ValueError("Fecha inexistente en el calendario.") from None
    if (tabla, campo) in ENUMS and texto not in get_args(ENUMS[tabla, campo]):
        raise ValueError("Valor fuera del enum acordado.")
    if campo == "dni" and not re.fullmatch(r"[0-9]+", texto):
        raise ValueError("DNI debe contener dígitos ASCII, conservado como string.")
    if campo == "cuit" and not re.fullmatch(r"[0-9]{2}-[0-9]{8}-[0-9]", texto):
        raise ValueError("CUIT debe tener formato XX-XXXXXXXX-X; no se verifica checksum ficticio.")
    return texto
