from farmared.clock import ZONA_COMERCIAL
from farmared.errores import CodigoError, ErrorDominio

VISTA_INGRESOS_MENSUALES = "ingresos_mensuales_farmaceutico"


def pipeline_ingresos_mensuales(ahora="$$NOW") -> list[dict]:
    inicio = {"$dateTrunc": {"date": ahora, "unit": "month", "timezone": ZONA_COMERCIAL.key}}
    fin = {"$dateAdd": {"startDate": inicio, "unit": "month", "amount": 1,
                        "timezone": ZONA_COMERCIAL.key}}
    return [
        {
            "$match": {
                "estado": "Completada",
                "$expr": {"$and": [{"$gte": ["$fecha", inicio]}, {"$lt": ["$fecha", fin]}]},
            }
        },
        {"$group": {"_id": "$id_farmaceutico", "ingresos_totales": {"$sum": "$total"}}},
        {
            "$lookup": {
                "from": "farmaceuticos",
                "localField": "_id",
                "foreignField": "_id",
                "as": "farmaceutico",
            }
        },
        {"$unwind": {"path": "$farmaceutico", "preserveNullAndEmptyArrays": True}},
    ]


def q11_ingresos_mensuales(db) -> list[dict]:
    vista = next(db.list_collections(filter={"name": VISTA_INGRESOS_MENSUALES}), None)
    if vista is None or vista["type"] != "view" or vista["options"].get("viewOn") != "ventas":
        raise ErrorDominio(CodigoError.INTEGRIDAD, "La vista de q11 no está preparada; ejecutar preparar-mongo.")
    return list(db[VISTA_INGRESOS_MENSUALES].find())
