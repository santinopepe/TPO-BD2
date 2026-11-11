def q07_top_productos(db) -> list[dict]:
    return list(db.ventas.aggregate([
        {"$match": {"estado": "Completada"}},
        {"$unwind": "$items"},
        {
            "$group": {
                "_id": "$items.id_producto",
                "unidades_vendidas": {"$sum": "$items.cantidad"},
            }
        },
        {"$sort": {"unidades_vendidas": -1, "_id": 1}},
        {"$limit": 5},
        {
            "$lookup": {
                "from": "productos",
                "localField": "_id",
                "foreignField": "_id",
                "as": "producto",
            }
        },
        {"$unwind": {"path": "$producto", "preserveNullAndEmptyArrays": True}},
    ]))
