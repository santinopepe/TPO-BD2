"""Prepara Neo4j y procesa una tanda recuperable del outbox existente."""

from neo4j.exceptions import DriverError, Neo4jError
from pymongo.errors import PyMongoError

from farmared.conexiones import obtener_neo4j
from farmared.errores import ErrorDominio
from farmared.grafo.esquema import preparar_grafo
from farmared.proyeccion.consumidor import sincronizar


def sincronizar_consola(consola):
    db = None
    pendientes = None
    try:
        db = consola._mongo()
        pendientes = db.outbox.count_documents({"procesado": False})
        # Comparte el lock predeterminado de la CLI; no depende de la base ni cwd.
        consola.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with obtener_neo4j(consola.config) as driver:
            preparar_grafo(driver)
            return sincronizar(db, driver, consola.lock_path, max_eventos=500)
    except (ErrorDominio, PyMongoError, Neo4jError, DriverError, OSError) as error:
        codigo = error.codigo if isinstance(error, ErrorDominio) else "SYNC_ERROR"
        mensaje = error.mensaje if isinstance(error, ErrorDominio) else "No se pudo completar la sincronización. Revisá la conexión, los permisos y el esquema de Neo4j."
        return {"estado": "error", "procesados": 0, "pendientes_observados": pendientes,
                "fallidos": [{"codigo": codigo, "causa": mensaje}], "limite_alcanzado": False}
    finally:
        if db is not None:
            db.client.close()
