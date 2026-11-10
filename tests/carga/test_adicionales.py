"""Adicionales deterministas y casos de la consigna; no ejecuta consultas B/C/D."""

import hashlib
import json
import shutil
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from farmared.carga.adicionales import generar_adicionales
from farmared.carga.formatos import CAMPOS, CLAVES
from farmared.carga.metadatos import MARCA_INCOMPLETA, NOMBRE_MANIFIESTO
from farmared.carga.modelos import ErrorDatasets
from farmared.carga.validacion import rutas_desde_directorios, validar_datasets
from farmared.clock import FixedClock, inicio_dia_utc
from farmared.errores import ErrorDominio

ORIGINALES = Path(__file__).resolve().parents[2] / "data/originales"
BASE = date(2026, 11, 10)


@pytest.fixture
def generado(tmp_path):
    destino = tmp_path / "adicionales"
    generar_adicionales(destino, ORIGINALES, base_date=BASE)
    return destino


def contenido(directorio):
    return {p.name: p.read_bytes() for p in directorio.iterdir()}


def conjunto(destino):
    return validar_datasets(rutas_desde_directorios(ORIGINALES, destino))


def propias(validado, tabla):
    return {f.datos[CLAVES[tabla]]: f.datos for f in validado.filas[tabla]
            if f.datos[CLAVES[tabla]].startswith("A-")}


def test_minimos_identidades_y_manifest(generado):
    v = conjunto(generado)
    assert len(v.generaciones) == 1 and v.generaciones[0].base_date == BASE
    for tabla in CAMPOS:
        filas = propias(v, tabla)
        assert len(filas) >= 10
        assert len(filas) == len([f for f in v.filas[tabla] if Path(f.archivo).parent == generado])
    m = json.loads((generado / NOMBRE_MANIFIESTO).read_text())
    assert set(m["archivos"]) == {f"{t}.csv" for t in CAMPOS}
    assert all(registro["sha256"] == hashlib.sha256((generado / nombre).read_bytes()).hexdigest()
               for nombre, registro in m["archivos"].items())
    assert all(registro["filas"] >= 10 for registro in m["archivos"].values())
    assert len(m["casos"]) == 14
    assert not (generado / MARCA_INCOMPLETA).exists()


def test_repeticion_no_mueve_fechas_y_determinismo(generado, tmp_path):
    antes = contenido(generado)
    reloj = FixedClock(datetime(2035, 1, 1, 12, tzinfo=UTC))
    segunda = generar_adicionales(generado, ORIGINALES, clock=reloj)
    assert segunda["reutilizada"] is True and segunda["base_date"] == BASE.isoformat()
    assert contenido(generado) == antes
    otro = tmp_path / "otro"
    generar_adicionales(otro, ORIGINALES, base_date=BASE)
    assert contenido(otro) == antes
    assert conjunto(otro).huella == conjunto(generado).huella


def test_hoy_solo_en_generacion_nueva(tmp_path):
    destino = tmp_path / "nuevo"
    resultado = generar_adicionales(destino, ORIGINALES, clock=FixedClock(datetime(2026, 11, 10, 1, tzinfo=UTC)))
    assert resultado["base_date"] == "2026-11-09"


def test_fecha_explicita_distinta_exige_otro_destino(generado):
    antes = contenido(generado)
    with pytest.raises(ErrorDominio) as exc:
        generar_adicionales(generado, ORIGINALES, base_date=BASE + timedelta(days=1))
    assert exc.value.codigo == "CONFLICTO_ID"
    assert contenido(generado) == antes


def test_casos_de_clientes_catalogo_y_profesionales(generado):
    v = conjunto(generado)
    c, f, p, prv, ventas, r = [propias(v, t) for t in ("clientes", "farmaceuticos", "productos", "proveedores", "ventas", "recetas")]
    assert not any(x["id_cliente"] == "A-C010" for x in ventas.values())
    assert not any(x["id_cliente"] == "A-C010" for x in r.values())
    assert sum(x["id_cliente"] == "A-C001" for x in r.values()) > 1
    assert f["A-F010"]["activo"] is True
    assert not any(x["id_farmaceutico"] == "A-F010" for x in ventas.values())
    assert f["A-F002"]["activo"] is False
    assert ventas["A-V002"]["estado"] == "Completada"
    assert ventas["A-V003"]["estado"] == "Pendiente" and ventas["A-V003"]["id_farmaceutico"] == "A-F002"
    assert p["A-PRD010"]["activo"] is True and prv[p["A-PRD010"]["id_proveedor"]]["activo"] is False
    assert c["A-C009"]["activo"] is False and p["A-PRD009"]["activo"] is False


def test_fronteras_y_fechas_comerciales(generado):
    v = conjunto(generado)
    r, ventas, lotes = [propias(v, t) for t in ("recetas", "ventas", "stock_lotes")]
    for identificador, dias in (("A-RC001", -1), ("A-RC002", 0), ("A-RC003", 1)):
        assert r[identificador]["proxima_dispensa"] == inicio_dia_utc(BASE + timedelta(days=dias))
    assert r["A-RC004"]["dispensas_realizadas"] == r["A-RC004"]["dispensas_autorizadas"]
    assert r["A-RC007"]["estado"] == "Vencida"
    assert [lotes[f"A-L{i:03}"]["unidades"] for i in (5, 6, 7)] == [0, 49, 50]
    assert lotes["A-L001"]["vencimiento"] == inicio_dia_utc(BASE - timedelta(days=1))
    assert lotes["A-L002"]["vencimiento"] == inicio_dia_utc(BASE)
    assert [ventas[f"A-V{i:03}"]["total"] for i in (1, 2, 3)] == [4999, 5000, 4999]
    assert ventas["A-V007"]["estado"] == "Anulada"
    assert ventas["A-V010"]["fecha"] == inicio_dia_utc(BASE - timedelta(days=59))
    assert ventas["A-V011"]["fecha"] == inicio_dia_utc(BASE - timedelta(days=60))
    assert ventas["A-V012"]["fecha"] == inicio_dia_utc(BASE.replace(day=1))
    assert ventas["A-V008"]["fecha"] == inicio_dia_utc(BASE - timedelta(days=400))


def test_precondiciones_de_fefo_y_rollback_sin_ejecutarlos(generado):
    v = conjunto(generado)
    ventas, lotes, detalles = [propias(v, t) for t in ("ventas", "stock_lotes", "detalle_ventas")]
    assert ventas["A-V005"]["estado"] == "Pendiente"
    disponibles = [l for l in lotes.values() if l["id_producto"] == "A-PRD003" and l["id_sucursal"] == "A-S001"
                   and l["vencimiento"] >= inicio_dia_utc(BASE)]
    disponibles.sort(key=lambda l: (l["vencimiento"], l["id_lote"]))
    assert [l["id_lote"] for l in disponibles[:2]] == ["A-L002", "A-L003"]
    assert disponibles[0]["unidades"] == 4 and disponibles[1]["unidades"] == 10
    assert next(d for d in detalles.values() if d["id_venta"] == "A-V005")["cantidad"] == 6
    rollback = [d for d in detalles.values() if d["id_venta"] == "A-V006"]
    assert len(rollback) == 2 and ventas["A-V006"]["estado"] == "Pendiente"
    assert lotes["A-L010"]["unidades"] >= rollback[0]["cantidad"]
    assert lotes["A-L011"]["unidades"] < rollback[1]["cantidad"]


@pytest.mark.parametrize("modo", ["csv", "hash", "fecha", "fecha_sin_regenerar", "json", "version", "original", "incompleto"])
def test_manifiesto_o_fuentes_alterados_no_se_cargan(generado, tmp_path, modo):
    origen = ORIGINALES
    path = generado / NOMBRE_MANIFIESTO
    m = json.loads(path.read_text())
    if modo == "csv":
        with (generado / "clientes.csv").open("ab") as f:
            f.write(b"\n")
    elif modo == "hash":
        m["archivos"]["clientes.csv"]["sha256"] = "0" * 64
    elif modo == "fecha":
        m["base_date"] = "20261110"
    elif modo == "fecha_sin_regenerar":
        m["base_date"] = (BASE + timedelta(days=1)).isoformat()
    elif modo == "version":
        m["version_generador"] = 999
    elif modo == "original":
        origen = shutil.copytree(ORIGINALES, tmp_path / "originales")
        with (origen / "clientes.csv").open("ab") as f:
            f.write(b"\n")
    elif modo == "incompleto":
        (generado / MARCA_INCOMPLETA).write_text("interrumpida")
    if modo in {"hash", "fecha", "fecha_sin_regenerar", "version"}:
        path.write_text(json.dumps(m))
    if modo == "json":
        path.write_text("{")
    with pytest.raises(ErrorDatasets) as exc:
        validar_datasets(rutas_desde_directorios(origen, generado))
    assert any(e.codigo == "GENERACION" for e in exc.value.errores)


def test_no_pisa_directorio_ajeno_o_incompleto(tmp_path):
    destino = tmp_path / "ajeno"
    destino.mkdir()
    (destino / "previo.txt").write_text("preservar")
    with pytest.raises(ErrorDominio):
        generar_adicionales(destino, ORIGINALES)
    assert (destino / "previo.txt").read_text() == "preservar"


def test_publicacion_interrumpida_queda_bloqueada(tmp_path, monkeypatch):
    destino = tmp_path / "interrumpido"
    original_open = Path.open

    def fallar(path, *args, **kwargs):
        if path.parent == destino and path.name == "ventas.csv":
            raise OSError("Fallo de publicación inyectado")
        return original_open(path, *args, **kwargs)

    with monkeypatch.context() as m:
        m.setattr(Path, "open", fallar)
        with pytest.raises(ErrorDominio) as exc:
            generar_adicionales(destino, ORIGINALES, base_date=BASE)
        assert exc.value.codigo == "INTEGRIDAD"
    assert (destino / MARCA_INCOMPLETA).exists()
    with pytest.raises(ErrorDatasets):
        conjunto(destino)
    with pytest.raises(ErrorDominio):
        generar_adicionales(destino, ORIGINALES, base_date=BASE)


def test_cli_no_importa_drivers(tmp_path):
    script = """
import importlib.abc, sys
class Bloquear(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'pymongo','neo4j'}: raise AssertionError(fullname)
sys.meta_path.insert(0, Bloquear())
from farmared.__main__ import main
raise SystemExit(main(sys.argv[1:]))
"""
    r = subprocess.run([sys.executable, "-c", script, "generar-adicionales", "--directorio", str(tmp_path / "cli"),
                        "--originales", str(ORIGINALES), "--base-date", BASE.isoformat()], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["base_date"] == BASE.isoformat()
