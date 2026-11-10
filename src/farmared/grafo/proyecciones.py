"""Escritura de agregados dentro de una transacción Neo4j del llamador."""

from collections.abc import Iterable, Mapping

from farmared.errores import CodigoError, ErrorDominio
from farmared.grafo.mapeos import CAMPOS, ETIQUETAS, RELACIONES, mapear_documento


def proyectar_documento(tx, coleccion: str, documento: Mapping) -> None:
    """Proyecta un documento; las dependencias deben existir completas en el grafo.

    No abre sesiones ni confirma. La excepción debe salir del callback execute_write
    o del contexto begin_transaction para que el llamador haga rollback completo.
    """
    proyectar_documentos(tx, [(coleccion, documento)])


def proyectar_documentos(tx, documentos: Iterable[tuple[str, Mapping]]) -> None:
    """Proyecta una unidad de trabajo con dependencias completas, en cualquier orden.

    Mapea todo antes de escribir; crea/actualiza todos los nodos, comprueba extremos
    y luego reemplaza solo las relaciones propiedad de cada agregado. No borra nodos.
    Requiere preparar_grafo previo. No capturar errores y confirmar parcialmente.
    """
    mapeados = [(coleccion, mapear_documento(coleccion, doc)) for coleccion, doc in documentos]
    identidades = [(c, m["propiedades"]["id"]) for c, m in mapeados]
    if len(identidades) != len(set(identidades)):
        raise ErrorDominio(CodigoError.VALIDACION, "Documento repetido en la unidad de proyección.")
    for _, mapa in mapeados:
        etiqueta = mapa["etiqueta"]
        tx.run(f"MERGE (n:{etiqueta} {{id:$id}}) SET n += $props",
               id=mapa["propiedades"]["id"], props=mapa["propiedades"]).consume()
    for coleccion, mapa in mapeados:
        for tipo, (destino, _, _) in RELACIONES.get(coleccion, {}).items():
            id = mapa["referencias"][tipo]
            if id is not None:
                _exigir_dependencia(tx, destino, id)
        for item in mapa["items"]:
            _exigir_dependencia(tx, "productos", item["id_producto"])
    for coleccion, mapa in mapeados:
        etiqueta = mapa["etiqueta"]
        id = mapa["propiedades"]["id"]
        for tipo, (destino, _, entrante) in RELACIONES.get(coleccion, {}).items():
            patron = f"(n)<-[r:{tipo}]-()" if entrante else f"(n)-[r:{tipo}]->()"
            tx.run(f"MATCH (n:{etiqueta} {{id:$id}}) MATCH {patron} DELETE r", id=id).consume()
            referencia = mapa["referencias"][tipo]
            if referencia is not None:
                relacion = f"(n)<-[:{tipo}]-(d)" if entrante else f"(n)-[:{tipo}]->(d)"
                resultado = tx.run(
                    f"MATCH (n:{etiqueta} {{id:$id}}), (d:{ETIQUETAS[destino]} {{id:$referencia}}) "
                    f"CREATE {relacion} RETURN count(*) AS cantidad", id=id, referencia=referencia,
                ).single()
                _exigir_uno(resultado)
        if coleccion == "ventas":
            tx.run("MATCH (v:Venta {id:$id})-[r:CONTIENE]->() DELETE r", id=id).consume()
            for item in mapa["items"]:
                resultado = tx.run(
                    "MATCH (v:Venta {id:$id}), (p:Producto {id:$producto}) "
                    "CREATE (v)-[r:CONTIENE]->(p) SET r=$props RETURN count(*) AS cantidad",
                    id=id, producto=item["id_producto"], props=item["propiedades"],
                ).single()
                _exigir_uno(resultado)


def _exigir_uno(resultado):
    if resultado is None or resultado["cantidad"] != 1:
        raise ErrorDominio(CodigoError.INTEGRIDAD, "No se pudo proyectar una relación con extremos únicos.")


def _exigir_dependencia(tx, coleccion, id):
    campos = [c for c in CAMPOS[coleccion] if c != "proxima_dispensa"]
    resultado = tx.run(
        f"MATCH (n:{ETIQUETAS[coleccion]} {{id:$id}}) "
        "WHERE all(campo IN $campos WHERE n[campo] IS NOT NULL) RETURN count(n) AS cantidad",
        id=id, campos=campos,
    ).single()
    if resultado is None or resultado["cantidad"] != 1:
        raise ErrorDominio(CodigoError.INTEGRIDAD, f"Dependencia ausente o incompleta: {coleccion}/{id}.")
