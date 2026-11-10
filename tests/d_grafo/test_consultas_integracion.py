"""Resultados exactos con fixtures sintéticos; no son resultados del dataset CSV."""

import os

import pytest

from farmared.consultas.q04 import q04_clientes_con_recetas
from farmared.consultas.q10 import q10_clientes_sucursal
from farmared.grafo import preparar_grafo

pytestmark = pytest.mark.skipif(
    os.environ.get("FARMARED_TEST_GRAFO") != "1",
    reason="Activar FARMARED_TEST_GRAFO=1 para Neo4j aislado en Docker.",
)


@pytest.fixture(scope="module")
def datos(driver):
    preparar_grafo(driver)
    # Sin recetas o con solo una: nadie supera el umbral.
    with driver.session() as sesion:
        sesion.run("CREATE (:Cliente {id:'C00', nombre:'Cero', apellido:'Prueba'}), "
                   "(c:Cliente {id:'C01', nombre:'Una', apellido:'Prueba'}), "
                   "(c)-[:TIENE_RECETA]->(:Receta {id:'R01', estado:'Vigente'})").consume()
    assert q04_clientes_con_recetas(driver) == []
    assert q10_clientes_sucursal(driver, "S01") == []
    with driver.session() as sesion:
        sesion.run("""
            UNWIND $clientes AS dato
            CREATE (c:Cliente {id:dato.id, nombre:dato.nombre,
                               apellido:'Prueba', activo:dato.activo})
            WITH c, dato
            UNWIND range(1, dato.cantidad) AS numero
            CREATE (r:Receta {id:dato.id + '-R' + toString(numero),
                estado: ['Vigente', 'Completada', 'Vencida'][numero - 1],
                dispensas_realizadas: 3})
            CREATE (c)-[:TIENE_RECETA]->(r)
        """, clientes=[
            {"id": "C03", "nombre": "Tres", "activo": True, "cantidad": 3},
            {"id": "C02", "nombre": "Dos", "activo": True, "cantidad": 2},
            {"id": "C04", "nombre": "Inactiva", "activo": False, "cantidad": 2},
        ]).consume()
        # Un vínculo duplicado no debe aumentar el conteo de recetas.
        sesion.run("MATCH (c:Cliente {id:'C02'}), (r:Receta {id:'C02-R1'}) "
                   "CREATE (c)-[:TIENE_RECETA]->(r)").consume()
        sesion.run("""
            CREATE (s1:Sucursal {id:'S01'}), (s2:Sucursal {id:'S02'}),
                   (s3:Sucursal {id:'S03'}),
                   (f1:Farmaceutico {id:'F01', activo:true}),
                   (f2:Farmaceutico {id:'F02', activo:false}),
                   (f3:Farmaceutico {id:'F03', activo:true}),
                   (f4:Farmaceutico {id:'F04', activo:true}),
                   (f1)-[:TRABAJA_EN]->(s1), (f2)-[:TRABAJA_EN]->(s1),
                   (f3)-[:TRABAJA_EN]->(s2), (f4)-[:TRABAJA_EN]->(s3)
        """).consume()
        sesion.run("""
            UNWIND $ventas AS dato
            MATCH (f:Farmaceutico {id:dato.farmaceutico})
            MERGE (c:Cliente {id:dato.cliente})
            SET c.nombre = dato.cliente, c.apellido = 'Prueba', c.activo = false
            CREATE (v:Venta {id:dato.id, estado:dato.estado})
            CREATE (c)-[:REALIZO]->(v)-[:ATENDIDA_POR]->(f)
        """, ventas=[
            {"id": "V01", "cliente": "Q10-C01", "farmaceutico": "F01", "estado": "Completada"},
            {"id": "V02", "cliente": "Q10-C01", "farmaceutico": "F02", "estado": "Completada"},
            {"id": "V03", "cliente": "Q10-C02", "farmaceutico": "F02", "estado": "Completada"},
            {"id": "V04", "cliente": "Q10-C03", "farmaceutico": "F01", "estado": "Pendiente"},
            {"id": "V05", "cliente": "Q10-C04", "farmaceutico": "F02", "estado": "Anulada"},
            {"id": "V06", "cliente": "Q10-C05", "farmaceutico": "F03", "estado": "Completada"},
        ]).consume()
    return driver


def test_q04_resultado_exacto_orden_y_sin_duplicados(datos):
    assert q04_clientes_con_recetas(datos) == [
        {"id_cliente": "C03", "nombre": "Tres", "apellido": "Prueba", "cantidad": 3},
        {"id_cliente": "C02", "nombre": "Dos", "apellido": "Prueba", "cantidad": 2},
        {"id_cliente": "C04", "nombre": "Inactiva", "apellido": "Prueba", "cantidad": 2},
    ]


@pytest.mark.parametrize("id_cliente,cantidad", [
    ("C00", None), ("C01", None), ("C02", 2), ("C03", 3), ("C04", 2),
])
def test_q04_cero_una_dos_tres_recetas_e_inactivo(datos, id_cliente, cantidad):
    resultado = {fila["id_cliente"]: fila["cantidad"] for fila in q04_clientes_con_recetas(datos)}
    assert resultado.get(id_cliente) == cantidad


def test_q10_resultado_exacto_inactivos_y_todos_los_estados(datos):
    assert q10_clientes_sucursal(datos, "S01") == [
        {"id_cliente": c, "nombre": c, "apellido": "Prueba"}
        for c in ("Q10-C01", "Q10-C02", "Q10-C03", "Q10-C04")
    ]
    assert q10_clientes_sucursal(datos, "S02") == [
        {"id_cliente": "Q10-C05", "nombre": "Q10-C05", "apellido": "Prueba"},
    ]


@pytest.mark.parametrize("sucursal", ["S03", "INEXISTENTE", "S01'}) MATCH (n) RETURN n //"])
def test_q10_sin_ventas_inexistente_o_texto_cypher(datos, sucursal):
    assert q10_clientes_sucursal(datos, sucursal) == []


def test_consultas_no_modifican_el_grafo(datos):
    def snapshot():
        with datos.session() as sesion:
            nodos = sesion.run("MATCH (n) RETURN elementId(n) AS id, labels(n) AS etiquetas, "
                               "properties(n) AS propiedades ORDER BY id").data()
            relaciones = sesion.run(
                "MATCH (a)-[r]->(b) RETURN elementId(r) AS id, elementId(a) AS origen, "
                "elementId(b) AS destino, type(r) AS tipo, properties(r) AS propiedades ORDER BY id"
            ).data()
            return nodos, relaciones
    antes = snapshot()
    q04_clientes_con_recetas(datos)
    q10_clientes_sucursal(datos, "S01")
    assert snapshot() == antes

@pytest.fixture(scope="module")
def datos_q03(driver, casos_q03):
    from farmared.consultas.q03 import q03_historial

    preparar_grafo(driver)
    with driver.session() as sesion:
        for cliente, eventos in casos_q03.items():
            if cliente == "Q03-INEXISTENTE":
                continue
            sesion.run("CREATE (:Cliente {id:$id, activo:false})", id=cliente).consume()
            # Insertar en orden inverso para comprobar el orden impuesto por Cypher.
            for evento in reversed(eventos):
                if evento["tipo_evento"] != "RECETA":
                    continue
                propiedades = {**evento["detalle"], "id": evento["id_registro"],
                               "estado": evento["estado"], "fecha_emision": evento["fecha"]}
                sesion.run("MATCH (c:Cliente {id:$cliente}) CREATE (r:Receta) SET r=$props "
                           "CREATE (c)-[:TIENE_RECETA]->(r)",
                           cliente=cliente, props=propiedades).consume()
            for evento in reversed(eventos):
                if evento["tipo_evento"] != "VENTA":
                    continue
                detalle = evento["detalle"]
                props = {k: detalle[k] for k in ("tipo", "total", "medio_pago")}
                props.update(id=evento["id_registro"], estado=evento["estado"], fecha=evento["fecha"])
                sesion.run("MATCH (c:Cliente {id:$cliente}) CREATE (v:Venta) SET v=$props "
                           "CREATE (c)-[:REALIZO]->(v)", cliente=cliente, props=props).consume()
                if detalle["id_receta"]:
                    sesion.run("MATCH (v:Venta {id:$venta}), (r:Receta {id:$receta}) "
                               "CREATE (v)-[:USA_RECETA]->(r)",
                               venta=evento["id_registro"], receta=detalle["id_receta"]).consume()
                for item in reversed(detalle["items"]):
                    props_item = {k: v for k, v in item.items() if k != "id_producto"}
                    sesion.run("MATCH (v:Venta {id:$venta}) MERGE (p:Producto {id:$producto}) "
                               "SET p.nombre='Nombre actual', p.precio_unit=99999 "
                               "CREATE (v)-[i:CONTIENE]->(p) SET i=$props",
                               venta=evento["id_registro"], producto=item["id_producto"],
                               props=props_item).consume()
    # Evidencia de ejemplo obtenida de la función real y no de los datos esperados.
    print("\nEjemplo Q03 Neo4j:", repr(q03_historial(driver, "Q03-COMPLETO")))
    return driver


@pytest.mark.parametrize("cliente", ["Q03-COMPLETO", "Q03-RECETAS", "Q03-VENTAS",
                                     "Q03-EMPATES", "Q03-VACIO", "Q03-INEXISTENTE"])
def test_q03_historial_exacto_neo4j(datos_q03, casos_q03, cliente):
    from datetime import date
    from farmared.consultas.q03 import q03_historial

    resultado = q03_historial(datos_q03, cliente)
    assert resultado == casos_q03[cliente]
    assert all(type(fila["fecha"]) is date for fila in resultado)
    assert all(type(fila["detalle"]["proxima_dispensa"]) is date
               for fila in resultado if fila["tipo_evento"] == "RECETA"
               and fila["detalle"]["proxima_dispensa"] is not None)


def test_q03_no_escribe_y_parametriza(datos_q03):
    from farmared.consultas.q03 import q03_historial

    def snapshot():
        with datos_q03.session() as sesion:
            return (
                sesion.run("MATCH (n) RETURN elementId(n) AS id, properties(n) AS props "
                           "ORDER BY id").data(),
                sesion.run("MATCH ()-[r]->() RETURN elementId(r) AS id, properties(r) AS props "
                           "ORDER BY id").data(),
            )
    antes = snapshot()
    q03_historial(datos_q03, "Q03-COMPLETO")
    assert q03_historial(datos_q03, "C'}) MATCH (n) RETURN n //") == []
    assert snapshot() == antes
