"""Q04: clientes con más de una receta registrada."""

from neo4j import Driver, READ_ACCESS

CYPHER = """
MATCH (c:Cliente)-[:TIENE_RECETA]->(r:Receta)
WITH c, count(DISTINCT r) AS cantidad
WHERE cantidad > 1
RETURN c.id AS id_cliente, c.nombre AS nombre, c.apellido AS apellido, cantidad
ORDER BY cantidad DESC, id_cliente
"""


def q04_clientes_con_recetas(driver: Driver) -> list[dict]:
    """Cuenta recetas distintas, sin filtrar estados ni clientes inactivos.

    Usa la base predeterminada del driver. Conserva el driver del llamador y
    propaga errores del motor; una lista vacía solo significa que no hubo filas.
    """
    with driver.session(default_access_mode=READ_ACCESS) as sesion:
        return sesion.execute_read(lambda tx: tx.run(CYPHER).data())
