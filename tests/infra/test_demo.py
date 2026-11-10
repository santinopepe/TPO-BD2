"""Guardas y cierre de recursos; estos dobles no prueban persistencia."""

from types import SimpleNamespace

import pytest
from pymongo.errors import OperationFailure

from farmared import demo
from farmared.config import Config
from farmared.errores import ErrorDominio


@pytest.mark.parametrize("base", ["admin", "config", "local", "farmared", "farmared_demo_", "Farmared_demo_uno"])
def test_no_admite_base_ajena_sin_conectar(monkeypatch, base):
    def prohibido(_):
        pytest.fail("No debe conectar antes de validar el destino")

    monkeypatch.setattr(demo, "obtener_mongo", prohibido)
    with pytest.raises(ErrorDominio) as exc:
        demo.resetear_demo_mongo(Config(mongo_db=base), confirmar_base=base)
    assert exc.value.codigo == "VALIDACION"


def test_confirmacion_incorrecta_no_conecta(monkeypatch):
    monkeypatch.setattr(demo, "obtener_mongo", lambda _: pytest.fail("No debe conectar"))
    with pytest.raises(ErrorDominio, match="no coincide"):
        demo.resetear_demo_mongo(Config(mongo_db="farmared_demo_uno"), confirmar_base="farmared_demo_dos")


@pytest.mark.parametrize("modo", ["preview", "ok", "motor", "escritor", "salida"])
def test_plan_orden_y_limpieza_de_recursos(monkeypatch, modo):
    pasos = []
    base = "farmared_demo_fixture"

    def borrar(nombre):
        assert nombre == base
        pasos.append("drop")
        if modo == "motor":
            raise OperationFailure("detalle-nativo-privado")

    cliente = SimpleNamespace(nodes={("localhost", 37017)}, drop_database=borrar,
                              close=lambda: pasos.append("close"))
    db = SimpleNamespace(client=cliente, list_collection_names=lambda: ["nueva"] if modo == "escritor" else [])
    monkeypatch.setattr(demo, "obtener_mongo", lambda _: db)

    def anunciar(destino):
        assert destino == {"motor": "mongodb", "base": base, "servidores": [{"host": "localhost", "puerto": 37017}]}
        pasos.append("anuncio")
        if modo == "salida":
            raise BrokenPipeError("No se pudo mostrar el destino")

    config = Config(mongo_db=base, mongo_uri="mongodb://usuario:secreto@localhost/")
    if modo in {"motor", "escritor"}:
        with pytest.raises(ErrorDominio) as exc:
            demo.resetear_demo_mongo(config, confirmar_base=base, antes_de_borrar=anunciar)
        assert exc.value.codigo == "INTEGRIDAD" and "detalle-nativo" not in str(exc.value)
    elif modo == "salida":
        with pytest.raises(BrokenPipeError):
            demo.resetear_demo_mongo(config, confirmar_base=base, antes_de_borrar=anunciar)
        assert "drop" not in pasos
    else:
        resultado = demo.resetear_demo_mongo(config, confirmar_base=base if modo == "ok" else None, antes_de_borrar=anunciar)
        assert resultado["ejecutado"] is (modo == "ok")
        assert resultado["proyeccion"] == "no_comprobada" and resultado["neo4j"] == "sin_reiniciar"
        assert "secreto" not in repr(resultado)
    assert pasos[-1] == "close"
    if "drop" in pasos:
        assert pasos.index("anuncio") < pasos.index("drop")


@pytest.mark.parametrize("nombre", ["a" * 64, "é" * 32])
def test_nombre_largo_se_rechaza_antes_del_motor(nombre):
    with pytest.raises(ErrorDominio, match="63 bytes"):
        Config(mongo_db=nombre)


def test_nombre_hasta_63_bytes():
    assert Config(mongo_db="a" * 63).mongo_db == "a" * 63
    assert Config(mongo_db="é" * 31).mongo_db == "é" * 31
