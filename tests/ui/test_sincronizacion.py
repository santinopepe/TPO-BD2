from unittest.mock import Mock

import pytest

from farmared.config import Config
from farmared.errores import ErrorDominio
from farmared.ui.servicio import Consola


def test_prepara_grafo_sincroniza_con_lock_y_cierra_recursos(monkeypatch, tmp_path):
    from farmared.ui import sincronizacion as modulo
    consola = Consola(Config(), lock_path=tmp_path / "lock" / "sync.lock")
    db = Mock()
    db.outbox.count_documents.return_value = 120
    driver = Mock()
    driver.__enter__ = Mock(return_value=driver)
    driver.__exit__ = Mock()
    monkeypatch.setattr(consola, "_mongo", lambda: db)
    monkeypatch.setattr(modulo, "obtener_neo4j", lambda _: driver)
    orden = []
    monkeypatch.setattr(modulo, "preparar_grafo", lambda d: orden.append("esquema"))
    def consumir(base, grafo, ruta, *, max_eventos):
        assert (base, grafo, ruta, max_eventos) == (db, driver, consola.lock_path, 500)
        orden.append("eventos")
        return {"estado": "sin_pendientes_observados", "procesados": 120, "pendientes_observados": 0, "fallidos": []}
    monkeypatch.setattr(modulo, "sincronizar", consumir)
    assert consola.sincronizar_neo4j()["procesados"] == 120
    assert orden == ["esquema", "eventos"]
    db.client.close.assert_called_once()
    driver.__exit__.assert_called_once()


@pytest.mark.parametrize("etapa", ["conexion", "esquema"])
def test_fallo_neo4j_preserva_pendientes_y_cierra_mongo(monkeypatch, tmp_path, etapa):
    from farmared.ui import sincronizacion as modulo
    consola = Consola(Config(), lock_path=tmp_path / "sync.lock")
    db = Mock()
    db.outbox.count_documents.return_value = 120
    monkeypatch.setattr(consola, "_mongo", lambda: db)
    def fallo(*_):
        raise ErrorDominio("CONEXION", "Neo4j no disponible")
    if etapa == "conexion":
        monkeypatch.setattr(modulo, "obtener_neo4j", fallo)
    else:
        class Driver:
            def __enter__(self): return self
            def __exit__(self, *_): pass
        monkeypatch.setattr(modulo, "obtener_neo4j", lambda _: Driver())
        monkeypatch.setattr(modulo, "preparar_grafo", fallo)
    resultado = consola.sincronizar_neo4j()
    assert resultado["estado"] == "error" and resultado["pendientes_observados"] == 120
    assert resultado["fallidos"][0]["codigo"] == "CONEXION"
    db.outbox.update_one.assert_not_called()
    db.client.close.assert_called_once()
