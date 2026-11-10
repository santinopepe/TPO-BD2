"""Inicialización no destructiva, compatible con Neo4j Community 5.26."""

from neo4j import Driver

from farmared.errores import CodigoError, ErrorDominio

ETIQUETAS = ("Cliente", "Venta", "Receta", "Farmaceutico", "Sucursal", "Producto")
RESTRICCIONES = {f"uq_{etiqueta.lower()}_id": etiqueta for etiqueta in ETIQUETAS}


def _compatible(restriccion, etiqueta):
    return (
        restriccion["entityType"] == "NODE"
        and restriccion["type"] == "UNIQUENESS"
        and restriccion["labelsOrTypes"] == [etiqueta]
        and restriccion["properties"] == ["id"]
    )


def preparar_grafo(driver: Driver) -> None:
    """Asegura seis restricciones de unicidad sin crear ni borrar datos.

    Usa la base predeterminada del driver (neo4j en el entorno del proyecto).
    El llamador conserva el driver. Propaga errores del motor, incluidos permisos
    y duplicados existentes. El DDL es incremental: una falla puede dejar algunas
    restricciones creadas; se puede reintentar. No reemplaza restricciones ajenas.
    """
    with driver.session() as sesion:
        actuales = sesion.run("SHOW CONSTRAINTS").data()
        for nombre, etiqueta in RESTRICCIONES.items():
            for actual in actuales:
                if actual["name"] == nombre and not _compatible(actual, etiqueta):
                    raise ErrorDominio(
                        CodigoError.INTEGRIDAD,
                        f"Restricción {nombre} incompatible; requiere migración explícita.",
                    )
        for nombre, etiqueta in RESTRICCIONES.items():
            sesion.run(
                f"CREATE CONSTRAINT {nombre} IF NOT EXISTS "
                f"FOR (n:{etiqueta}) REQUIRE n.id IS UNIQUE"
            ).consume()
        # IF NOT EXISTS también puede omitir por nombre; comprobar el resultado real.
        actuales = sesion.run("SHOW CONSTRAINTS").data()
        for etiqueta in ETIQUETAS:
            if not any(_compatible(actual, etiqueta) for actual in actuales):
                raise ErrorDominio(
                    CodigoError.INTEGRIDAD,
                    f"No se pudo asegurar unicidad de {etiqueta}.id; no se declara listo.",
                )
