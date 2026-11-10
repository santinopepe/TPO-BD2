"""Readiness explícita de cada motor, sin leer ni modificar datos de negocio."""

import argparse
import json

from farmared.config import Config
from farmared.conexiones import obtener_mongo, obtener_neo4j
from farmared.errores import CodigoError, ErrorDominio


def ejecutar(args: argparse.Namespace) -> int:
    config = Config.from_env()
    resultado = {"proyeccion": "no_comprobada"}
    fallo = False
    for motor in ("mongo", "neo4j") if args.motor == "ambos" else (args.motor,):
        try:
            if motor == "mongo":
                db = obtener_mongo(config)
                try:
                    resultado[motor] = {"estado": "listo", "base": db.name, "primario": True}
                finally:
                    db.client.close()
            else:
                from neo4j.exceptions import DriverError, Neo4jError

                with obtener_neo4j(config) as driver:
                    try:
                        with driver.session(database="neo4j") as sesion:
                            fila = sesion.run("RETURN 1 AS listo").single(strict=True)
                            if fila["listo"] != 1:
                                raise ErrorDominio(CodigoError.INTEGRIDAD, "Neo4j devolvió una respuesta inesperada.")
                    except (DriverError, Neo4jError):
                        raise ErrorDominio(CodigoError.CONEXION, "Neo4j no pudo ejecutar la comprobación de disponibilidad.") from None
                resultado[motor] = {"estado": "listo"}
        except ErrorDominio as error:
            fallo = True
            resultado[motor] = {"estado": "error", "codigo": error.codigo, "mensaje": error.mensaje}
    print(json.dumps(resultado, ensure_ascii=False))
    return 1 if fallo else 0
