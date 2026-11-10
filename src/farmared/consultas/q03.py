"""Q03: historial completo de ventas y recetas de un cliente."""

from datetime import date

from neo4j import Driver, READ_ACCESS
from neo4j.time import Date

from farmared.errores import CodigoError, ErrorDominio

CYPHER = """
MATCH (c:Cliente {id: $id_cliente})
CALL (c) {
    MATCH (c)-[:REALIZO]->(v:Venta)
    WITH DISTINCT v
    CALL (v) {
        OPTIONAL MATCH (v)-[i:CONTIENE]->(p:Producto)
        WITH i, p ORDER BY i.orden, i.id_detalle
        RETURN collect(CASE WHEN i IS NULL THEN null ELSE {
            id_detalle: i.id_detalle, orden: i.orden, id_producto: p.id,
            nombre_al_vender: i.nombre_al_vender, cantidad: i.cantidad,
            precio_unit: i.precio_unit, subtotal: i.subtotal
        } END) AS items
    }
    RETURN v.fecha AS fecha, 'VENTA' AS tipo_evento, v.id AS id_registro,
           v.estado AS estado, {
               tipo: v.tipo, total: v.total, medio_pago: v.medio_pago,
               id_receta: head([(v)-[:USA_RECETA]->(r:Receta) | r.id]),
               items: items
           } AS detalle
    UNION ALL
    MATCH (c)-[:TIENE_RECETA]->(r:Receta)
    WITH DISTINCT r
    RETURN r.fecha_emision AS fecha, 'RECETA' AS tipo_evento, r.id AS id_registro,
           r.estado AS estado, {
               tipo: r.tipo, medico: r.medico,
               dispensas_realizadas: r.dispensas_realizadas,
               dispensas_autorizadas: r.dispensas_autorizadas,
               proxima_dispensa: r.proxima_dispensa
           } AS detalle
}
RETURN fecha, tipo_evento, id_registro, estado, detalle
ORDER BY fecha, tipo_evento, id_registro
"""


def _fecha_comercial(valor, *, opcional=False):
    if valor is None and opcional:
        return None
    if isinstance(valor, Date):
        return valor.to_native()
    if type(valor) is date:
        return valor
    raise ErrorDominio(CodigoError.INTEGRIDAD, "Q03 requiere fechas comerciales de tipo date en el grafo.")


def q03_historial(driver: Driver, id_cliente: str) -> list[dict]:
    """Devuelve eventos cronológicos, con fechas datetime.date, sin filtrar estados.

    Usa la base predeterminada del driver. No escribe ni cierra el driver recibido.
    Propaga errores del motor; rechaza fechas ausentes o de un tipo incorrecto.
    """
    if not isinstance(id_cliente, str) or not id_cliente.strip():
        raise ErrorDominio(CodigoError.VALIDACION, "id_cliente debe ser un string no vacío.")
    with driver.session(default_access_mode=READ_ACCESS) as sesion:
        filas = sesion.execute_read(lambda tx: tx.run(CYPHER, id_cliente=id_cliente).data())
    for fila in filas:
        fila["fecha"] = _fecha_comercial(fila["fecha"])
        if fila["tipo_evento"] == "RECETA":
            fila["detalle"]["proxima_dispensa"] = _fecha_comercial(
                fila["detalle"]["proxima_dispensa"], opcional=True
            )
    return filas
