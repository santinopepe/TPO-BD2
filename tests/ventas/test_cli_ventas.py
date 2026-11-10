"""CLI de q14/q15/demo-transaccion y demo sobre el dataset de entrega."""

import argparse
import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from farmared.cli_ventas import COMANDOS_VENTAS, a_json, ejecutar, registrar_comandos
from farmared.clock import SystemClock
from farmared.config import Config
from farmared.errores import ErrorDominio

RAIZ = Path(__file__).resolve().parents[2]


def parsear(*argv):
    """Router mínimo equivalente al de __main__ para los comandos de B."""
    parser = argparse.ArgumentParser(prog="farmared")
    registrar_comandos(parser.add_subparsers(dest="comando", required=True))
    return parser.parse_args(argv)


def correr(capsys, *argv):
    assert ejecutar(parsear(*argv)) == 0
    return json.loads(capsys.readouterr().out)


# --- Sin motor ---------------------------------------------------------------

def test_comandos_registrados_y_delegados_a_este_modulo():
    assert COMANDOS_VENTAS == {c: ("farmared.cli_ventas", "ejecutar") for c in ("q14", "q15", "demo-transaccion")}
    args = parsear("q14", "--base", "b", "--pedido", "p.json")
    assert (args.comando, args.base, args.pedido) == ("q14", "b", "p.json")
    assert parsear("q15", "--base", "b", "--id-venta", "V011").id_venta == "V011"


@pytest.mark.parametrize("argv", [["q15", "--base", "b"], ["q14", "--base", "b"], ["demo-transaccion"],
                                  ["q15", "--base", " ", "--id-venta", "V1"]])
def test_argumentos_obligatorios(argv):
    with pytest.raises(SystemExit):
        parsear(*argv)


def test_router_principal_delega_en_cli_ventas():
    from farmared.__main__ import COMANDOS, PENDIENTES

    for comando in COMANDOS_VENTAS:
        assert COMANDOS[comando] == ("farmared.cli_ventas", "ejecutar") and comando not in PENDIENTES
    entorno = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    proceso = subprocess.run([sys.executable, "-m", "farmared", "demo-transaccion", "--base", "farmared"],
                             capture_output=True, text=True, env=entorno, timeout=60)
    assert proceso.returncode == 1 and proceso.stderr.startswith("VALIDACION:")  # error de dominio, sin conectar


def test_registrar_no_importa_pymongo():
    codigo = "import sys, farmared.cli_ventas; print('pymongo' in sys.modules)"
    salida = subprocess.run([sys.executable, "-c", codigo], capture_output=True, text=True, check=True)
    assert salida.stdout.strip() == "False"


@pytest.mark.parametrize("base", ["farmared", "farmared_demo_", "otra_demo"])
def test_demo_rechaza_bases_que_no_son_de_demo_sin_conectar(base):
    with pytest.raises(ErrorDominio) as exc:
        ejecutar(parsear("demo-transaccion", "--base", base))
    assert exc.value.codigo == "VALIDACION"


def test_demo_no_sobrescribe_evidencia_existente_sin_conectar(tmp_path):
    existente = tmp_path / "evidencia.json"
    existente.write_text("{}", encoding="utf-8")
    with pytest.raises(ErrorDominio) as exc:
        ejecutar(parsear("demo-transaccion", "--base", "farmared_demo_x", "--salida", str(existente)))
    assert exc.value.codigo == "VALIDACION" and existente.read_text(encoding="utf-8") == "{}"


@pytest.mark.parametrize("contenido", [None, "{no es json", "[1, 2]"])
def test_pedido_ilegible_se_rechaza_sin_conectar(tmp_path, contenido):
    ruta = tmp_path / "pedido.json"
    if contenido is not None:
        ruta.write_text(contenido, encoding="utf-8")
    with pytest.raises(ErrorDominio) as exc:
        ejecutar(parsear("q14", "--base", "b", "--pedido", str(ruta)))
    assert exc.value.codigo == "VALIDACION"


def test_json_muestra_dias_comerciales_como_fecha():
    datos = {"fecha": datetime(2026, 11, 10, 3, 0, tzinfo=UTC),
             "creado_en": datetime(2026, 11, 10, 15, 30, 0, 123000, tzinfo=UTC)}
    assert json.loads(a_json(datos)) == {"fecha": "2026-11-10", "creado_en": "2026-11-10T15:30:00.123000+00:00"}


# --- Con MongoDB ---------------------------------------------------------------

def test_q14_por_cli_registra_y_reporta(db, escenario, capsys, tmp_path):
    ruta = tmp_path / "pedido.json"
    ruta.write_text(json.dumps({"id_venta": "B-VCLI1", "id_cliente": "B-C001", "id_farmaceutico": "B-F001",
                                "medio_pago": "Efectivo", "items": [{"id_producto": "B-P002", "cantidad": 1}]}),
                    encoding="utf-8")
    salida = correr(capsys, "q14", "--base", db.name, "--pedido", str(ruta))

    assert (salida["operacion"], salida["reutilizada"], salida["id_venta_generado"]) == ("q14", False, False)
    assert salida["venta"]["_id"] == "B-VCLI1" and salida["venta"]["total"] == 3500
    assert salida["venta"]["fecha"] == SystemClock().today().isoformat()
    assert salida["proyeccion"] == "pendiente_sync" and len(salida["eventos"]) == 1
    assert correr(capsys, "q14", "--base", db.name, "--pedido", str(ruta))["reutilizada"] is True


def test_q14_por_cli_sin_id_genera_uno_y_avisa(db, escenario, capsys, tmp_path):
    ruta = tmp_path / "pedido.json"
    ruta.write_text(json.dumps({"id_cliente": "B-C001", "id_farmaceutico": "B-F001", "medio_pago": "Efectivo",
                                "items": [{"id_producto": "B-P002", "cantidad": 1}]}), encoding="utf-8")
    salida = correr(capsys, "q14", "--base", db.name, "--pedido", str(ruta))
    assert salida["id_venta_generado"] is True and "aviso" in salida
    assert db.ventas.count_documents({"_id": salida["venta"]["_id"]}) == 1


def test_q15_por_cli_y_error_de_dominio_se_propaga(db, escenario, capsys):
    db.ventas.insert_one({
        "_id": "B-VCLI2", "id_cliente": "B-C001", "id_farmaceutico": "B-F001", "id_sucursal": "B-S001",
        "id_receta": None, "fecha": datetime(2026, 9, 1, 3, tzinfo=UTC), "tipo": "Venta libre",
        "medio_pago": "Efectivo", "estado": "Pendiente", "total": 3500,
        "items": [{"id_detalle": "D1", "id_producto": "B-P002", "cantidad": 1, "precio_unit": 3500,
                   "subtotal": 3500, "asignaciones_lotes": []}],
        "stock_aplicado": False, "receta_aplicada": False, "origen": "servicio",
        "trazabilidad_lotes": "no_aplicada"})
    salida = correr(capsys, "q15", "--base", db.name, "--id-venta", "B-VCLI2")
    assert salida["venta"]["estado"] == "Completada" and salida["venta"]["fecha_creacion_pendiente"] == "2026-09-01"

    with pytest.raises(ErrorDominio) as exc:
        ejecutar(parsear("q15", "--base", db.name, "--id-venta", "B-V404"))
    assert exc.value.codigo == "NO_EXISTE"


# --- Demo sobre el dataset de entrega -----------------------------------------------

@pytest.fixture
def db_demo():
    if not any(os.environ.get(k) == "1" for k in ("FARMARED_TEST_MONGO", "FARMARED_TEST_INTEGRACION")):
        pytest.skip("Activar FARMARED_TEST_MONGO=1 con replica set de prueba.")
    from farmared.carga.mongo import cargar_mongo
    from farmared.carga.validacion import rutas_desde_directorios
    from farmared.conexiones import obtener_mongo

    nombre = f"farmared_demo_test_b_{uuid4().hex}"
    database = obtener_mongo(replace(Config.from_env(), mongo_db=nombre))
    try:
        cargar_mongo(database, rutas_desde_directorios(RAIZ / "data/originales", RAIZ / "data/adicionales"))
        yield database
    finally:
        database.client.drop_database(nombre)
        database.client.close()


def test_demo_con_fecha_base_de_los_adicionales(db_demo, reloj):
    from farmared.servicios.ventas.demo import ejecutar_demo

    pasos = {p["paso"]: p for p in ejecutar_demo(db_demo, reloj)["pasos"]}

    exito = pasos["q14_exito_receta_fefo"]
    assert exito["resultado"]["estado"] == "ok" and exito["resultado"]["reutilizada"] is False
    unidades = {k: (exito["antes"]["stock_lotes"][k]["unidades"], v["unidades"])
                for k, v in exito["despues"]["stock_lotes"].items()}
    assert unidades == {"A-L001": (100, 100), "A-L002": (4, 0), "A-L003": (10, 8), "A-L004": (20, 20),
                        "A-L006": (49, 47), "A-L016": (10, 10)}
    receta = exito["despues"]["recetas"]["A-RC001"]
    assert (receta["dispensas_realizadas"], receta["proxima_dispensa"]) == (2, datetime(2026, 12, 10, 3, tzinfo=UTC))
    assert exito["antes"]["ventas"]["B-DEMO-V1"] is None and exito["despues"]["ventas"]["B-DEMO-V1"]["estado"] == "Completada"

    for nombre, codigo in [("q14_rechazo_stock", "STOCK_INSUFICIENTE"),
                           ("q14_rechazo_cliente_inactivo", "VALIDACION"),
                           ("q15_rechazo_pendiente", "STOCK_INSUFICIENTE")]:
        assert pasos[nombre]["resultado"]["codigo"] == codigo
        assert pasos[nombre]["antes"] == pasos[nombre]["despues"]

    assert pasos["q14_reintento_idempotente"]["resultado"]["reutilizada"] is True
    assert pasos["q14_reintento_idempotente"]["antes"] == pasos["q14_reintento_idempotente"]["despues"]
    q15 = pasos["q15_exito_pendiente"]
    assert q15["resultado"]["estado"] == "ok"
    assert (q15["antes"]["stock_lotes"]["L014"]["unidades"], q15["despues"]["stock_lotes"]["L014"]["unidades"]) == (45, 44)
    assert q15["despues"]["recetas"]["RC006"]["estado"] == "Completada"


def test_demo_por_cli_guarda_evidencia_y_es_repetible(db_demo, capsys, tmp_path):
    ruta = tmp_path / "demo.json"
    salida = correr(capsys, "demo-transaccion", "--base", db_demo.name, "--salida", str(ruta))
    assert salida["evidencia"] == str(ruta) and len(salida["pasos"]) == 6
    evidencia = json.loads(ruta.read_text(encoding="utf-8"))
    assert [p["paso"] for p in evidencia["pasos"]][0] == "q14_exito_receta_fefo"

    segunda = correr(capsys, "demo-transaccion", "--base", db_demo.name)  # sin efectos duplicados
    assert db_demo.ventas.count_documents({"_id": "B-DEMO-V1"}) == 1
    assert len(segunda["pasos"]) == 6
