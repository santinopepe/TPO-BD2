"""Administración real en contenedores exclusivos; limpieza solo por IDs del fixture."""

from copy import deepcopy
from datetime import UTC, datetime
import json
import os
from uuid import uuid4

import pytest
from neo4j.exceptions import Neo4jError

from farmared.consultas.q03 import q03_historial
from farmared.consultas.q04 import q04_clientes_con_recetas
from farmared.consultas.q10 import q10_clientes_sucursal
from farmared.proyeccion import reconstruccion, reconstruir_grafo, sincronizar, verificar_proyeccion

pytestmark = pytest.mark.skipif(os.environ.get('FARMARED_TEST_SYNC') != '1',
                               reason='Activar FARMARED_TEST_SYNC=1 para reconstrucción aislada.')


def snapshot_mongo(db, *, outbox=True):
    nombres = ['clientes', 'sucursales', 'farmaceuticos', 'productos', 'recetas', 'ventas']
    if outbox:
        nombres.append('outbox')
    return {c: list(db[c].find({}).sort('_id', 1)) for c in nombres}


def snapshot_grafo(driver):
    with driver.session() as sesion:
        return (sesion.run('MATCH (n) RETURN labels(n) AS e, properties(n) AS p ORDER BY n.id').data(),
                sesion.run('MATCH (a)-[r]->(b) RETURN a.id AS a, b.id AS b, type(r) AS t, properties(r) AS p '
                           'ORDER BY a,b,t,r.id_detalle').data())


@pytest.fixture
def admin(db_sync, driver, fuente, tmp_path):
    ids = [d['_id'] for d in fuente.values()]
    segunda = dict(fuente['recetas'], _id=fuente['recetas']['_id'] + '-2')
    ids.append(segunda['_id'])
    eventos = []
    with db_sync.client.start_session() as sesion:
        with sesion.start_transaction():
            for c, doc in list(fuente.items()) + [('recetas', segunda)]:
                db_sync[c].insert_one(deepcopy(doc), session=sesion)
                e = dict(_id='REC-' + uuid4().hex, procesado=False, creado_en=datetime(2026, 1, 1, tzinfo=UTC),
                         afectadas=[dict(coleccion=c, id=doc['_id'])])
                db_sync.outbox.insert_one(e, session=sesion)
                eventos.append(e['_id'])
    contexto = dict(db=db_sync, driver=driver, fuente=fuente, segunda=segunda, ids=ids,
                    lock=tmp_path / 'admin.lock', eventos=eventos, restricciones=[])
    try:
        yield contexto
    finally:
        # Solo artefactos de este fixture en un contenedor privado, nunca una base compartida.
        with driver.session() as sesion:
            sesion.run('MATCH (n) WHERE n.id IN $ids DETACH DELETE n', ids=contexto['ids']).consume()
            for nombre in contexto['restricciones']:
                sesion.run(f'DROP CONSTRAINT {nombre} IF EXISTS').consume()


def reconstruir(a, *, actualizar=False):
    return reconstruir_grafo(a['db'], a['driver'], a['lock'], confirmar_entorno_aislado=True,
                            confirmar_escrituras_pausadas=True, confirmar_actualizacion_existente=actualizar)


def verificar(a):
    return verificar_proyeccion(a['db'], a['driver'], a['lock'], confirmar_escrituras_pausadas=True)


def test_a_inicial_todas_entidades_consultas_y_g_detalles(admin):
    a, docs = admin, admin['fuente']
    antes = snapshot_mongo(a['db'])
    resultado = reconstruir(a)
    assert resultado['estado'] == 'verificada' and resultado['habilitable']
    assert resultado['verificacion']['conteos'] == dict(nodos_esperados=7, nodos_observados=7,
                                                        relaciones_esperadas=8, relaciones_observadas=8)
    assert verificar(a)['equivalente']
    assert snapshot_mongo(a['db']) == antes
    historial = q03_historial(a['driver'], docs['clientes']['_id'])
    assert [r['tipo_evento'] for r in historial] == ['RECETA', 'RECETA', 'VENTA']
    assert [(i['id_detalle'], i['id_producto'], i['precio_unit']) for i in historial[-1]['detalle']['items']] == [
        ('D1', docs['productos']['_id'], 100), ('D2', docs['productos']['_id'], 120)]
    assert q04_clientes_con_recetas(a['driver']) == [
        dict(id_cliente=docs['clientes']['_id'], nombre='Ana', apellido='Prueba', cantidad=2)]
    assert q10_clientes_sucursal(a['driver'], docs['sucursales']['_id']) == [
        dict(id_cliente=docs['clientes']['_id'], nombre='Ana', apellido='Prueba')]
    print('\nReconstrucción real:', resultado)


def test_b_repetida_confirmacion_y_sin_duplicados(admin):
    assert reconstruir(admin)['habilitable']
    antes = snapshot_grafo(admin['driver']), snapshot_mongo(admin['db'])
    rechazo = reconstruir(admin)
    assert rechazo['error']['codigo'] == 'ACTUALIZACION_NO_CONFIRMADA'
    assert not rechazo['habilitable']
    assert reconstruir(admin, actualizar=True)['habilitable']
    assert (snapshot_grafo(admin['driver']), snapshot_mongo(admin['db'])) == antes


def test_c_outbox_historica_procesada_no_se_reinicia(admin):
    a = admin
    a['db'].outbox.update_many({}, {'$set': {'procesado': True}})  # Preparación explícita del fixture.
    antes = snapshot_mongo(a['db'])
    assert reconstruir(a)['habilitable']
    assert snapshot_mongo(a['db']) == antes
    assert verificar(a)['equivalente']


@pytest.mark.parametrize('caso,tipo,campo', [
    ('nombre', 'propiedad_diferente', 'nombre'), ('fecha', 'propiedad_diferente', 'fecha'),
    ('precio', 'propiedad_relacion_diferente', 'precio_unit'),
    ('relacion_faltante', 'relacion_faltante', None), ('relacion_sobrante', 'relacion_sobrante', None),
    ('duplicado', 'detalle_duplicado', None), ('nodo_faltante', 'nodo_faltante', None),
    ('nodo_sobrante', 'nodo_sobrante', None), ('misma_cantidad', 'nodo_faltante', None),
])
def test_d_diferencias_exactas_reales(admin, caso, tipo, campo):
    a, docs = admin, admin['fuente']
    assert reconstruir(a)['habilitable']
    with a['driver'].session() as sesion:
        if caso == 'nombre':
            sesion.run('MATCH (c:Cliente {id:$id}) SET c.nombre=$nombre', id=docs['clientes']['_id'],
                       nombre='NO DEBE PUBLICARSE').consume()
        elif caso == 'fecha':
            sesion.run("MATCH (v:Venta {id:$id}) SET v.fecha=date('2026-01-03')", id=docs['ventas']['_id']).consume()
        elif caso == 'precio':
            sesion.run("MATCH (:Venta {id:$id})-[r:CONTIENE {id_detalle:'D1'}]->() SET r.precio_unit=999",
                       id=docs['ventas']['_id']).consume()
        elif caso == 'relacion_faltante':
            sesion.run('MATCH ()-[r:REALIZO]->(:Venta {id:$id}) DELETE r', id=docs['ventas']['_id']).consume()
        elif caso == 'relacion_sobrante':
            sesion.run('MATCH (v:Venta {id:$v}), (r:Receta {id:$r}) CREATE (v)-[:USA_RECETA]->(r)',
                       v=docs['ventas']['_id'], r=a['segunda']['_id']).consume()
        elif caso == 'duplicado':
            sesion.run("MATCH (v:Venta {id:$id})-[r:CONTIENE {id_detalle:'D1'}]->(p) "
                       'CREATE (v)-[otro:CONTIENE]->(p) SET otro=properties(r)', id=docs['ventas']['_id']).consume()
        elif caso == 'nodo_faltante':
            sesion.run('MATCH (p:Producto {id:$id}) DETACH DELETE p', id=docs['productos']['_id']).consume()
        else:
            extra = docs['productos']['_id'] + '-EXTRA'
            a['ids'].append(extra)
            if caso == 'nodo_sobrante':
                sesion.run('CREATE (:Producto {id:$id})', id=extra).consume()
            else:
                sesion.run('MATCH (p:Producto {id:$id}) SET p.id=$extra', id=docs['productos']['_id'], extra=extra).consume()
    antes = snapshot_mongo(a['db'])
    informe = verificar(a)
    assert not informe['equivalente']
    diferencia = next(d for d in informe['diferencias'] if d['tipo'] == tipo)
    if campo:
        assert diferencia['campo'] == campo
    if caso == 'precio':
        assert diferencia['origen']['id'] == docs['ventas']['_id']
        assert diferencia['id_detalle'] == 'D1'
    if caso == 'misma_cantidad':
        assert informe['conteos']['nodos_esperados'] == informe['conteos']['nodos_observados']
        assert any(d['tipo'] == 'nodo_sobrante' for d in informe['diferencias'])
    assert 'NO DEBE PUBLICARSE' not in json.dumps(informe)
    if caso not in ('nodo_sobrante', 'misma_cantidad'):
        assert reconstruir(a, actualizar=True)['habilitable']
        assert verificar(a)['equivalente']
    else:
        grafo_antes = snapshot_grafo(a['driver'])
        assert reconstruir(a, actualizar=True)['error']['codigo'] == 'DESTINO_NO_AISLADO'
        assert snapshot_grafo(a['driver']) == grafo_antes
    assert snapshot_mongo(a['db']) == antes


@pytest.mark.parametrize('existente', [False, True])
def test_e_falla_durante_escrituras_rollback_y_recuperacion(admin, monkeypatch, existente):
    a = admin
    if existente:
        assert reconstruir(a)['habilitable']
        with a['db'].client.start_session() as s:
            with s.start_transaction():
                a['db'].clientes.update_one({'_id': a['fuente']['clientes']['_id']}, {'$set': {'nombre': 'Nueva'}}, session=s)
                a['db'].outbox.insert_one(dict(_id='CAMBIO', procesado=False, creado_en=datetime.now(UTC),
                    afectadas=[dict(coleccion='clientes', id=a['fuente']['clientes']['_id'])]), session=s)
    mongo_antes, neo_antes = snapshot_mongo(a['db']), snapshot_grafo(a['driver'])
    original = reconstruccion.proyectar_documentos
    def falla(tx, documentos):
        original(tx, documentos)
        raise Neo4jError('fallo inyectado antes del commit')
    with monkeypatch.context() as m:
        m.setattr(reconstruccion, 'proyectar_documentos', falla)
        resultado = reconstruir(a, actualizar=existente)
    assert resultado['estado'] == 'error' and resultado['recuperable'] and not resultado['habilitable']
    assert snapshot_mongo(a['db']) == mongo_antes
    assert snapshot_grafo(a['driver']) == neo_antes
    assert reconstruir(a, actualizar=existente)['habilitable']
    assert verificar(a)['equivalente']


def test_f_reentrega_pendientes_tras_reconstruccion(admin):
    a = admin
    assert reconstruir(a)['habilitable']
    assert a['db'].outbox.count_documents({'procesado': False}) == 7
    antes = snapshot_grafo(a['driver']), snapshot_mongo(a['db'], outbox=False)
    resultado = sincronizar(a['db'], a['driver'], a['lock'])
    assert resultado['procesados'] == 7 and resultado['fallidos'] == []
    assert (snapshot_grafo(a['driver']), snapshot_mongo(a['db'], outbox=False)) == antes
    assert verificar(a)['equivalente']


def test_fuente_y_destino_vacios(db_sync, driver, tmp_path):
    resultado = reconstruir_grafo(db_sync, driver, tmp_path / 'lock', confirmar_entorno_aislado=True,
                                 confirmar_escrituras_pausadas=True)
    assert resultado['habilitable']
    assert resultado['verificacion']['conteos']['nodos_observados'] == 0


@pytest.mark.parametrize('solo_restriccion', [False, True])
def test_destino_ajeno_y_restricciones_conservadas(admin, solo_restriccion):
    a = admin
    extra = 'AUX-' + uuid4().hex
    nombre = 'aux_' + uuid4().hex
    a['ids'].append(extra)
    a['restricciones'].append(nombre)
    with a['driver'].session() as s:
        if not solo_restriccion:
            s.run('CREATE (:Ajeno {id:$id})', id=extra).consume()
        s.run(f'CREATE CONSTRAINT {nombre} FOR (n:Ajeno) REQUIRE n.id IS UNIQUE').consume()
    antes = snapshot_grafo(a['driver']), snapshot_mongo(a['db'])
    resultado = reconstruir(a, actualizar=True)
    assert resultado['error']['codigo'] == 'DESTINO_NO_AISLADO'
    assert (snapshot_grafo(a['driver']), snapshot_mongo(a['db'])) == antes
    with a['driver'].session() as s:
        assert s.run('SHOW CONSTRAINTS YIELD name WHERE name=$nombre RETURN name', nombre=nombre).single()



def test_dependencia_fuente_ausente_no_cambia_motores(admin):
    a = admin
    # Corrupción controlada del fixture, anterior a la llamada administrativa.
    a['db'].productos.delete_one({'_id': a['fuente']['productos']['_id']})
    antes = snapshot_mongo(a['db']), snapshot_grafo(a['driver'])
    resultado = reconstruir(a)
    assert resultado['estado'] == 'error' and not resultado['habilitable']
    assert resultado['error']['codigo'] == 'INTEGRIDAD'
    assert (snapshot_mongo(a['db']), snapshot_grafo(a['driver'])) == antes
