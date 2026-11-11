def q08_lotes_stock_bajo(db) -> list[dict]:
    return list(db.stock_lotes.aggregate([
        {"$match": {"unidades": {"$lt": 50}}},
        {
            "$lookup": {
                "from": "productos",
                "localField": "id_producto",
                "foreignField": "_id",
                "as": "producto",
            }
        },
        {"$unwind": {"path": "$producto", "preserveNullAndEmptyArrays": True}},
        {
            "$lookup": {
                "from": "proveedores",
                "localField": "producto.id_proveedor",
                "foreignField": "_id",
                "as": "proveedor",
            }
        },
        {"$unwind": {"path": "$proveedor", "preserveNullAndEmptyArrays": True}},
        {
            "$lookup": {
                "from": "sucursales",
                "localField": "id_sucursal",
                "foreignField": "_id",
                "as": "sucursal",
            }
        },
        {"$unwind": {"path": "$sucursal", "preserveNullAndEmptyArrays": True}},
    ]))
