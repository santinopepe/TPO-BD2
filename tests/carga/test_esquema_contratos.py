"""Pruebas puras de las fronteras de inicialización y CLI."""

import argparse
from types import SimpleNamespace

import pytest

from farmared.errores import ErrorDominio
from farmared.esquema.base_mongo import preparar_mongo_base


@pytest.mark.parametrize("nombre", ["admin", "config", "local"])
def test_rechaza_bases_internas_sin_acceder_al_motor(nombre):
    with pytest.raises(ErrorDominio) as exc:
        preparar_mongo_base(SimpleNamespace(name=nombre))
    assert exc.value.codigo == "VALIDACION"


def test_cli_base_explicita_y_cierre_ante_fallo(monkeypatch):
    from farmared.cli import preparar_mongo

    cerrados = []
    destinos = []
    db = SimpleNamespace(client=SimpleNamespace(close=lambda: cerrados.append(True)))

    def conectar(config):
        destinos.append(config.mongo_db)
        return db

    def fallar(db):
        raise ErrorDominio("INTEGRIDAD", "conflicto de esquema")

    monkeypatch.setattr(preparar_mongo, "obtener_mongo", conectar)
    monkeypatch.setattr(preparar_mongo, "preparar_mongo_base", fallar)
    with pytest.raises(ErrorDominio):
        preparar_mongo.ejecutar(argparse.Namespace(base="farmared_test_a_cli"))
    assert destinos == ["farmared_test_a_cli"]
    assert cerrados == [True]
