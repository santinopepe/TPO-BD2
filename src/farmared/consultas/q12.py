from datetime import timedelta

from farmared.clock import Clock, inicio_dia_utc


def q12_clientes_sin_ventas(db, clock: Clock) -> list[dict]:
    hoy = clock.today()
    dia = 28 if hoy.month == 2 and hoy.day == 29 else hoy.day
    inicio = inicio_dia_utc(hoy.replace(year=hoy.year - 1, day=dia))
    fin = inicio_dia_utc(hoy + timedelta(days=1))

    return list(db.clientes.aggregate([
        {
            "$lookup": {
                "from": "ventas",
                "localField": "_id",
                "foreignField": "id_cliente",
                "pipeline": [
                    {"$match": {"fecha": {"$gte": inicio, "$lt": fin}}},
                    {"$limit": 1},
                ],
                "as": "ventas_recientes",
            }
        },
        {"$match": {"ventas_recientes.0": {"$exists": False}}},
        {"$unset": "ventas_recientes"},
    ]))
