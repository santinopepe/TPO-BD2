"""Pruebas puras sobre copias de las fuentes; ningún test modifica originales."""

import csv
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from farmared.carga.formatos import CAMPOS
from farmared.carga.modelos import ErrorDatasets
from farmared.carga.validacion import rutas_desde_directorios, validar_datasets

ORIGINALES = Path(__file__).resolve().parents[2] / "data/originales"


@pytest.fixture
def fuente(tmp_path):
    return shutil.copytree(ORIGINALES, tmp_path / "fuente")


def editar(directorio, tabla, accion):
    path = directorio / f"{tabla}.csv"
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    accion(rows)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CAMPOS[tabla], lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def validar(directorio):
    return validar_datasets(rutas_desde_directorios(directorio))


def test_originales_y_conversiones_sin_modificaciones():
    antes = {p.name: p.read_bytes() for p in ORIGINALES.glob("*.csv")}
    resultado = validar(ORIGINALES)
    assert resultado.resumen()["conteos"] == {
        "clientes": 8, "sucursales": 5, "farmaceuticos": 7, "proveedores": 5,
        "productos": 13, "stock_lotes": 18, "recetas": 9, "ventas": 16, "detalle_ventas": 22,
    }
    assert resultado.filas["clientes"][0].datos["dni"] == "31245678"
    assert resultado.filas["clientes"][7].datos["activo"] is False
    assert resultado.filas["clientes"][4].datos["nro_afiliado"] is None
    assert resultado.filas["ventas"][0].datos["fecha"] == datetime(2025, 9, 18, 3, tzinfo=UTC)
    assert resultado.filas["detalle_ventas"][0].datos["precio_unit"] == 3850
    assert resultado.filas["productos"][6].datos["precio_unit"] == 4800  # No repreció el detalle.
    assert resultado.filas["recetas"][1].datos["proxima_dispensa"] == datetime(2026, 9, 15, 3, tzinfo=UTC)
    assert {(Path(a.archivo).name, a.fila, a.campo) for a in resultado.avisos} == {
        ("ventas.csv", 2, "id_farmaceutico"), ("detalle_ventas.csv", 20, "id_producto"),
        ("recetas.csv", 3, "proxima_dispensa"),
    }
    assert all(f.sha256 == hashlib.sha256(antes[Path(f.archivo).name]).hexdigest() for f in resultado.fuentes)
    assert {p.name: p.read_bytes() for p in ORIGINALES.glob("*.csv")} == antes


@pytest.mark.parametrize("tabla,campo,valor", [
    ("clientes", "id_cliente", ""), ("clientes", "nombre", " "),
    ("clientes", "dni", "31.245.678"), ("clientes", "activo", "true"),
    ("clientes", "activo", "1"), ("clientes", "obra_social", "Otra"),
    ("proveedores", "cuit", "30712345671"), ("farmaceuticos", "cargo", "Vendedor"),
    ("sucursales", "tipo", "Local"), ("productos", "precio_unit", "1.0"),
    ("productos", "precio_unit", "1e3"), ("productos", "precio_unit", "NaN"),
    ("productos", "precio_unit", "True"), ("productos", "precio_unit", "-1"),
    ("productos", "precio_unit", str(2**63)), ("productos", "precio_unit", "9" * 5000),
    ("productos", "precio_unit", " 100"), ("productos", "condicion_venta", "Libre"),
    ("stock_lotes", "unidades", "-1"), ("stock_lotes", "vencimiento", "2026-02-30"),
    ("stock_lotes", "vencimiento", "20261109"), ("stock_lotes", "vencimiento", "2026-W45-1"),
    ("recetas", "dispensas_autorizadas", "4"), ("recetas", "dispensas_realizadas", "-1"),
    ("recetas", "estado", "Activa"), ("ventas", "estado", "Pagada"),
    ("ventas", "medio_pago", "Cheque"), ("detalle_ventas", "cantidad", "0"),
    ("detalle_ventas", "cantidad", "1.5"), ("detalle_ventas", "precio_unit", "-1"),
])
def test_valores_invalidos_diagnostico_localizable(fuente, tabla, campo, valor):
    editar(fuente, tabla, lambda rows: rows[0].update({campo: valor}))
    with pytest.raises(ErrorDatasets) as exc:
        validar(fuente)
    assert any(Path(e.archivo).name == f"{tabla}.csv" and e.fila == 2 and e.campo == campo for e in exc.value.errores)
    assert exc.value.codigo == "VALIDACION"
    assert exc.value.resumen()["valido"] is False
    assert exc.value.resumen()["huella"] is None
    assert not hasattr(exc.value, "filas")


@pytest.mark.parametrize("tabla,campo", [
    ("farmaceuticos", "id_sucursal"), ("productos", "id_proveedor"),
    ("stock_lotes", "id_producto"), ("stock_lotes", "id_sucursal"),
    ("recetas", "id_cliente"), ("ventas", "id_cliente"),
    ("ventas", "id_farmaceutico"), ("ventas", "id_receta"),
    ("detalle_ventas", "id_venta"), ("detalle_ventas", "id_producto"),
])
def test_diez_referencias(fuente, tabla, campo):
    editar(fuente, tabla, lambda rows: rows[0].update({campo: "A-NO-EXISTE"}))
    with pytest.raises(ErrorDatasets) as exc:
        validar(fuente)
    assert any(e.campo == campo and e.codigo == "REFERENCIA" for e in exc.value.errores)


@pytest.mark.parametrize("tabla,campo", [(t, campos[0]) for t, campos in CAMPOS.items()] + [
    ("clientes", "dni"), ("farmaceuticos", "matricula"),
])
def test_unicidad_incluye_inactivos(fuente, tabla, campo):
    def duplicar(rows):
        rows[1][campo] = rows[0][campo]
        if "activo" in rows[0]:
            rows[0]["activo"] = "False"
    editar(fuente, tabla, duplicar)
    with pytest.raises(ErrorDatasets) as exc:
        validar(fuente)
    assert any(e.campo == campo and e.codigo == "DUPLICADO" and e.fila == 3 for e in exc.value.errores)


@pytest.mark.parametrize("tabla,cambio,campo", [
    ("clientes", {"obra_social": "Sin cobertura"}, "nro_afiliado"),
    ("recetas", {"dispensas_realizadas": "2"}, "dispensas_realizadas"),
    ("recetas", {"dispensas_autorizadas": "2", "dispensas_realizadas": "2"}, "dispensas_autorizadas"),
    ("recetas", {"dispensas_realizadas": "0"}, "estado"),
    ("ventas", {"id_receta": "RC001"}, "id_receta"),
    ("ventas", {"fecha": "2025-09-16"}, "fecha"),
    ("ventas", {"total": "3851"}, "total"),
])
def test_coherencia_y_totales(fuente, tabla, cambio, campo):
    editar(fuente, tabla, lambda rows: rows[0].update(cambio))
    with pytest.raises(ErrorDatasets) as exc:
        validar(fuente)
    assert any(e.campo == campo for e in exc.value.errores)


def test_overflow_producto_y_suma(fuente):
    editar(fuente, "detalle_ventas", lambda rows: rows[0].update({"cantidad": "2", "precio_unit": str(2**63-1)}))
    with pytest.raises(ErrorDatasets) as exc:
        validar(fuente)
    assert {e.campo for e in exc.value.errores if e.codigo == "RANGO"} >= {"precio_unit", "total"}


def test_cabecera_sin_detalles(fuente):
    editar(fuente, "detalle_ventas", lambda rows: rows.pop(0))
    with pytest.raises(ErrorDatasets) as exc:
        validar(fuente)
    assert any(e.codigo == "DETALLE" and e.fila == 2 for e in exc.value.errores)


@pytest.mark.parametrize("modo", ["faltante", "extra", "duplicada", "columnas", "comillas", "utf8", "vacio"])
def test_errores_de_estructura(fuente, modo):
    path = fuente / "clientes.csv"
    lineas = path.read_text().splitlines()
    if modo == "faltante":
        lineas[0] = lineas[0].replace(",activo", "")
    elif modo == "extra":
        lineas[0] += ",extra"
    elif modo == "duplicada":
        lineas[0] += ",dni"
    elif modo == "columnas":
        lineas[1] += ",extra"
    elif modo == "comillas":
        lineas = [lineas[0], '"sin cierre']
    elif modo == "utf8":
        path.write_bytes(b"\xff\xfe")
    else:
        lineas = [lineas[0]]
    if modo != "utf8":
        path.write_text("\n".join(lineas) + "\n")
    with pytest.raises(ErrorDatasets) as exc:
        validar(fuente)
    assert any(Path(e.archivo).name == "clientes.csv" and e.codigo in {"ESTRUCTURA", "CODIFICACION", "VACIO"} for e in exc.value.errores)


def test_archivos_faltantes_y_rutas_incompletas(tmp_path):
    with pytest.raises(ErrorDatasets) as exc:
        validar(tmp_path)
    assert len(exc.value.errores) == 9
    assert {Path(e.archivo).name for e in exc.value.errores} == {f"{t}.csv" for t in CAMPOS}
    with pytest.raises(ErrorDatasets) as exc:
        validar_datasets({})
    assert len(exc.value.errores) == 9


def test_identificadores_int64_nulos_y_cabecera_reordenada(fuente):
    editar(fuente, "clientes", lambda rows: rows[0].update({"dni": "00001234", "telefono": "00112233", "email": ""}))
    editar(fuente, "productos", lambda rows: rows[0].update({"precio_unit": str(2**63-1)}))
    path = fuente / "clientes.csv"
    with path.open(newline="") as f:
        rows = list(csv.DictReader(f))
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(reversed(CAMPOS["clientes"])))
        w.writeheader()
        w.writerows(rows)
    d = validar(fuente)
    assert d.filas["clientes"][0].datos["dni"] == "00001234"
    assert d.filas["clientes"][0].datos["telefono"] == "00112233"
    assert d.filas["clientes"][0].datos["email"] is None
    assert d.filas["productos"][0].datos["precio_unit"] == 2**63-1


def test_huellas_portables_y_cambio_de_bytes(fuente):
    original = validar(ORIGINALES)
    copia = validar(fuente)
    assert original.huella == copia.huella
    assert original.huella == validar(ORIGINALES).huella
    with (fuente / "clientes.csv").open("ab") as f:
        f.write(b"\n")
    distinto = validar(fuente)
    assert distinto.resumen()["conteos"] == original.resumen()["conteos"]
    assert distinto.huella != original.huella


def test_linea_fisica_con_csv_multilinea(fuente):
    editar(fuente, "clientes", lambda rows: (rows[0].update({"nombre": "Nombre\ncompuesto"}), rows[1].update({"dni": "INVALIDO"})))
    with pytest.raises(ErrorDatasets) as exc:
        validar(fuente)
    assert any(e.fila == 4 and e.campo == "dni" for e in exc.value.errores)


def test_calendario_comercial_cruzando_dst(fuente):
    editar(fuente, "recetas", lambda rows: rows[1].update({"fecha_emision": "2008-02-15", "proxima_dispensa": "2008-04-14"}))
    editar(fuente, "ventas", lambda rows: (rows[3].update({"fecha": "2008-02-15"}), rows[4].update({"fecha": "2008-03-15"})))
    assert not any(Path(a.archivo).name == "recetas.csv" and a.fila == 3 for a in validar(fuente).avisos)


def test_aviso_historico_no_desborda_calendario(fuente):
    editar(fuente, "recetas", lambda rows: rows[1].update({"fecha_emision": "9999-11-01", "proxima_dispensa": "9999-12-31"}))
    editar(fuente, "ventas", lambda rows: (rows[3].update({"fecha": "9999-11-01"}), rows[4].update({"fecha": "9999-12-20"})))
    resultado = validar(fuente)
    assert any(a.campo == "proxima_dispensa" and "calendario" in a.motivo for a in resultado.avisos)


def adicional_minimo(tmp_path):
    destino = tmp_path / "adicional_fixture"
    destino.mkdir()
    datos = {}
    for tabla in CAMPOS:
        with (ORIGINALES / f"{tabla}.csv").open(newline="") as f:
            datos[tabla] = list(csv.DictReader(f))[0]
    cliente = {**datos["clientes"], "id_cliente": "A-C-TEST", "dni": "99999999"}
    venta = {**datos["ventas"], "id_venta": "A-V-TEST", "id_cliente": "A-C-TEST",
             "id_farmaceutico": "F001", "id_receta": "", "tipo": "Venta libre", "total": "2800"}
    detalle = {**datos["detalle_ventas"], "id_detalle": "A-D-TEST", "id_venta": "A-V-TEST",
               "id_producto": "PRD001", "cantidad": "1", "precio_unit": "2800"}
    nuevos = {"clientes": cliente, "ventas": venta, "detalle_ventas": detalle}
    for tabla in CAMPOS:
        with (destino / f"{tabla}.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=CAMPOS[tabla])
            w.writeheader()
            if tabla in nuevos:
                w.writerow(nuevos[tabla])
    return destino


def test_union_fuentes_referencias_cruzadas_y_orden(tmp_path):
    adicional = adicional_minimo(tmp_path)
    resultado = validar_datasets(rutas_desde_directorios(ORIGINALES, adicional))
    assert len(resultado.fuentes) == 18
    assert len(resultado.filas["clientes"]) == 9
    assert len(resultado.filas["ventas"]) == 17
    assert len(resultado.filas["detalle_ventas"]) == 23
    inverso = validar_datasets(rutas_desde_directorios(adicional, ORIGINALES))
    assert inverso.resumen()["conteos"] == resultado.resumen()["conteos"]
    assert inverso.huella != resultado.huella


def test_duplicados_entre_fuentes_localizan_archivo_adicional(tmp_path):
    adicional = adicional_minimo(tmp_path)
    editar(adicional, "clientes", lambda rows: rows[0].update({"dni": "31245678"}))
    with pytest.raises(ErrorDatasets) as exc:
        validar_datasets(rutas_desde_directorios(ORIGINALES, adicional))
    assert any(e.archivo == str(adicional / "clientes.csv") and e.campo == "dni" and e.fila == 2 for e in exc.value.errores)


def test_mapeo_directo_y_tabla_desconocida():
    rutas = {tabla: ORIGINALES / f"{tabla}.csv" for tabla in CAMPOS}
    assert validar_datasets(rutas).huella == validar(ORIGINALES).huella
    rutas["inventada"] = ORIGINALES / "inventada.csv"
    with pytest.raises(ErrorDatasets) as exc:
        validar_datasets(rutas)
    assert any(e.archivo == "inventada" and e.codigo == "ESTRUCTURA" for e in exc.value.errores)


def test_cli_independiente_sin_drivers_y_fallo_json(tmp_path):
    script = """
import importlib.abc, sys
class BloquearDrivers(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'pymongo', 'neo4j'}:
            raise AssertionError('El validador no debe importar drivers')
sys.meta_path.insert(0, BloquearDrivers())
from farmared.__main__ import main
raise SystemExit(main(sys.argv[1:]))
"""
    comando = [sys.executable, "-c", script, "validar-datasets", "--directorio"]
    ok = subprocess.run([*comando, str(ORIGINALES)], capture_output=True, text=True)
    assert ok.returncode == 0, ok.stderr
    assert json.loads(ok.stdout)["valido"] is True
    mal = subprocess.run([*comando, str(tmp_path)], capture_output=True, text=True)
    assert mal.returncode == 1
    assert json.loads(mal.stdout)["valido"] is False
    assert len(json.loads(mal.stdout)["errores"]) == 9
