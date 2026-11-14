"""Contratos HTTP y límites de lectura de la consola local."""

import json
import os
from dataclasses import replace
from datetime import UTC, datetime
from http.client import HTTPConnection
from threading import Thread
from uuid import uuid4

import pytest
from bson import ObjectId

from farmared.config import Config
from farmared.errores import ErrorDominio
from farmared.ui.servidor import crear_servidor
from farmared.ui.servicio import Consola, _validar_lectura_mongo, serializable


@pytest.mark.parametrize("etapa", ["$out", "$merge", "$where", "$function", "$accumulator"])
def test_rechaza_escrituras_y_javascript_incluso_anidados(etapa):
    with pytest.raises(ErrorDominio, match=etapa.replace("$", r"\$")):
        _validar_lectura_mongo({"pipeline": [{"$lookup": {"pipeline": [{etapa: "destino"}]}}]})


@pytest.mark.parametrize("limite", [0, 501, True, "100", -1])
def test_limite_invalido_no_conecta(monkeypatch, limite):
    consola = Consola(Config())
    monkeypatch.setattr(consola, "_mongo", lambda: pytest.fail("No debe conectar"))
    with pytest.raises(ErrorDominio):
        consola.consulta({"limite": limite})


@pytest.mark.parametrize("consulta", ["CALL db.labels()", "LOAD CSV FROM 'file:///a.csv' AS a RETURN a", "PROFILE RETURN 1"])
def test_cypher_no_permite_procedimientos_ni_cargas(consulta):
    with pytest.raises(ErrorDominio):
        Consola(Config()).consulta({"motor": "neo4j", "texto": consulta})


def test_serializa_fechas_bson_y_valores_anidados():
    identificador = ObjectId()
    assert serializable({"id": identificador, "fecha": datetime(2026, 11, 14, tzinfo=UTC)}) == {
        "id": {"$oid": str(identificador)}, "fecha": "2026-11-14T00:00:00+00:00"}
    assert serializable(2**63 - 1) == {"$numberLong": "9223372036854775807"}


def test_un_motor_caido_no_oculta_al_otro(monkeypatch):
    consola = Consola(Config())
    def fallo():
        raise ErrorDominio("CONEXION", "MongoDB no disponible")
    monkeypatch.setattr(consola, "estado_mongo", fallo)
    monkeypatch.setattr(consola, "estado_neo4j", lambda: {"estado": "listo", "etiquetas": []})
    assert consola.estado() == {"mongo": {"estado": "error", "mensaje": "MongoDB no disponible"},
                                "neo4j": {"estado": "listo", "etiquetas": []}}


@pytest.fixture
def http(monkeypatch):
    monkeypatch.setattr(Consola, "consulta", lambda self, datos: {"resultados": [{"ok": True}]})
    servidor = crear_servidor(Config(), 0)
    hilo = Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    def pedir(ruta, *, metodo="GET", datos=None, headers=None):
        conexion = HTTPConnection("127.0.0.1", servidor.server_port, timeout=3)
        conexion.request(metodo, ruta, body=datos, headers=headers or {})
        respuesta = conexion.getresponse()
        cuerpo = respuesta.read()
        resultado = respuesta.status, dict(respuesta.getheaders()), cuerpo
        conexion.close()
        return resultado
    yield pedir
    servidor.shutdown()
    servidor.server_close()
    hilo.join(timeout=3)


def test_http_config_y_assets_sin_credenciales(http):
    status, _, cuerpo = http("/api/config")
    config = json.loads(cuerpo)
    assert status == 200
    assert len(config["consultas"]) == 15
    assert "mongo_uri" not in config and "neo4j_password" not in config
    for ruta in ("/", "/app.js", "/styles.css"):
        status, headers, cuerpo = http(ruta)
        assert status == 200 and cuerpo
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]


def test_http_consulta_json(http):
    status, _, cuerpo = http("/api/consulta", metodo="POST", datos='{"consulta":"q01"}',
                           headers={"Content-Type": "application/json"})
    assert status == 200
    assert json.loads(cuerpo) == {"resultados": [{"ok": True}]}


@pytest.mark.parametrize("headers", [{"Host": "evil.example"}, {"Origin": "https://evil.example"}])
def test_http_rechaza_host_y_origen_externos(http, headers):
    assert http("/api/config", headers=headers)[0] == 403


@pytest.mark.parametrize("contenido", ['[]', '{"parametros": []}', '{malformado'])
def test_http_json_invalido(http, contenido):
    assert http("/api/consulta", metodo="POST", datos=contenido,
                headers={"Content-Type": "application/json"})[0] == 400


def test_http_no_permite_traversal_ni_formularios(http):
    assert http("/../config.py")[0] == 404
    assert http("/api/consulta", metodo="POST", datos="consulta=q01",
                headers={"Content-Type": "application/x-www-form-urlencoded"})[0] == 415


def test_http_validacion_csv_y_huella_obligatoria(http):
    datos = {"origen": "proyecto", "conjunto": "originales"}
    status, _, cuerpo = http("/api/carga/validar", metodo="POST", datos=json.dumps(datos),
                            headers={"Content-Type": "application/json"})
    assert status == 200 and json.loads(cuerpo)["valido"]
    status, _, cuerpo = http("/api/carga/importar", metodo="POST", datos=json.dumps(datos),
                            headers={"Content-Type": "application/json"})
    assert status == 400 and "validación previa" in json.loads(cuerpo)["error"]


def test_http_sincronizacion_es_post_y_protege_origen(http, monkeypatch):
    monkeypatch.setattr(Consola, "sincronizar_neo4j", lambda self: {
        "estado": "sin_pendientes_observados", "procesados": 120, "pendientes_observados": 0, "fallidos": []})
    status, _, cuerpo = http("/api/sincronizar", metodo="POST", datos="{}",
                            headers={"Content-Type": "application/json"})
    assert status == 200 and json.loads(cuerpo)["procesados"] == 120
    assert http("/api/sincronizar")[0] == 404
    assert http("/api/sincronizar", metodo="POST", datos="{}",
                headers={"Content-Type": "application/json", "Origin": "https://externo.example"})[0] == 403


def test_http_csv_admite_cuerpos_mayores_que_una_consulta(http):
    import base64
    cuerpo = json.dumps({"origen": "archivos", "archivos": [{
        "nombre": "clientes.csv", "contenido_base64": base64.b64encode(b"invalido\n" * 10000).decode()}]})
    headers = {"Content-Type": "application/json"}
    assert len(cuerpo) > 65536
    status, _, resultado = http("/api/carga/validar", metodo="POST", datos=cuerpo, headers=headers)
    assert status == 200 and not json.loads(resultado)["valido"]
    assert http("/api/consulta", metodo="POST", datos=cuerpo, headers=headers)[0] == 413


@pytest.mark.skipif(os.getenv("FARMARED_TEST_UI") != "1", reason="Activar FARMARED_TEST_UI=1 con los motores disponibles.")
def test_consultas_reales_exploracion_y_escrituras():
    from farmared.conexiones import obtener_mongo
    config = replace(Config.from_env(), mongo_db="farmared_test_ui_" + uuid4().hex)
    db = obtener_mongo(config)
    consola = Consola(config)
    try:
        db.productos.insert_many([{"_id": str(i), "nombre": f"Producto {i}", "activo": True} for i in range(3)])
        db.productos.create_index("nombre")
        for consulta in [
            {"consulta": "q01", "limite": 2},
            {"motor": "mongo", "texto": '{"coleccion":"productos","filtro":{"activo":true}}', "limite": 2},
            {"motor": "mongo", "texto": '{"coleccion":"productos","pipeline":[{"$match":{"activo":true}}]}', "limite": 2},
        ]:
            resultado = consola.consulta(consulta)
            assert resultado["cantidad"] == 2 and resultado["truncado"]
        documentos = consola.documentos("productos", pagina=1, limite=2)
        assert documentos["total"] == 3 and len(documentos["resultados"]) == 1
        assert len(documentos["indices"]) == 2
        assert consola.consulta({"motor": "neo4j", "texto": "RETURN $n AS valor", "parametros": {"n": 7}})["resultados"] == [{"valor": 7}]
        q03 = next(q for q in consola.configuracion()["consultas"] if q["id"] == "q03")
        assert consola.consulta({"motor": "neo4j", "texto": q03["texto"], "parametros": {"id_cliente": "ui-inexistente"}})["resultados"] == []
        assert consola.consulta({"motor": "neo4j", "texto": "UNWIND range(1,10) AS n RETURN n", "limite": 2})["truncado"]
        plantilla = next(q for q in consola.configuracion()["consultas"] if q["id"] == "q01")
        assert consola.consulta({"motor": "mongo", "texto": plantilla["texto"]})["resultados"] == consola.consulta({"consulta": "q01"})["resultados"]
        def mongo(datos):
            return consola.consulta({"motor": "mongo", "texto": json.dumps(datos)})
        for datos, esperado in [
            ({"operacion": "insertOne", "documento": {"_id": "a", "nombre": "A"}}, {"insertados": 1}),
            ({"operacion": "insertMany", "documentos": [{"_id": "b"}, {"_id": "c"}]}, {"insertados": 2}),
            ({"operacion": "updateOne", "filtro": {"_id": "a"}, "actualizacion": {"$set": {"nombre": "B"}}}, {"modificados": 1}),
            ({"operacion": "updateMany", "filtro": {}, "actualizacion": {"$set": {"activo": True}}}, {"modificados": 3}),
            ({"operacion": "replaceOne", "filtro": {"_id": "a"}, "documento": {"nombre": "C"}}, {"modificados": 1}),
            ({"operacion": "deleteOne", "filtro": {"_id": "a"}}, {"eliminados": 1}),
            ({"operacion": "deleteMany", "filtro": {}}, {"eliminados": 2}),
        ]:
            resultado = mongo({"coleccion": "pruebas", **datos})
            assert resultado["escritura"]
            assert all(resultado["cambios"][k] == v for k, v in esperado.items())
        for operacion in ["updateOne", "deleteMany"]:
            with pytest.raises(ErrorDominio, match="filtro"):
                mongo({"coleccion": "productos", "operacion": operacion})
        plantilla = next(q for q in consola.configuracion()["consultas"] if q["id"] == "q13")
        cliente = mongo(json.loads(plantilla["texto"]))["cambios"]
        assert cliente["eventos"] and db.outbox.count_documents({}) == 1
        id_cliente = cliente["documento"]["_id"]
        assert mongo({"operacion": "q13", "accion": "modificar", "id_cliente": id_cliente, "datos": {"email": "ui@example.com"}})["escritura"]
        assert mongo({"operacion": "q13", "accion": "baja", "id_cliente": id_cliente})["cambios"]["documento"]["activo"] is False
        assert db.outbox.count_documents({}) == 3
        token = uuid4().hex
        try:
            resultado = consola.consulta({"motor": "neo4j", "texto": "UNWIND range(1,5) AS n CREATE (:FarmaRedUITest {token:$token, n:n}) RETURN n", "parametros": {"token": token}, "limite": 2})
            assert resultado["escritura"] and resultado["truncado"]
            assert resultado["cambios"]["nodes_created"] == 5
            assert consola.consulta({"motor": "neo4j", "texto": "MATCH (n:FarmaRedUITest {token:$token}) RETURN count(n) AS cantidad", "parametros": {"token": token}})["resultados"] == [{"cantidad": 5}]
        finally:
            consola.consulta({"motor": "neo4j", "texto": "MATCH (n:FarmaRedUITest {token:$token}) DETACH DELETE n", "parametros": {"token": token}})
        assert db.productos.count_documents({}) == 3
        assert consola.estado()["mongo"]["estado"] == "listo"
        assert consola.estado()["neo4j"]["estado"] == "listo"
    finally:
        db.client.drop_database(config.mongo_db)
        db.client.close()


def test_plantillas_sin_conexion_y_fechas_extended_json(monkeypatch):
    monkeypatch.setattr("farmared.ui.servicio.obtener_mongo", lambda _: pytest.fail("No debe conectar"))
    catalogo = Consola(Config()).configuracion()["consultas"]
    assert len(catalogo) == 15
    from farmared.consultas.q03 import CYPHER
    q03 = next(q for q in catalogo if q["id"] == "q03")
    assert q03["texto"] == CYPHER.strip() and q03["parametros"] == {"id_cliente": ""}
    q05 = next(q for q in catalogo if q["id"] == "q05")
    assert '"$date"' in q05["texto"]
    q11 = next(q for q in catalogo if q["id"] == "q11")
    assert json.loads(q11["texto"])["coleccion"] == "ventas"
    assert all(q["escritura"] for q in catalogo if q["id"] in {"q13", "q14", "q15"})
