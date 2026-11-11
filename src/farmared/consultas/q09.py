"""q09: ventas de tipo Venta libre con total menor a $5000, excepto anuladas."""


def q09_ventas_libres(db) -> list[dict]:
    return list(db.ventas.find({
        "tipo": "Venta libre",
        "total": {"$lt": 5000},
        "estado": {"$ne": "Anulada"},
    }))
