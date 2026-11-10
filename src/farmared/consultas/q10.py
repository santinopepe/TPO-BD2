"""Q10: clientes atendidos por profesionales de una sucursal."""

from neo4j import Driver, READ_ACCESS

CYPHER = """
MATCH (s:Sucursal {id: $id_sucursal})
      <-[:TRABAJA_EN]-(f:Farmaceutico)
      <-[:ATENDIDA_POR]-(v:Venta)
      <-[:REALIZO]-(c:Cliente)
RETURN DISTINCT c.id AS id_cliente, c.nombre AS nombre, c.apellido AS apellido
ORDER BY id_cliente
"""


def q10_clientes_sucursal(driver: Driver, id_sucursal: str) -> list[dict]:
    """Devuelve clientes distintos por la sucursal actual del farmacéutico.

    No filtra actividad ni estado de venta. El modelo no contempla traslados
    históricos. Sucursal inexistente o sin ventas devuelve []. Propaga errores
    del motor y conserva el driver del llamador.
    """
    with driver.session(default_access_mode=READ_ACCESS) as sesion:
        return sesion.execute_read(
            lambda tx: tx.run(CYPHER, id_sucursal=id_sucursal).data()
        )
