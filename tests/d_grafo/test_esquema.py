from unittest.mock import MagicMock

import pytest
from neo4j.exceptions import AuthError, ServiceUnavailable

from farmared.errores import ErrorDominio
from farmared.grafo import preparar_grafo
from farmared.grafo.esquema import ETIQUETAS, RESTRICCIONES


def restricciones():
    return [dict(name=n, entityType="NODE", type="UNIQUENESS",
                 labelsOrTypes=[e], properties=["id"])
            for n, e in RESTRICCIONES.items()]


def driver_falso(actuales=None):
    driver = MagicMock()
    sesion = driver.session.return_value.__enter__.return_value
    sesion.run.return_value.data.return_value = restricciones() if actuales is None else actuales
    return driver, sesion


def test_seis_restricciones_y_repeticion_sin_escrituras_de_datos():
    driver, sesion = driver_falso()
    assert preparar_grafo(driver) is None
    preparar_grafo(driver)
    esperadas = [f"CREATE CONSTRAINT {n} IF NOT EXISTS FOR (n:{e}) REQUIRE n.id IS UNIQUE"
                 for n, e in RESTRICCIONES.items()]
    assert len(ETIQUETAS) == 6
    assert [c.args[0] for c in sesion.run.call_args_list] == (
        ["SHOW CONSTRAINTS", *esperadas, "SHOW CONSTRAINTS"] * 2
    )
    assert sesion.run.return_value.consume.call_count == 12
    driver.close.assert_not_called()


@pytest.mark.parametrize("error", [ServiceUnavailable("sin conexión"), AuthError("sin permiso")])
@pytest.mark.parametrize("etapa", ["session", "run", "consume"])
def test_errores_no_se_ocultan(error, etapa):
    driver, sesion = driver_falso()
    if etapa == "session":
        driver.session.side_effect = error
    elif etapa == "run":
        sesion.run.side_effect = error
    else:
        sesion.run.return_value.consume.side_effect = error
    with pytest.raises(type(error)):
        preparar_grafo(driver)


def test_nombre_incompatible_se_informa_antes_del_ddl():
    actuales = restricciones()
    actuales[0]["properties"] = ["otro_campo"]
    driver, sesion = driver_falso(actuales)
    with pytest.raises(ErrorDominio, match="incompatible"):
        preparar_grafo(driver)
    assert sesion.run.call_count == 1


def test_verifica_resultado_no_solo_if_not_exists():
    driver, _ = driver_falso([])
    with pytest.raises(ErrorDominio, match="no se declara listo"):
        preparar_grafo(driver)


def test_acepta_restricciones_equivalentes_con_otro_nombre():
    actuales = restricciones()
    for actual in actuales:
        actual["name"] = "existente_" + actual["name"]
    driver, _ = driver_falso(actuales)
    preparar_grafo(driver)
