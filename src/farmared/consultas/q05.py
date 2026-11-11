from datetime import timedelta

from farmared.clock import Clock, inicio_dia_utc


def q05_ventas_por_farmaceutico(db, clock: Clock) -> list[dict]:
    hoy = clock.today()
    inicio = inicio_dia_utc(hoy - timedelta(days=59))
    fin = inicio_dia_utc(hoy + timedelta(days=1))

    return list(db.farmaceuticos.aggregate([
        {"$match": {"activo": True}},
        {
            "$lookup": {
                "from": "ventas",
                "localField": "_id",
                "foreignField": "id_farmaceutico",
                "pipeline": [
                    {
                        "$match": {
                            "fecha": {"$gte": inicio, "$lt": fin},
                            "estado": {"$ne": "Anulada"},
                        }
                    },
                    {"$count": "cantidad_ventas"},
                ],
                "as": "resumen_ventas",
            }
        },
        {
            "$set": {
                "cantidad_ventas": {
                    "$ifNull": [
                        {"$arrayElemAt": ["$resumen_ventas.cantidad_ventas", 0]},
                        0,
                    ]
                }
            }
        },
        {"$unset": "resumen_ventas"},
    ]))
