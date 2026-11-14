import base64
import os
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from farmared.config import Config
from farmared.errores import ErrorDominio
from farmared.ui.importacion import DATOS_PROYECTO
from farmared.ui.servicio import Consola


def subidos(conjunto="completo"):
    carpetas = ("originales", "adicionales") if conjunto == "completo" else ("originales",)
    return {"origen": "archivos", "archivos": [
        {"nombre": f"data/{carpeta}/{ruta.name}", "contenido_base64": base64.b64encode(ruta.read_bytes()).decode("ascii")}
        for carpeta in carpetas for ruta in sorted((DATOS_PROYECTO / carpeta).iterdir())
        if ruta.name.endswith(".csv") or ruta.name == "manifiesto.json"
    ]}


@pytest.fixture
def sin_motor(monkeypatch):
    consola = Consola(Config())
    monkeypatch.setattr(consola, "_mongo", lambda: pytest.fail("No debe conectar"))
    return consola


@pytest.mark.parametrize("conjunto,documentos,fuentes", [("originales", 81, 9), ("completo", 169, 18)])
def test_validar_proyecto_no_conecta_y_distingue_filas_de_documentos(sin_motor, conjunto, documentos, fuentes):
    resultado = sin_motor.cargar_csv({"origen": "proyecto", "conjunto": conjunto})
    assert resultado["valido"] and resultado["escrituras"] == 0
    assert sum(resultado["conteos_documentos"].values()) == documentos
    assert len(resultado["fuentes"]) == fuentes
    assert resultado["conteos"]["detalle_ventas"] > 0
    assert "detalle_ventas" not in resultado["conteos_documentos"]
    assert all(not Path(f["archivo"]).is_absolute() for f in resultado["fuentes"])


def test_upload_preserva_bytes_manifiesto_y_huella_del_proyecto(sin_motor):
    proyecto = sin_motor.cargar_csv({"origen": "proyecto", "conjunto": "completo"})
    archivos = subidos()
    archivos["archivos"].reverse()  # El orden del selector no cambia la carga.
    upload = sin_motor.cargar_csv(archivos)
    assert upload["valido"]
    assert upload["huella"] == proyecto["huella"]
    assert upload["conteos"] == proyecto["conteos"]
    assert upload["generaciones"][0]["base_date"] == "2026-11-10"


def test_csv_invalido_muestra_archivo_fila_y_campo_sin_escrituras(sin_motor):
    archivos = subidos("originales")
    archivos["archivos"][0]["contenido_base64"] = base64.b64encode(b"columna_incorrecta\nvalor\n").decode()
    resultado = sin_motor.cargar_csv(archivos, importar=True)
    assert not resultado["valido"] and resultado["escrituras"] == 0
    diagnostico = next(e for e in resultado["errores"] if e["campo"] == "cabecera")
    assert diagnostico["fila"] == 1
    assert diagnostico["archivo"].endswith("clientes.csv")
    assert not Path(diagnostico["archivo"]).is_absolute()


@pytest.mark.parametrize("nombre", ["../clientes.csv", "/tmp/clientes.csv", "a/../../clientes.csv", "a\\clientes.csv", "a//clientes.csv", "./clientes.csv", "clientes.csv/ventas.csv", "archivo.py"])
def test_nombres_invalidos_no_acceden_al_motor(sin_motor, nombre):
    with pytest.raises(ErrorDominio):
        sin_motor.cargar_csv({"origen": "archivos", "archivos": [{"nombre": nombre, "contenido_base64": ""}]})


def test_rechaza_duplicados_y_base64_invalido(sin_motor):
    with pytest.raises(ErrorDominio, match="repetido"):
        sin_motor.cargar_csv({"origen": "archivos", "archivos": [{"nombre": "clientes.csv", "contenido_base64": ""}] * 2})
    with pytest.raises(ErrorDominio, match="Base64"):
        sin_motor.cargar_csv({"origen": "archivos", "archivos": [{"nombre": "clientes.csv", "contenido_base64": "!!!"}]})


def test_huella_obsoleta_no_conecta(sin_motor):
    with pytest.raises(ErrorDominio, match="validación previa"):
        sin_motor.cargar_csv({"origen": "proyecto", "conjunto": "originales", "huella_esperada": "obsoleta"}, importar=True)


@pytest.mark.skipif(os.getenv("FARMARED_TEST_UI") != "1", reason="Activar FARMARED_TEST_UI=1 con MongoDB disponible.")
def test_importacion_real_idempotente_vista_y_conflicto(monkeypatch):
    from farmared.conexiones import obtener_mongo
    config = replace(Config.from_env(), mongo_db="farmared_test_ui_csv_" + uuid4().hex)
    db = obtener_mongo(config)
    consola = Consola(config)
    monkeypatch.setattr(consola, "sincronizar_neo4j", lambda: {
        "estado": "sin_pendientes_observados", "procesados": 0, "pendientes_observados": 0, "fallidos": []})
    try:
        datos = {"origen": "proyecto", "conjunto": "completo"}
        previo = consola.cargar_csv(datos)
        resultado = consola.cargar_csv({**datos, "huella_esperada": previo["huella"]}, importar=True)
        assert resultado["carga"]["carga"] == "completa"
        assert resultado["carga"]["eventos_emitidos"] == 120
        assert not resultado["carga"]["reutilizada"]
        assert resultado["preparacion_consultas"]["estado"] == "lista"
        assert sum(db[nombre].count_documents({}) for nombre in previo["conteos_documentos"]) == 169
        assert db.outbox.count_documents({}) == 120
        assert next(db.list_collections(filter={"name": "ingresos_mensuales_farmaceutico"}))["type"] == "view"
        # Subir los mismos bytes desde una carpeta es la misma carga.
        repetida = consola.cargar_csv({**subidos(), "huella_esperada": previo["huella"]}, importar=True)
        assert repetida["carga"]["reutilizada"] and repetida["carga"]["eventos_emitidos"] == 0
        original = {"origen": "proyecto", "conjunto": "originales"}
        otra = consola.cargar_csv(original)
        with pytest.raises(ErrorDominio):
            consola.cargar_csv({**original, "huella_esperada": otra["huella"]}, importar=True)
        assert db.outbox.count_documents({}) == 120
        assert db.ventas.count_documents({}) == 28
    finally:
        db.client.drop_database(config.mongo_db)
        db.client.close()
