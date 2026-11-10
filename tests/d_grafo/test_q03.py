from copy import deepcopy
from datetime import datetime
from unittest.mock import MagicMock

import pytest
from neo4j import READ_ACCESS
from neo4j.exceptions import AuthError, ServiceUnavailable
from neo4j.time import Date, DateTime

from farmared.consultas.q03 import CYPHER, q03_historial
from farmared.errores import ErrorDominio


def driver_falso(filas):
    driver = MagicMock()
    sesion = driver.session.return_value.__enter__.return_value
    tx = MagicMock()
    tx.run.return_value.data.return_value = filas
    sesion.execute_read.side_effect = lambda funcion: funcion(tx)
    return driver, tx


@pytest.mark.parametrize("cliente", ["Q03-COMPLETO", "Q03-RECETAS", "Q03-VENTAS",
                                     "Q03-EMPATES", "Q03-VACIO", "Q03-INEXISTENTE"])
def test_resultados_exactos_y_conversion_de_fechas(casos_q03, cliente):
    esperado = casos_q03[cliente]
    filas = deepcopy(esperado)
    for fila in filas:
        fila["fecha"] = Date.from_native(fila["fecha"])
        if fila["tipo_evento"] == "RECETA" and fila["detalle"]["proxima_dispensa"]:
            fila["detalle"]["proxima_dispensa"] = Date.from_native(fila["detalle"]["proxima_dispensa"])
    driver, tx = driver_falso(filas)
    assert q03_historial(driver, cliente) == esperado
    driver.session.assert_called_once_with(default_access_mode=READ_ACCESS)
    tx.run.assert_called_once_with(CYPHER, id_cliente=cliente)
    driver.session.return_value.__exit__.assert_called_once()
    driver.close.assert_not_called()


@pytest.mark.parametrize("valor", [None, "", "  \t", 12, True, [], {}])
def test_id_invalido_se_rechaza_antes_de_conectar(valor):
    driver = MagicMock()
    with pytest.raises(ErrorDominio) as error:
        q03_historial(driver, valor)
    assert error.value.codigo == "VALIDACION"
    driver.session.assert_not_called()


def test_parametro_seguro_y_sin_normalizacion():
    entrada = " C'}) MATCH (n) DETACH DELETE n // "
    driver, tx = driver_falso([])
    assert q03_historial(driver, entrada) == []
    tx.run.assert_called_once_with(CYPHER, id_cliente=entrada)
    assert entrada not in CYPHER


@pytest.mark.parametrize("valor", [None, "2026-01-01", 123, datetime(2026, 1, 1),
                                    DateTime(2026, 1, 1)])
@pytest.mark.parametrize("campo", ["fecha", "proxima_dispensa"])
def test_fechas_invalidas_no_se_convierten(casos_q03, valor, campo):
    fila = deepcopy(casos_q03["Q03-RECETAS"][0])
    if campo == "fecha":
        fila["fecha"] = valor
    else:
        if valor is None:
            driver, _ = driver_falso([fila])
            assert q03_historial(driver, "C") == [fila]
            return
        fila["detalle"][campo] = valor
    driver, _ = driver_falso([fila])
    with pytest.raises(ErrorDominio) as error:
        q03_historial(driver, "C")
    assert error.value.codigo == "INTEGRIDAD"


@pytest.mark.parametrize("error", [AuthError("permiso"), ServiceUnavailable("conexión")])
@pytest.mark.parametrize("etapa", ["session", "run", "data"])
def test_errores_driver_se_propagan(error, etapa):
    driver, tx = driver_falso([])
    if etapa == "session":
        driver.session.side_effect = error
    elif etapa == "run":
        tx.run.side_effect = error
    else:
        tx.run.return_value.data.side_effect = error
    with pytest.raises(type(error)) as capturado:
        q03_historial(driver, "C")
    assert capturado.value is error
    if etapa != "session":
        driver.session.return_value.__exit__.assert_called_once()
