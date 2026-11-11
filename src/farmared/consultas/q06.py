from farmared.clock import Clock, inicio_dia_utc


def q06_recetas_prolongadas(db, clock: Clock) -> list[dict]:
    return list(db.recetas.aggregate([
        {
            "$match": {
                "tipo": "Tratamiento prolongado",
                "estado": "Vigente",
                "proxima_dispensa": {
                    "$type": "date",
                    "$lt": inicio_dia_utc(clock.today()),
                },
            }
        },
        {
            "$lookup": {
                "from": "clientes",
                "localField": "id_cliente",
                "foreignField": "_id",
                "as": "cliente",
            }
        },
        {
            "$unwind": {
                "path": "$cliente",
                "preserveNullAndEmptyArrays": True,
            }
        },
    ]))
