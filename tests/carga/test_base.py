"""Contratos puros: no requieren ni simulan garantías de una base de datos."""

import json
import os
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from farmared.clock import FixedClock, SystemClock, inicio_dia_utc
from farmared.config import Config
from farmared.contratos import MAX_IMPORTE_ARS, validar_importe_ars
from farmared.errores import CodigoError, ErrorDominio


def test_dia_comercial_cambia_a_las_tres_utc():
    antes = FixedClock(datetime(2026, 11, 9, 2, 59, 59, tzinfo=UTC))
    despues = FixedClock(datetime(2026, 11, 9, 3, tzinfo=UTC))
    assert antes.today() == date(2026, 11, 8)
    assert despues.today() == date(2026, 11, 9)
    assert inicio_dia_utc(despues.today()) == despues.now_utc()


def test_reloj_fijo_normaliza_un_instante_con_otro_offset():
    clock = FixedClock(datetime(2026, 11, 9, 0, tzinfo=timezone(timedelta(hours=-3))))
    assert clock.now_utc() == datetime(2026, 11, 9, 3, tzinfo=UTC)
    assert clock.now_utc().tzinfo is UTC


def test_reloj_fijo_rechaza_instante_sin_zona():
    with pytest.raises(ValueError, match="zona horaria"):
        FixedClock(datetime(2026, 11, 9))


def test_reloj_real_usa_el_instante_actual():
    antes = datetime.now(UTC)
    instante = SystemClock().now_utc()
    assert antes <= instante <= datetime.now(UTC)


@pytest.mark.parametrize("valor", [datetime(2026, 11, 9, tzinfo=UTC), "2026-11-09", None])
def test_inicio_dia_no_descarta_horas_ni_convierte_texto(valor):
    with pytest.raises(TypeError):
        inicio_dia_utc(valor)


def test_fecha_bisiesta():
    assert inicio_dia_utc(date(2024, 2, 29)) == datetime(2024, 2, 29, 3, tzinfo=UTC)


@pytest.mark.parametrize("valor", [0, 4999, MAX_IMPORTE_ARS])
def test_importe_valido(valor):
    assert validar_importe_ars(valor) == valor


@pytest.mark.parametrize("valor", [-1, MAX_IMPORTE_ARS + 1, 1.0, True, "5000", None])
def test_importe_invalido(valor):
    with pytest.raises(ErrorDominio) as exc:
        validar_importe_ars(valor)
    assert exc.value.codigo == "VALIDACION"


def test_config_no_requiere_neo4j_para_trabajo_independiente():
    config = Config.from_env({})
    assert config.mongo_db == "farmared"
    assert config.neo4j_password is None


def test_config_lee_mapping_sin_mutarlo():
    env = {"MONGO_DB": "farmared_test_a", "DB_TIMEOUT_MS": "2500"}
    previo = env.copy()
    config = Config.from_env(env)
    assert config.mongo_db == "farmared_test_a"
    assert config.db_timeout_ms == 2500
    assert env == previo


@pytest.mark.parametrize("env", [
    {"MONGO_DB": ""}, {"MONGO_DB": "otra.base"}, {"MONGO_DB": "a/b"},
    {"MONGO_URI": " "}, {"DB_TIMEOUT_MS": "no-numero"},
    {"DB_TIMEOUT_MS": "0"}, {"DB_TIMEOUT_MS": "300001"},
])
def test_config_invalida(env):
    with pytest.raises(ErrorDominio) as exc:
        Config.from_env(env)
    assert exc.value.codigo == "VALIDACION"


def test_repr_no_expone_password_ni_uri_con_credenciales():
    config = Config.from_env({
        "MONGO_URI": "mongodb://user:mongo-secreto@localhost/",
        "NEO4J_URI": "bolt://user:uri-secreto@localhost:7687",
        "NEO4J_PASSWORD": "neo-secreto",
    })
    assert "secreto" not in repr(config)


def test_error_conserva_contrato():
    error = ErrorDominio(CodigoError.NO_EXISTE, "No se encontró el cliente.")
    assert error.codigo == "NO_EXISTE"
    assert error.mensaje == "No se encontró el cliente."
    assert str(error) == "NO_EXISTE: No se encontró el cliente."


def cli(*args, cwd=None):
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    return subprocess.run(
        [sys.executable, "-m", "farmared", *args],
        capture_output=True, text=True, check=False, cwd=cwd, env=env,
    )


def test_cli_instalada_fuera_del_repo(tmp_path):
    resultado = cli("estado", cwd=tmp_path)
    assert resultado.returncode == 0, resultado.stderr
    payload = json.loads(resultado.stdout)
    assert payload["version"] == "0.1.0"
    assert payload["motores"] == "no_comprobados"
    assert payload["proyeccion"] == "no_comprobada"
    assert date.fromisoformat(payload["fecha_comercial"])


@pytest.mark.parametrize("comando,persona", [("q13", "C"), ("q14", "B")])
def test_comando_ausente_no_simula_exito(comando, persona):
    resultado = cli(comando)
    assert resultado.returncode == 3
    assert resultado.stdout == ""
    assert "NO_IMPLEMENTADO" in resultado.stderr
    assert f"Persona {persona}" in resultado.stderr
    assert cli("estado").returncode == 0


def test_cli_importa_solo_el_handler_elegido():
    script = """
import sys
import farmared.__main__ as router
assert 'farmared.cli.estado' not in sys.modules
assert 'pymongo' not in sys.modules
assert 'neo4j' not in sys.modules
assert router.main(['estado']) == 0
assert 'farmared.cli.estado' in sys.modules
assert 'pymongo' not in sys.modules
assert 'neo4j' not in sys.modules
"""
    resultado = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert resultado.returncode == 0, resultado.stderr


def test_cli_no_oculta_dependencia_rota_del_handler(monkeypatch):
    import farmared.__main__ as router

    def roto(nombre):
        raise ModuleNotFoundError("dependencia interna ausente", name="dependencia_interna")

    monkeypatch.setattr(router, "import_module", roto)
    with pytest.raises(ModuleNotFoundError, match="dependencia interna"):
        router.main(["estado"])


def test_cli_traduce_error_dominio(monkeypatch, capsys):
    import farmared.__main__ as router
    from types import SimpleNamespace

    def rechazado(args):
        raise ErrorDominio(CodigoError.VALIDACION, "Dato inválido.")

    monkeypatch.setattr(router, "import_module", lambda _: SimpleNamespace(ejecutar=rechazado))
    assert router.main(["estado"]) == 1
    assert capsys.readouterr().err == "VALIDACION: Dato inválido.\n"


def test_entrada_consola_y_argumentos_invalidos():
    ejecutable = Path(sys.executable).parent / "farmared"
    resultado = subprocess.run([str(ejecutable), "--version"], capture_output=True, text=True)
    assert resultado.returncode == 0
    assert resultado.stdout.strip() == "0.1.0"
    assert cli("comando-inexistente").returncode == 2
