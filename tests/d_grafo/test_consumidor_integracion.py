"""MongoDB replica set + Neo4j reales, exclusivamente en contenedores de prueba."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime
import os
import socket
from threading import Event
from uuid import uuid4

import pytest
from neo4j import GraphDatabase
from neo4j.exceptions import Neo4jError
from pymongo.errors import AutoReconnect

from farmared.consultas.q03 import q03_historial
from farmared.consultas.q04 import q04_clientes_con_recetas
from farmared.consultas.q10 import q10_clientes_sucursal
from farmared.errores import ErrorDominio
from farmared.grafo import preparar_grafo
from farmared.proyeccion import consumidor

pytestmark = pytest.mark.skipif(os.environ.get('FARMARED_TEST_SYNC') != '1',
                               reason='Activar FARMARED_TEST_SYNC=1 para ambos motores aislados.')






@pytest.fixture
def db(db_sync):
    return db_sync


@pytest.fixture(scope='module', autouse=True)
def esquema(driver):
    preparar_grafo(driver)




def nuevo_evento(coleccion, id, *, evento_id=None, creado_en=None):
    return dict(_id=evento_id or 'E-' + uuid4().hex, procesado=False,
                creado_en=creado_en or datetime(2026, 1, 1, tzinfo=UTC),
                afectadas=[dict(coleccion=coleccion, id=id)])


def insertar(db, fuente, eventos):
    with db.client.start_session() as sesion:
        with sesion.start_transaction():
            for coleccion, documento in fuente.items():
                db[coleccion].insert_one(deepcopy(documento), session=sesion)
            db.outbox.insert_many(deepcopy(eventos), session=sesion)


def grafo(driver):
    with driver.session() as sesion:
        return (sesion.run('MATCH (n) RETURN labels(n) AS l, properties(n) AS p ORDER BY n.id').data(),
                sesion.run('MATCH (a)-[r]->(b) RETURN a.id AS a, b.id AS b, type(r) AS t, '
                           'properties(r) AS p ORDER BY a, b, t, r.id_detalle').data())


def test_a_inicial_eventos_reales_y_consultas(db, driver, fuente, tmp_path):
    # Venta antes de los eventos de maestros: resuelve todas sus dependencias.
    eventos = [nuevo_evento('ventas', fuente['ventas']['_id'], evento_id='E00-VENTA')]
    eventos += [nuevo_evento(c, d['_id'], evento_id='E10-' + c) for c, d in fuente.items() if c != 'ventas']
    insertar(db, fuente, eventos)
    segunda = dict(fuente['recetas'], _id=fuente['recetas']['_id'] + '-2')
    with db.client.start_session() as sesion:
        with sesion.start_transaction():
            db.recetas.insert_one(segunda, session=sesion)
            db.outbox.insert_one(nuevo_evento('recetas', segunda['_id'], evento_id='E20-RECETA'), session=sesion)
    resultado = consumidor.sincronizar(db, driver, tmp_path / 'sync.lock')
    assert resultado['procesados'] == 7
    assert resultado['eventos_procesados'][0] == 'E00-VENTA'
    assert resultado['pendientes_observados'] == 0 and resultado['fallidos'] == []
    historial = q03_historial(driver, fuente['clientes']['_id'])
    assert [e['tipo_evento'] for e in historial] == ['RECETA', 'RECETA', 'VENTA']
    assert [i['precio_unit'] for i in historial[-1]['detalle']['items']] == [100, 120]
    assert [i['id_detalle'] for i in historial[-1]['detalle']['items']] == ['D1', 'D2']
    assert [r for r in q04_clientes_con_recetas(driver) if r['id_cliente'] == fuente['clientes']['_id']] == [
        dict(id_cliente=fuente['clientes']['_id'], nombre='Ana', apellido='Prueba', cantidad=2)]
    assert q10_clientes_sucursal(driver, fuente['sucursales']['_id']) == [
        dict(id_cliente=fuente['clientes']['_id'], nombre='Ana', apellido='Prueba')]
    assert db.outbox.count_documents({'procesado': True}) == 7
    assert consumidor.sincronizar(db, driver, tmp_path / 'sync.lock')['procesados'] == 0
    print('\nFlujo real outbox:', resultado, 'detalles=', historial[-1]['detalle']['items'])


def test_b_reentrega_idempotente(db, driver, fuente, tmp_path):
    e = nuevo_evento('ventas', fuente['ventas']['_id'])
    insertar(db, fuente, [e])
    assert consumidor.sincronizar(db, driver, tmp_path / 'lock')['procesados'] == 1
    antes = grafo(driver)
    db.outbox.update_one({'_id': e['_id']}, {'$set': {'procesado': False}})
    assert consumidor.sincronizar(db, driver, tmp_path / 'lock')['procesados'] == 1
    assert grafo(driver) == antes


def test_c_neo4j_realmente_inaccesible_y_recuperacion(db, driver, fuente, tmp_path):
    e = nuevo_evento('ventas', fuente['ventas']['_id'])
    insertar(db, fuente, [e])
    # Puerto reservado sin listener: fallo real del driver, no un mock exitoso.
    with socket.socket() as reserva:
        reserva.bind(('127.0.0.1', 0))
        puerto = reserva.getsockname()[1]
        with GraphDatabase.driver(f'bolt://127.0.0.1:{puerto}', auth=('neo4j', 'prueba-no-secreto'),
                                  connection_timeout=0.2, connection_acquisition_timeout=0.5,
                                  max_transaction_retry_time=0) as inaccesible:
            resultado = consumidor.sincronizar(db, inaccesible, tmp_path / 'lock')
    assert resultado['procesados'] == 0
    assert resultado['fallidos'][0]['codigo'] == 'NEO4J_CONEXION'
    assert db.outbox.find_one({'_id': e['_id']})['procesado'] is False
    assert consumidor.sincronizar(db, driver, tmp_path / 'lock')['procesados'] == 1


def test_d_dependencia_faltante_sin_grafo_parcial(db, driver, fuente, tmp_path):
    fuente['ventas']['items'][0]['id_producto'] = 'NO-EXISTE'
    e = nuevo_evento('ventas', fuente['ventas']['_id'])
    insertar(db, fuente, [e])
    antes = grafo(driver)
    resultado = consumidor.sincronizar(db, driver, tmp_path / 'lock')
    assert resultado['fallidos'][0]['codigo'] == 'DEPENDENCIA_INEXISTENTE'
    assert db.outbox.find_one({'_id': e['_id']})['procesado'] is False
    assert grafo(driver) == antes


def test_e_estado_actual_incluso_evento_antiguo(db, driver, fuente, tmp_path):
    e = nuevo_evento('ventas', fuente['ventas']['_id'])
    insertar(db, fuente, [e])
    assert consumidor.sincronizar(db, driver, tmp_path / 'lock')['procesados'] == 1
    venta = deepcopy(fuente['ventas'])
    venta.update(estado='Completada', total=450, id_receta=None)
    venta['items'] = [dict(venta['items'][1], precio_unit=450, subtotal=450)]
    nuevo = nuevo_evento('ventas', venta['_id'])
    with db.client.start_session() as sesion:
        with sesion.start_transaction():
            db.ventas.replace_one({'_id': venta['_id']}, venta, session=sesion)
            db.outbox.insert_one(nuevo, session=sesion)
    assert consumidor.sincronizar(db, driver, tmp_path / 'lock')['procesados'] == 1
    actualizado = grafo(driver)
    # Reentrega de un evento anterior vuelve a leer el estado actual, no el viejo.
    db.outbox.update_one({'_id': e['_id']}, {'$set': {'procesado': False}})
    assert consumidor.sincronizar(db, driver, tmp_path / 'lock')['procesados'] == 1
    assert grafo(driver) == actualizado
    v = q03_historial(driver, fuente['clientes']['_id'])[-1]
    assert v['estado'] == 'Completada'
    assert v['detalle']['id_receta'] is None
    assert v['detalle']['items'] == [dict(id_detalle='D2', orden=0, id_producto=fuente['productos']['_id'],
        nombre_al_vender=None, cantidad=1, precio_unit=450, subtotal=450)]


def test_f_commit_neo4j_ack_fallido_y_reentrega(db, driver, fuente, tmp_path, monkeypatch):
    e = nuevo_evento('ventas', fuente['ventas']['_id'])
    insertar(db, fuente, [e])
    def fallo_antes_ack(*args):
        raise AutoReconnect('fallo controlado antes de la marca')
    with monkeypatch.context() as m:
        m.setattr(consumidor, 'confirmar_evento', fallo_antes_ack)
        resultado = consumidor.sincronizar(db, driver, tmp_path / 'lock')
    assert resultado['fallidos'][0]['neo4j_confirmado'] is True
    assert resultado['fallidos'][0]['codigo'] == 'OUTBOX_CONFIRMACION'
    assert db.outbox.find_one({'_id': e['_id']})['procesado'] is False
    assert len(q03_historial(driver, fuente['clientes']['_id'])) == 2  # Commit real ya visible.
    antes = grafo(driver)
    assert consumidor.sincronizar(db, driver, tmp_path / 'lock')['procesados'] == 1
    assert grafo(driver) == antes


def test_g_dos_sincronizaciones_excluidas(db, driver, fuente, tmp_path, monkeypatch):
    insertar(db, fuente, [nuevo_evento('ventas', fuente['ventas']['_id'])])
    listo, liberar = Event(), Event()
    original = consumidor._leer_snapshot
    def pausa(database):
        unidad = original(database)
        if unidad:
            listo.set()
            assert liberar.wait(10)
        return unidad
    monkeypatch.setattr(consumidor, '_leer_snapshot', pausa)
    with ThreadPoolExecutor(max_workers=1) as pool:
        futuro = pool.submit(consumidor.sincronizar, db, driver, tmp_path / 'lock')
        try:
            assert listo.wait(10)
            with pytest.raises(ErrorDominio) as error:
                consumidor.sincronizar(db, driver, tmp_path / 'lock')
            assert error.value.codigo == 'SYNC_EN_CURSO'
            assert db.outbox.count_documents({'procesado': True}) == 0
        finally:
            liberar.set()
        assert futuro.result(timeout=30)['procesados'] == 1


def test_snapshot_real_cambio_concurrente_y_sesion_cerrada(db, driver, fuente, tmp_path, monkeypatch):
    insertar(db, fuente, [nuevo_evento('ventas', fuente['ventas']['_id'])])
    original = consumidor.resolver_documentos
    proyectar = consumidor.proyectar_documentos
    sesiones = []
    def cambio_concurrente(database, sesion, evento):
        sesiones.append(sesion)
        with db.client.start_session() as otra:
            with otra.start_transaction():
                db.clientes.update_one({'_id': fuente['clientes']['_id']}, {'$set': {'nombre': 'Nuevo'}}, session=otra)
                db.outbox.insert_one(nuevo_evento('clientes', fuente['clientes']['_id']), session=otra)
        documentos = original(database, sesion, evento)
        assert next(d['nombre'] for c, d in documentos if c == 'clientes') == 'Ana'
        return documentos
    def comprobar_cierre(tx, documentos):
        assert all(s.has_ended and not s.in_transaction for s in sesiones)
        return proyectar(tx, documentos)
    with monkeypatch.context() as m:
        m.setattr(consumidor, 'resolver_documentos', cambio_concurrente)
        m.setattr(consumidor, 'proyectar_documentos', comprobar_cierre)
        resultado = consumidor.sincronizar(db, driver, tmp_path / 'lock', max_eventos=1)
    assert resultado['limite_alcanzado'] and resultado['pendientes_observados'] == 1
    assert q10_clientes_sucursal(driver, fuente['sucursales']['_id'])[0]['nombre'] == 'Ana'
    assert consumidor.sincronizar(db, driver, tmp_path / 'lock')['procesados'] == 1
    assert q10_clientes_sucursal(driver, fuente['sucursales']['_id'])[0]['nombre'] == 'Nuevo'


def test_rollback_real_durante_escritura(db, driver, fuente, tmp_path, monkeypatch):
    e = nuevo_evento('ventas', fuente['ventas']['_id'])
    insertar(db, fuente, [e])
    antes = grafo(driver)
    original = consumidor.proyectar_documentos
    def escribir_y_fallar(tx, documentos):
        original(tx, documentos)
        raise Neo4jError('fallo controlado después de las escrituras, antes del commit')
    with monkeypatch.context() as m:
        m.setattr(consumidor, 'proyectar_documentos', escribir_y_fallar)
        resultado = consumidor.sincronizar(db, driver, tmp_path / 'lock')
    assert resultado['fallidos'][0]['codigo'] == 'NEO4J_ESCRITURA'
    assert grafo(driver) == antes
    assert db.outbox.find_one({'_id': e['_id']})['procesado'] is False
