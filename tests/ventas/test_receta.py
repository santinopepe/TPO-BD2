"""Pruebas puras de receta: exigencia, validación y transición de dispensa."""

from datetime import date

import pytest

from farmared.clock import inicio_dia_utc
from farmared.errores import ErrorDominio
from farmared.servicios.ventas.receta import requiere_receta, tipo_venta, transicion_receta, validar_receta

HOY = date(2026, 11, 10)


def receta(**cambios):
    base = {"_id": "B-RC001", "id_cliente": "B-C001", "tipo": "Tratamiento prolongado",
            "estado": "Vigente", "dispensas_autorizadas": 3, "dispensas_realizadas": 1,
            "proxima_dispensa": inicio_dia_utc(date(2026, 11, 1))}
    base.update(cambios)
    return base


def rechazo(receta_doc, id_receta="B-RC001", id_cliente="B-C001", requiere=True):
    with pytest.raises(ErrorDominio) as exc:
        validar_receta(receta_doc, id_receta, id_cliente, requiere)
    return exc.value.codigo


# --- Exigencia y tipo ------------------------------------------------------

@pytest.mark.parametrize(("condiciones", "esperado"), [
    (["Venta libre"], False),
    (["Venta libre", "Venta libre"], False),
    (["Venta libre", "Bajo receta"], True),
    (["Bajo receta archivada"], True),
])
def test_requiere_receta_si_algun_producto_la_exige(condiciones, esperado):
    assert requiere_receta([{"condicion_venta": c} for c in condiciones]) is esperado


def test_tipo_de_venta_derivado():
    assert tipo_venta(True) == "Con receta"
    assert tipo_venta(False) == "Venta libre"


# --- Validación ------------------------------------------------------------

def test_receta_valida_no_rechaza():
    validar_receta(receta(), "B-RC001", "B-C001", True)


def test_venta_libre_sin_receta_no_rechaza():
    validar_receta(None, None, "B-C001", False)


def test_venta_libre_con_receta_se_rechaza_para_no_gastar_dispensa():
    assert rechazo(receta(), requiere=False) == "VALIDACION"


def test_producto_bajo_receta_sin_receta():
    assert rechazo(None, id_receta=None) == "RECETA_INVALIDA"


def test_receta_inexistente():
    assert rechazo(None) == "NO_EXISTE"


def test_receta_de_otro_cliente():
    assert rechazo(receta(id_cliente="B-C002")) == "RECETA_INVALIDA"


@pytest.mark.parametrize("estado", ["Completada", "Vencida"])
def test_receta_no_vigente(estado):
    assert rechazo(receta(estado=estado)) == "RECETA_INVALIDA"


def test_receta_vigente_sin_dispensas_disponibles():
    assert rechazo(receta(dispensas_realizadas=3)) == "RECETA_INVALIDA"


@pytest.mark.parametrize("cambio", [{"dispensas_realizadas": None}, {"dispensas_autorizadas": "3"},
                                    {"dispensas_realizadas": -1}, {"dispensas_autorizadas": 0}])
def test_contadores_corruptos_son_integridad(cambio):
    assert rechazo(receta(**cambio)) == "INTEGRIDAD"


# --- Transición ------------------------------------------------------------

@pytest.mark.parametrize("tipo", ["Simple", "Archivada"])
def test_simple_y_archivada_se_completan_con_su_unica_dispensa(tipo):
    r = receta(tipo=tipo, dispensas_autorizadas=1, dispensas_realizadas=0, proxima_dispensa=None)
    assert transicion_receta(r, HOY) == {"dispensas_realizadas": 1, "estado": "Completada", "proxima_dispensa": None}


def test_prolongado_con_dispensas_restantes_mueve_proxima_30_dias():
    assert transicion_receta(receta(dispensas_realizadas=1), HOY) == {
        "dispensas_realizadas": 2, "estado": "Vigente",
        "proxima_dispensa": inicio_dia_utc(date(2026, 12, 10)),
    }


def test_prolongado_primera_dispensa():
    r = receta(dispensas_realizadas=0, proxima_dispensa=None)
    assert transicion_receta(r, HOY)["proxima_dispensa"] == inicio_dia_utc(date(2026, 12, 10))


def test_prolongado_ultima_dispensa_se_completa():
    assert transicion_receta(receta(dispensas_realizadas=2), HOY) == {
        "dispensas_realizadas": 3, "estado": "Completada", "proxima_dispensa": None,
    }


def test_proxima_dispensa_es_inicio_de_dia_comercial_en_utc():
    proxima = transicion_receta(receta(), HOY)["proxima_dispensa"]
    assert proxima.isoformat() == "2026-12-10T03:00:00+00:00"


def test_tipo_desconocido_es_integridad():
    with pytest.raises(ErrorDominio) as exc:
        transicion_receta(receta(tipo="Magistral"), HOY)
    assert exc.value.codigo == "INTEGRIDAD"
