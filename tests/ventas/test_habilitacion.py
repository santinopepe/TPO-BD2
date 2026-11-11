"""Pruebas puras de habilitación: cliente, farmacéutico, sucursal y productos."""

import pytest

from farmared.errores import ErrorDominio
from farmared.servicios.ventas.habilitacion import (
    validar_cliente,
    validar_farmaceutico,
    validar_productos,
    validar_sucursal,
)


def codigo(funcion, *args):
    with pytest.raises(ErrorDominio) as exc:
        funcion(*args)
    return exc.value.codigo


# --- Cliente ---------------------------------------------------------------

def test_cliente_activo_habilita():
    validar_cliente({"_id": "B-C001", "activo": True}, "B-C001")


def test_cliente_inexistente_o_inactivo():
    assert codigo(validar_cliente, None, "B-C001") == "NO_EXISTE"
    assert codigo(validar_cliente, {"_id": "B-C001", "activo": False}, "B-C001") == "VALIDACION"


def test_cliente_sin_marca_activo_no_se_asume_activo():
    assert codigo(validar_cliente, {"_id": "B-C001"}, "B-C001") == "VALIDACION"


# --- Farmacéutico ----------------------------------------------------------

def test_farmaceutico_activo_devuelve_su_sucursal():
    assert validar_farmaceutico({"_id": "B-F001", "activo": True, "id_sucursal": "B-S001"}, "B-F001") == "B-S001"


def test_farmaceutico_inexistente_inactivo_o_sin_sucursal():
    assert codigo(validar_farmaceutico, None, "B-F001") == "NO_EXISTE"
    assert codigo(validar_farmaceutico, {"activo": False, "id_sucursal": "B-S001"}, "B-F001") == "VALIDACION"
    assert codigo(validar_farmaceutico, {"activo": True, "id_sucursal": None}, "B-F001") == "INTEGRIDAD"


# --- Sucursal --------------------------------------------------------------

def test_farmacia_activa_habilita():
    validar_sucursal({"_id": "B-S001", "tipo": "Farmacia", "activo": True}, "B-S001")


def test_drogueria_no_vende_aunque_este_activa():
    assert codigo(validar_sucursal, {"tipo": "Droguería", "activo": True}, "B-S009") == "VALIDACION"


def test_farmacia_inactiva_no_vende():
    assert codigo(validar_sucursal, {"tipo": "Farmacia", "activo": False}, "B-S001") == "VALIDACION"


def test_sucursal_referenciada_inexistente_es_integridad():
    assert codigo(validar_sucursal, None, "B-S404") == "INTEGRIDAD"


# --- Productos -------------------------------------------------------------

CATALOGO = {
    "B-P001": {"activo": True},
    "B-P002": {"activo": True},
    "B-P012": {"activo": False},
    "B-P013": {"activo": False},
}


def test_productos_activos_habilitan_aunque_se_repitan():
    validar_productos(CATALOGO, ["B-P001", "B-P002", "B-P001"])


def test_productos_inexistentes_se_informan_todos():
    with pytest.raises(ErrorDominio) as exc:
        validar_productos(CATALOGO, ["B-P001", "B-P998", "B-P999"])
    assert exc.value.codigo == "NO_EXISTE"
    assert "B-P998" in exc.value.mensaje and "B-P999" in exc.value.mensaje


def test_productos_inactivos_se_informan_todos():
    with pytest.raises(ErrorDominio) as exc:
        validar_productos(CATALOGO, ["B-P012", "B-P001", "B-P013"])
    assert exc.value.codigo == "VALIDACION"
    assert "B-P012" in exc.value.mensaje and "B-P013" in exc.value.mensaje
    assert "B-P001" not in exc.value.mensaje


def test_inexistencia_tiene_prioridad_sobre_inactividad():
    assert codigo(validar_productos, CATALOGO, ["B-P012", "B-P999"]) == "NO_EXISTE"
