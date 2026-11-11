def q01_productos_activos(db) -> list[dict]:
    return list(db.productos.aggregate([
        {"$match": {"activo": True}},
        {
            "$lookup": {
                "from": "proveedores",
                "localField": "id_proveedor",
                "foreignField": "_id",
                "as": "proveedor",
            }
        },
        {
            "$unwind": {
                "path": "$proveedor",
                "preserveNullAndEmptyArrays": True,
            }
        },
    ]))
