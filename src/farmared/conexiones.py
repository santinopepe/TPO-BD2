
from datetime import UTC
from time import monotonic, sleep
from typing import TYPE_CHECKING

from farmared.config import Config
from farmared.errores import CodigoError, ErrorDominio

if TYPE_CHECKING:
    from neo4j import Driver
    from pymongo.database import Database


def obtener_mongo(config: Config) -> "Database":
    """Devuelve Database con fechas UTC conscientes de zona y write concern majority.

    Espera primario de un replica set con sesiones. No inicializa esquema ni datos.
    El Database mantiene su cliente: usar db.client.start_session() y cerrarlo al salir.
    """
    import pymongo
    from pymongo.errors import PyMongoError
    from pymongo.write_concern import WriteConcern

    client = None
    try:
        client = pymongo.MongoClient(
            config.mongo_uri, appname="farmared", tz_aware=True, tzinfo=UTC,
            serverSelectionTimeoutMS=config.db_timeout_ms,
            connectTimeoutMS=config.db_timeout_ms, socketTimeoutMS=config.db_timeout_ms,
            timeoutMS=config.db_timeout_ms, w="majority",
        )
        limite = monotonic() + config.db_timeout_ms / 1000
        with pymongo.timeout(config.db_timeout_ms / 1000):
            while True:
                hello = client.admin.command("hello")
                if not hello.get("setName") or hello.get("logicalSessionTimeoutMinutes") is None:
                    raise ErrorDominio(CodigoError.INTEGRIDAD, "MongoDB requiere replica set con sesiones; no se modificó su configuración.")
                if hello.get("isWritablePrimary"):
                    return client.get_database(config.mongo_db, write_concern=WriteConcern("majority"))
                if monotonic() >= limite:
                    raise ErrorDominio(CodigoError.CONEXION, "MongoDB no tiene primario disponible dentro del plazo.")
                sleep(min(0.2, max(0, limite - monotonic())))
    except PyMongoError:
        if client is not None:
            client.close()
        raise ErrorDominio(CodigoError.CONEXION, "No se pudo conectar a MongoDB; revisar destino, replica set y credenciales.") from None
    except Exception:
        if client is not None:
            client.close()
        raise


def obtener_neo4j(config: Config) -> "Driver":
    """Devuelve un Driver con conectividad/autenticación verificadas; no sincroniza."""
    from neo4j import GraphDatabase
    from neo4j.exceptions import DriverError, Neo4jError

    if not config.neo4j_password:
        raise ErrorDominio(CodigoError.VALIDACION, "NEO4J_PASSWORD es obligatorio para conectar a Neo4j.")
    driver = None
    try:
        driver = GraphDatabase.driver(
            config.neo4j_uri, auth=(config.neo4j_user, config.neo4j_password),
            connection_timeout=config.db_timeout_ms / 1000,
            connection_acquisition_timeout=config.db_timeout_ms / 1000,
            max_transaction_retry_time=config.db_timeout_ms / 1000,
        )
        driver.verify_connectivity()
        return driver
    except (DriverError, Neo4jError, ValueError):
        if driver is not None:
            driver.close()
        raise ErrorDominio(CodigoError.CONEXION, "No se pudo conectar a Neo4j; revisar destino y credenciales.") from None
    except Exception:
        if driver is not None:
            driver.close()
        raise
