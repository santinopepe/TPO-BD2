from farmared.consultas.q11 import VISTA_INGRESOS_MENSUALES, pipeline_ingresos_mensuales
from farmared.errores import CodigoError, ErrorDominio


def preparar_consultas_mongo(db) -> None:
    from pymongo.errors import PyMongoError

    if db.name in {"admin", "config", "local"}:
        raise ErrorDominio(CodigoError.VALIDACION, "Elegir una base de aplicación, no una base interna MongoDB.")
    try:
        pipeline = pipeline_ingresos_mensuales()
        vista = next(db.list_collections(filter={"name": VISTA_INGRESOS_MENSUALES}), None)
        if vista is not None and (vista["type"] != "view" or vista["options"].get("viewOn") != "ventas"):
            raise ErrorDominio(CodigoError.INTEGRIDAD, "El nombre de la vista q11 está ocupado por otro objeto.")
        db.ventas.create_index([("estado", 1), ("fecha", 1)], name="ix_ventas_estado_fecha")
        if vista is None:
            db.create_collection(VISTA_INGRESOS_MENSUALES, viewOn="ventas", pipeline=pipeline)
        elif vista["options"].get("pipeline") != pipeline:
            db.command("collMod", VISTA_INGRESOS_MENSUALES, viewOn="ventas", pipeline=pipeline)
    except PyMongoError:
        raise ErrorDominio(CodigoError.INTEGRIDAD, "MongoDB no pudo preparar el índice y la vista de q11.") from None
