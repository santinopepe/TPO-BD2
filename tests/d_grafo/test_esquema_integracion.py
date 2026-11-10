"""Integraci?n opt-in: contenedor exclusivo, sin base ni vol?menes compartidos."""

import os

import pytest
from neo4j.exceptions import ConstraintError

from farmared.grafo import preparar_grafo
from farmared.grafo.esquema import ETIQUETAS

pytestmark = pytest.mark.skipif(
    os.environ.get("FARMARED_TEST_GRAFO") != "1",
    reason="Activar FARMARED_TEST_GRAFO=1; requiere Docker e imagen Neo4j del Compose local.",
)


def test_restricciones_idempotencia_preservacion_y_detalles(driver):
    with driver.session() as sesion:
        sesion.run("CREATE (v:Venta {id:'v'}), (p:Producto {id:'p'}), "
                   "(v)-[:CONTIENE {id_detalle:'d1', orden:0}]->(p), "
                   "(v)-[:CONTIENE {id_detalle:'d2', orden:1}]->(p)").consume()
        preparar_grafo(driver)
        antes = sesion.run("SHOW CONSTRAINTS").data()
        preparar_grafo(driver)
        assert sesion.run("SHOW CONSTRAINTS").data() == antes
        assert len(antes) == 6
        assert {tuple(r["labelsOrTypes"]) for r in antes} == {(e,) for e in ETIQUETAS}
        assert all(r["properties"] == ["id"] and r["type"] == "UNIQUENESS" for r in antes)
        assert sesion.run("MATCH (n) RETURN count(n) AS n").single()["n"] == 2
        assert sesion.run("MATCH (:Venta)-[r:CONTIENE]->(:Producto) "
                          "RETURN r.id_detalle AS id ORDER BY id").value() == ["d1", "d2"]
        for etiqueta in ETIQUETAS:
            sesion.run(f"CREATE (:{etiqueta} {{id:'duplicado'}})").consume()
            with pytest.raises(ConstraintError):
                sesion.run(f"CREATE (:{etiqueta} {{id:'duplicado'}})").consume()
