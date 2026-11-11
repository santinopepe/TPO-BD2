def q02_ventas_pendientes(db) -> list[dict]:
    return list(db.ventas.aggregate([
        {"$match": {"estado": "Pendiente"}},
        {
            "$lookup": {
                "from": "farmaceuticos",
                "localField": "id_farmaceutico",
                "foreignField": "_id",
                "as": "farmaceutico",
            }
        },
        {"$unwind": {"path": "$farmaceutico", "preserveNullAndEmptyArrays": True}},
        {
            "$lookup": {
                "from": "sucursales",
                "localField": "farmaceutico.id_sucursal",
                "foreignField": "_id",
                "as": "sucursal",
            }
        },
        {"$unwind": {"path": "$sucursal", "preserveNullAndEmptyArrays": True}},
    ]))
