from unittest.mock import MagicMock

import pytest
from neo4j import READ_ACCESS
from neo4j.exceptions import AuthError, ServiceUnavailable

from farmared.consultas.q04 import CYPHER, q04_clientes_con_recetas


@pytest.mark.parametrize("filas", [[], [
    {"id_cliente": "C03", "nombre": "Tres", "apellido": "Prueba", "cantidad": 3},
    {"id_cliente": "C02", "nombre": "Dos", "apellido": "Prueba", "cantidad": 2},
]])
def test_resultado_materializado_en_sesion_de_lectura(filas):
    driver = MagicMock()
    sesion = driver.session.return_value.__enter__.return_value
    tx = MagicMock()
    tx.run.return_value.data.return_value = filas
    sesion.execute_read.side_effect = lambda funcion: funcion(tx)
    assert q04_clientes_con_recetas(driver) == filas
    driver.session.assert_called_once_with(default_access_mode=READ_ACCESS)
    tx.run.assert_called_once_with(CYPHER)
    tx.run.return_value.data.assert_called_once_with()
    driver.session.return_value.__exit__.assert_called_once()
    driver.close.assert_not_called()


def test_semantica_cypher_sin_filtros_adicionales():
    assert " ".join(CYPHER.split()) == (
        "MATCH (c:Cliente)-[:TIENE_RECETA]->(r:Receta) "
        "WITH c, count(DISTINCT r) AS cantidad WHERE cantidad > 1 "
        "RETURN c.id AS id_cliente, c.nombre AS nombre, c.apellido AS apellido, cantidad "
        "ORDER BY cantidad DESC, id_cliente"
    )


@pytest.mark.parametrize("error", [ServiceUnavailable("sin conexión"), AuthError("sin permisos")])
@pytest.mark.parametrize("etapa", ["session", "run", "data"])
def test_errores_reales_se_propagan_y_se_cierra_la_sesion(error, etapa):
    driver = MagicMock()
    sesion = driver.session.return_value.__enter__.return_value
    tx = MagicMock()
    sesion.execute_read.side_effect = lambda funcion: funcion(tx)
    if etapa == "session":
        driver.session.side_effect = error
    elif etapa == "run":
        tx.run.side_effect = error
    else:
        tx.run.return_value.data.side_effect = error
    with pytest.raises(type(error)) as capturado:
        q04_clientes_con_recetas(driver)
    assert capturado.value is error
    if etapa != "session":
        driver.session.return_value.__exit__.assert_called_once()
