"""Materializa documentos del snapshot CSV sin reproducir operaciones históricas."""

from collections import defaultdict
from copy import deepcopy
from typing import get_args

from farmared.carga.formatos import CLAVES
from farmared.carga.modelos import DatasetValidado
from farmared.contratos import ColeccionNegocio, validar_importe_ars


def _traza(fila, huella):
    return {"huella": huella, "archivo": fila.archivo, "fila": fila.fila}


def transformar_mongo(validado: DatasetValidado) -> dict[str, list[dict]]:
    documentos = {nombre: [] for nombre in get_args(ColeccionNegocio)}
    profesionales = {f.datos["id_farmaceutico"]: f.datos["id_sucursal"] for f in validado.filas["farmaceuticos"]}
    detalles = defaultdict(list)
    for fila in validado.filas["detalle_ventas"]:
        item = deepcopy(fila.datos)
        id_venta = item.pop("id_venta")
        item["subtotal"] = validar_importe_ars(item["cantidad"] * item["precio_unit"])
        item["importacion"] = _traza(fila, validado.huella)
        detalles[id_venta].append(item)
    for nombre in documentos:
        for fila in validado.filas[nombre]:
            doc = deepcopy(fila.datos)
            doc["_id"] = doc.pop(CLAVES[nombre])
            doc["importacion"] = _traza(fila, validado.huella)
            if nombre == "ventas":
                aplicada = doc["estado"] == "Completada"
                doc.update({
                    "id_sucursal": profesionales[doc["id_farmaceutico"]],
                    "items": deepcopy(detalles[doc["_id"]]),
                    "stock_aplicado": aplicada,
                    "receta_aplicada": aplicada and doc["id_receta"] is not None,
                    "origen": "csv",
                    "trazabilidad_lotes": "desconocida" if aplicada else "no_aplicada",
                })
                for item in doc["items"]:
                    item["asignaciones_lotes"] = None if aplicada else []
                if doc["estado"] == "Pendiente":
                    doc["fecha_creacion_pendiente"] = doc["fecha"]
            documentos[nombre].append(doc)
    return documentos
