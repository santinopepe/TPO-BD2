"""Lecturas de la operación de venta, siempre dentro de la sesión transaccional."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from pymongo import ASCENDING

from farmared.clock import inicio_dia_utc


@dataclass(frozen=True)
class SnapshotVenta:
    """Documentos que habilitan (o no) la venta, tal como los vio este intento."""

    cliente: dict | None
    farmaceutico: dict | None
    sucursal: dict | None
    productos: dict[str, dict]
    receta: dict | None


def leer_snapshot(db, sesion, *, id_cliente: str, id_farmaceutico: str,
                  ids_productos: Iterable[str], id_receta: str | None) -> SnapshotVenta:
    """Lee cliente, farmacéutico, su sucursal actual, productos y receta indicada."""
    farmaceutico = db.farmaceuticos.find_one({"_id": id_farmaceutico}, session=sesion)
    id_sucursal = farmaceutico.get("id_sucursal") if farmaceutico else None
    ids = sorted(set(ids_productos))
    return SnapshotVenta(
        cliente=db.clientes.find_one({"_id": id_cliente}, session=sesion),
        farmaceutico=farmaceutico,
        sucursal=db.sucursales.find_one({"_id": id_sucursal}, session=sesion) if id_sucursal else None,
        productos={p["_id"]: p for p in db.productos.find({"_id": {"$in": ids}}, session=sesion)},
        receta=db.recetas.find_one({"_id": id_receta}, session=sesion) if id_receta else None,
    )


def leer_lotes_vigentes(db, sesion, id_sucursal: str, ids_productos: Iterable[str], hoy: date) -> list[dict]:
    """Lotes con unidades y no vencidos de la sucursal, en orden FEFO (usa ix_stock_lotes_fefo).

    El plan FEFO vuelve a filtrar y ordenar: esta consulta solo acota lo leído.
    """
    filtro = {
        "id_sucursal": id_sucursal,
        "id_producto": {"$in": sorted(set(ids_productos))},
        "unidades": {"$gt": 0},
        "vencimiento": {"$gte": inicio_dia_utc(hoy)},
    }
    return list(db.stock_lotes.find(filtro, session=sesion).sort([("vencimiento", ASCENDING), ("_id", ASCENDING)]))


def leer_venta(db, sesion, id_venta: str) -> dict | None:
    return db.ventas.find_one({"_id": id_venta}, session=sesion)
