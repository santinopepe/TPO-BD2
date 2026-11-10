
import os
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from farmared.config import Config
from farmared.conexiones import obtener_mongo, obtener_neo4j

pytestmark = pytest.mark.skipif(
    os.environ.get("FARMARED_TEST_INTEGRACION") != "1",
    reason="Activar FARMARED_TEST_INTEGRACION=1 con motores de prueba disponibles.",
)


@pytest.fixture
def db():
    config = replace(Config.from_env(), mongo_db=f"farmared_test_a_infra_{uuid4().hex}")
    database = obtener_mongo(config)
    try:
        yield database
    finally:
        database.client.drop_database(config.mongo_db)
        database.client.close()


def test_mongo_primario_y_transaccion_commit_rollback(db):
    hello = db.client.admin.command("hello")
    assert hello["isWritablePrimary"] is True
    assert hello["setName"] == "rs0"
    assert db.client.write_concern.document["w"] == "majority"
    assert db.write_concern.document["w"] == "majority"
    db.create_collection("registros")
    db.create_collection("marcas")
    instante = datetime(2026, 11, 9, 3, tzinfo=UTC)
    with db.client.start_session() as sesion:
        with sesion.start_transaction():
            db.registros.insert_one({"_id": "commit", "fecha": instante}, session=sesion)
            db.marcas.insert_one({"_id": "commit"}, session=sesion)
        with pytest.raises(RuntimeError, match="fallo deliberado"):
            with sesion.start_transaction():
                db.registros.insert_one({"_id": "rollback"}, session=sesion)
                db.marcas.insert_one({"_id": "rollback"}, session=sesion)
                raise RuntimeError("fallo deliberado")
    assert db.registros.find_one({"_id": "commit"})["fecha"] == instante
    assert db.marcas.count_documents({"_id": "commit"}) == 1
    assert db.registros.count_documents({"_id": "rollback"}) == 0
    assert db.marcas.count_documents({"_id": "rollback"}) == 0


def test_neo4j_conectividad_y_rollback_real():
    prueba = f"A-INFRA-{uuid4().hex}"
    with obtener_neo4j(Config.from_env()) as driver:
        with driver.session(database="neo4j") as sesion:
            try:
                assert sesion.run("RETURN 1 AS listo").single()["listo"] == 1
                with pytest.raises(RuntimeError, match="fallo deliberado"):
                    with sesion.begin_transaction() as tx:
                        tx.run("CREATE (:AInfraPrueba {id: $id})", id=prueba).consume()
                        raise RuntimeError("fallo deliberado")
                cantidad = sesion.run(
                    "MATCH (n:AInfraPrueba {id: $id}) RETURN count(n) AS cantidad", id=prueba,
                ).single()["cantidad"]
                assert cantidad == 0
            finally:
                sesion.run("MATCH (n:AInfraPrueba {id: $id}) DELETE n", id=prueba).consume()
