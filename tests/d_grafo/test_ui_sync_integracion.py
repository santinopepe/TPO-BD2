"""El flujo CSV + Neo4j usa los contenedores exclusivos de los tests de D."""

import os
from dataclasses import replace
from uuid import uuid4

import pytest

from farmared.conexiones import obtener_mongo
from farmared.errores import ErrorDominio
from farmared.proyeccion.verificacion import verificar_proyeccion
from farmared.ui.servicio import Consola

pytestmark = pytest.mark.skipif(os.getenv("FARMARED_TEST_UI_SYNC") != "1",
                              reason="Activar FARMARED_TEST_UI_SYNC=1 con Docker disponible.")


def test_importacion_fallo_neo_retry_y_repeticion_sin_duplicados(driver, mongo_config, monkeypatch, tmp_path):
    from farmared.ui import sincronizacion as modulo
    config = replace(mongo_config, mongo_db="farmared_test_ui_sync_" + uuid4().hex)
    consola = Consola(config, lock_path=tmp_path / "sync.lock")
    db = obtener_mongo(config)
    class Prestado:
        def __enter__(self): return driver
        def __exit__(self, *_): pass
    def caido(_):
        raise ErrorDominio("CONEXION", "Neo4j apagado para la prueba")
    try:
        fuente = {"origen": "proyecto", "conjunto": "completo"}
        previo = consola.cargar_csv(fuente)
        solicitud = {**fuente, "huella_esperada": previo["huella"]}
        monkeypatch.setattr(modulo, "obtener_neo4j", caido)
        parcial = consola.cargar_csv(solicitud, importar=True)
        assert parcial["carga"]["carga"] == "completa"
        assert parcial["sincronizacion"]["estado"] == "error"
        assert db.outbox.count_documents({"procesado": False}) == 120
        monkeypatch.setattr(modulo, "obtener_neo4j", lambda _: Prestado())
        # Repetir la carga dispara automáticamente la sincronización pendiente.
        recuperada = consola.cargar_csv(solicitud, importar=True)
        assert recuperada["carga"]["reutilizada"]
        assert recuperada["sincronizacion"]["procesados"] == 120
        assert recuperada["sincronizacion"]["pendientes_observados"] == 0
        informe = verificar_proyeccion(db, driver, consola.lock_path, confirmar_escrituras_pausadas=True)
        assert informe["equivalente"]
        assert consola.sincronizar_neo4j()["procesados"] == 0
        assert consola.cargar_csv(solicitud, importar=True)["sincronizacion"]["procesados"] == 0
        assert db.outbox.count_documents({}) == 120
        assert db.ventas.count_documents({}) == 28
    finally:
        db.client.drop_database(config.mongo_db)
        db.client.close()
