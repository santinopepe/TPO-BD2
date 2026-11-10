"""Pruebas de contratos/errores; los dobles no prueban garantías de los motores."""

import argparse
import json
import os
import stat
from dataclasses import replace
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace

import pytest

from farmared.config import Config
from farmared.conexiones import obtener_mongo, obtener_neo4j
from farmared.errores import ErrorDominio


def test_mongo_uri_invalida_no_expone_credenciales():
    config = Config(mongo_uri="invalid://usuario:secreto@example.test")
    with pytest.raises(ErrorDominio) as exc:
        obtener_mongo(config)
    assert exc.value.codigo == "CONEXION"
    assert "secreto" not in str(exc.value)


def test_neo4j_requiere_secreto_solo_al_pedir_conexion():
    with pytest.raises(ErrorDominio, match="NEO4J_PASSWORD"):
        obtener_neo4j(Config())


def test_neo4j_uri_invalida_no_expone_credenciales():
    config = Config(neo4j_uri="invalid://usuario:secreto@example.test", neo4j_password="privado")
    with pytest.raises(ErrorDominio) as exc:
        obtener_neo4j(config)
    assert exc.value.codigo == "CONEXION"
    assert "secreto" not in str(exc.value)
    assert "privado" not in str(exc.value)


def test_cierra_mongo_si_es_standalone(monkeypatch):
    import pymongo

    class Client:
        cerrado = False
        admin = SimpleNamespace(command=lambda _: {"isWritablePrimary": True})

        def close(self):
            self.cerrado = True

    client = Client()
    monkeypatch.setattr(pymongo, "MongoClient", lambda *a, **k: client)
    with pytest.raises(ErrorDominio) as exc:
        obtener_mongo(Config())
    assert exc.value.codigo == "INTEGRIDAD"
    assert client.cerrado


def test_no_acepta_secundario_como_ready(monkeypatch):
    import pymongo
    import farmared.conexiones as conexiones

    class Client:
        cerrado = False
        admin = SimpleNamespace(command=lambda _: {
            "setName": "rs0", "logicalSessionTimeoutMinutes": 30,
            "isWritablePrimary": False,
        })

        def close(self):
            self.cerrado = True

    client = Client()
    tiempos = iter([0, 1])
    monkeypatch.setattr(pymongo, "MongoClient", lambda *a, **k: client)
    monkeypatch.setattr(conexiones, "monotonic", lambda: next(tiempos))
    with pytest.raises(ErrorDominio, match="primario"):
        obtener_mongo(replace(Config(), db_timeout_ms=1))
    assert client.cerrado


def test_cierra_neo4j_si_falla_conectividad(monkeypatch):
    from neo4j import GraphDatabase
    from neo4j.exceptions import ServiceUnavailable

    class Driver:
        cerrado = False

        def verify_connectivity(self):
            raise ServiceUnavailable("no disponible")

        def close(self):
            self.cerrado = True

    driver = Driver()
    monkeypatch.setattr(GraphDatabase, "driver", lambda *a, **k: driver)
    with pytest.raises(ErrorDominio):
        obtener_neo4j(Config(neo4j_password="local-prueba"))
    assert driver.cerrado


def test_salud_mongo_no_intenta_neo4j(monkeypatch, capsys):
    from farmared.cli import salud

    cerrado = []
    db = SimpleNamespace(name="farmared_test_a", client=SimpleNamespace(close=lambda: cerrado.append(True)))
    monkeypatch.setattr(salud.Config, "from_env", lambda: Config())
    monkeypatch.setattr(salud, "obtener_mongo", lambda _: db)

    def prohibido(_):
        pytest.fail("No debe conectar a Neo4j")

    monkeypatch.setattr(salud, "obtener_neo4j", prohibido)
    assert salud.ejecutar(argparse.Namespace(motor="mongo")) == 0
    assert json.loads(capsys.readouterr().out)["mongo"]["primario"] is True
    assert cerrado == [True]


def test_salud_ambos_informa_fallos_independientes(monkeypatch, capsys):
    from farmared.cli import salud

    llamados = []
    monkeypatch.setattr(salud.Config, "from_env", lambda: Config())

    def fallo_mongo(_):
        llamados.append("mongo")
        raise ErrorDominio("CONEXION", "MongoDB no disponible.")

    def fallo_neo4j(_):
        llamados.append("neo4j")
        raise ErrorDominio("CONEXION", "Neo4j no disponible.")

    monkeypatch.setattr(salud, "obtener_mongo", fallo_mongo)
    monkeypatch.setattr(salud, "obtener_neo4j", fallo_neo4j)
    assert salud.ejecutar(argparse.Namespace(motor="ambos")) == 1
    salida = json.loads(capsys.readouterr().out)
    assert salida["mongo"]["estado"] == salida["neo4j"]["estado"] == "error"
    assert salida["proyeccion"] == "no_comprobada"
    assert llamados == ["mongo", "neo4j"]


@pytest.fixture
def preparador_env():
    ruta = Path(__file__).resolve().parents[2] / "infra/preparar_env.py"
    spec = spec_from_file_location("preparar_env", ruta)
    modulo = module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_preparar_env_no_pisa_archivo(tmp_path, preparador_env):
    (tmp_path / ".env.example").write_bytes(b"NEO4J_PASSWORD=\nMONGO_DB=prueba\n")
    assert preparador_env.preparar_env(tmp_path) is True
    contenido = (tmp_path / ".env").read_bytes()
    linea = next(l for l in contenido.splitlines() if l.startswith(b"NEO4J_PASSWORD="))
    assert len(linea.split(b"=", 1)[1]) >= 8
    assert preparador_env.preparar_env(tmp_path) is False
    assert (tmp_path / ".env").read_bytes() == contenido


@pytest.mark.skipif(os.name != "posix", reason="0600 es un modo POSIX; Windows usa ACL, no st_mode.")
def test_preparar_env_restringe_permisos_posix(tmp_path, preparador_env):
    (tmp_path / ".env.example").write_bytes(b"NEO4J_PASSWORD=\n")
    assert preparador_env.preparar_env(tmp_path) is True
    assert stat.S_IMODE((tmp_path / ".env").stat().st_mode) == 0o600


def test_enlazar_env_compose_idempotente(tmp_path, preparador_env):
    (tmp_path / ".env.example").write_bytes(b"NEO4J_PASSWORD=\n")
    preparador_env.preparar_env(tmp_path)
    contenido = (tmp_path / ".env").read_bytes()
    (tmp_path / "infra").mkdir()
    try:
        preparador_env.enlazar_env_compose(tmp_path)
    except OSError as error:
        if os.name == "nt" and getattr(error, "winerror", None) == 1314:
            pytest.skip("Windows requiere privilegio de symlink o modo desarrollador; no se usa copia insegura.")
        raise
    preparador_env.enlazar_env_compose(tmp_path)
    assert (tmp_path / "infra/.env").resolve() == tmp_path / ".env"
    assert (tmp_path / "infra/.env").read_bytes() == contenido



def test_preparar_env_no_pisa_env_de_infra_preexistente(tmp_path):
    ruta = Path(__file__).resolve().parents[2] / "infra/preparar_env.py"
    spec = spec_from_file_location("preparar_env", ruta)
    modulo = module_from_spec(spec)
    spec.loader.exec_module(modulo)
    (tmp_path / "infra").mkdir()
    existente = tmp_path / "infra/.env"
    existente.write_text("configuracion previa")
    with pytest.raises(RuntimeError, match="se conserva"):
        modulo.enlazar_env_compose(tmp_path)
    assert existente.read_text() == "configuracion previa"
