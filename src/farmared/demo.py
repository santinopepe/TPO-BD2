"""Reset exclusivo de bases de demo MongoDB, separado del seed idempotente."""

from pymongo.errors import PyMongoError

from farmared.config import Config
from farmared.conexiones import obtener_mongo
from farmared.errores import CodigoError, ErrorDominio

PREFIJO_DEMO = "farmared_demo_"


def resetear_demo_mongo(config: Config, *, confirmar_base: str | None = None, antes_de_borrar=None) -> dict:
    """Vista previa sin confirmación; borra solo la base exacta si coincide.

    El llamador debe pausar escritores y proyección. No borra Neo4j, volúmenes,
    fuentes ni regenera/carga datos. Esta función abre/cierra su propio cliente.
    """
    base = config.mongo_db
    if not base.startswith(PREFIJO_DEMO) or base == PREFIJO_DEMO:
        raise ErrorDominio(CodigoError.VALIDACION, "reset-demo solo admite bases con prefijo farmared_demo_ y sufijo no vacío.")
    if confirmar_base is not None and confirmar_base != base:
        raise ErrorDominio(CodigoError.VALIDACION, "La confirmación no coincide exactamente con la base destino; no se borró nada.")
    db = obtener_mongo(config)
    try:
        # Nodos resueltos por el driver: nunca se imprime la URI o sus credenciales.
        destino = {"motor": "mongodb", "base": base,
                   "servidores": [{"host": h, "puerto": p} for h, p in sorted(db.client.nodes)]}
        resultado = {
            "destino": destino, "alcance": "solo_mongo", "accion": "eliminar_base_completa",
            "confirmacion_requerida": base, "ejecutado": False, "proyeccion": "no_comprobada",
            "neo4j": "sin_reiniciar",
        }
        if confirmar_base is None:
            return {**resultado, "modo": "vista_previa"}
        if antes_de_borrar is not None:
            antes_de_borrar(destino)  # Si la salida falla, no comenzar el borrado.
        db.client.drop_database(base)
        if db.list_collection_names():
            raise ErrorDominio(CodigoError.INTEGRIDAD, "La base tiene colecciones tras el reset; verificar escritores concurrentes. No se declara vacía.")
        return {**resultado, "modo": "confirmado", "ejecutado": True}
    except PyMongoError:
        raise ErrorDominio(CodigoError.INTEGRIDAD, "No se pudo verificar el reset de demo. Puede haberse aplicado; inspeccionar el destino antes de reintentar.") from None
    finally:
        db.client.close()
