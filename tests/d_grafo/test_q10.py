from unittest.mock import MagicMock

import pytest
from neo4j import READ_ACCESS
from neo4j.exceptions import AuthError, ServiceUnavailable

from farmared.consultas.q10 import CYPHER, q10_clientes_sucursal


@pytest.mark.parametrize("filas", [[], [
    {"id_cliente": "C01", "nombre": "Ana", "apellido": "Prueba"},
    {"id_cliente": "C02", "nombre": "Luis", "apellido": "Prueba"},
]])
def test_resultado_materializado_en_sesion_de_lectura(filas):
    driver = MagicMock()
    sesion = driver.session.return_value.__enter__.return_value
    tx = MagicMock()
    tx.run.return_value.data.return_value = filas
    sesion.execute_read.side_effect = lambda funcion: funcion(tx)
    assert q10_clientes_sucursal(driver, "S01") == filas
    driver.session.assert_called_once_with(default_access_mode=READ_ACCESS)
    tx.run.assert_called_once_with(CYPHER, id_sucursal="S01")
    tx.run.return_value.data.assert_called_once_with()
    driver.session.return_value.__exit__.assert_called_once()
    driver.close.assert_not_called()


def test_parametro_no_se_interpreta_como_cypher():
    driver = MagicMock()
    sesion = driver.session.return_value.__enter__.return_value
    tx = MagicMock()
    sesion.execute_read.side_effect = lambda funcion: funcion(tx)
    entrada = "S01'}) MATCH (n) DETACH DELETE n //"
    q10_clientes_sucursal(driver, entrada)
    tx.run.assert_called_once_with(CYPHER, id_sucursal=entrada)
    assert entrada not in tx.run.call_args.args[0]


def test_semantica_cypher_sin_filtros_adicionales():
    assert " ".join(CYPHER.split()) == (
        "MATCH (s:Sucursal {id: $id_sucursal}) "
        "<-[:TRABAJA_EN]-(f:Farmaceutico) "
        "<-[:ATENDIDA_POR]-(v:Venta) <-[:REALIZO]-(c:Cliente) "
        "RETURN DISTINCT c.id AS id_cliente, c.nombre AS nombre, c.apellido AS apellido "
        "ORDER BY id_cliente"
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
        q10_clientes_sucursal(driver, "S01")
    assert capturado.value is error
    if etapa != "session":
        driver.session.return_value.__exit__.assert_called_once()
