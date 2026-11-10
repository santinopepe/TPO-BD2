"""Rutas independientes de la CLI sin motores ni módulos B/C/D."""

import json
import subprocess
import sys

import pytest

from farmared.__main__ import main


def test_setup_completo_pendiente_no_importa_drivers(tmp_path):
    script = """
import importlib.abc, sys
class Bloquear(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'pymongo', 'neo4j'}: raise AssertionError(fullname)
sys.meta_path.insert(0, Bloquear())
from farmared.__main__ import main
raise SystemExit(main(sys.argv[1:]))
"""
    r = subprocess.run([sys.executable, "-c", script, "setup", "--base", "farmared_demo_prueba",
                        "--directorio", str(tmp_path)], capture_output=True, text=True)
    assert r.returncode == 3, r.stderr
    v = json.loads(r.stdout)
    assert v["setup"] == "pendiente_integracion" and v["escrituras"] == 0
    assert {p["responsable"] for p in v["pendientes"]} == {"C", "D"}
    assert "NO_IMPLEMENTADO" in r.stderr


def test_setup_fuentes_invalidas_no_conecta(tmp_path, monkeypatch, capsys):
    import farmared.conexiones as conexiones
    monkeypatch.setattr(conexiones, "obtener_mongo", lambda _: pytest.fail("No debe conectar"))
    assert main(["setup", "--solo-mongo", "--base", "farmared_demo_prueba", "--directorio", str(tmp_path)]) == 1
    r = json.loads(capsys.readouterr().out)
    assert r["valido"] is False and len(r["errores"]) >= 9


@pytest.mark.parametrize("args", [
    ["setup"], ["setup", "--solo-mongo", "--base", "farmared_demo_prueba"],
    ["reset-demo", "--base", "farmared_demo_prueba"],
    ["reset-demo", "--solo-mongo"],
])
def test_destinos_y_alcances_requeridos(args):
    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 2
