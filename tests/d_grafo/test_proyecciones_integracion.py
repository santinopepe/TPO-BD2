"""Proyección real de fixtures; no utiliza MongoDB ni el destino compartido."""

from copy import deepcopy
from datetime import UTC, date, datetime
import os

import pytest

from farmared.consultas.q03 import q03_historial
from farmared.consultas.q04 import q04_clientes_con_recetas
from farmared.consultas.q10 import q10_clientes_sucursal
from farmared.errores import ErrorDominio
from farmared.grafo import preparar_grafo
from farmared.grafo.proyecciones import proyectar_documento, proyectar_documentos

pytestmark = pytest.mark.skipif(os.environ.get('FARMARED_TEST_GRAFO') != '1',
                               reason='Activar FARMARED_TEST_GRAFO=1 para Neo4j aislado.')


@pytest.fixture(scope='module', autouse=True)
def esquema(driver):
    preparar_grafo(driver)


def escribir(driver, documentos):
    with driver.session() as sesion:
        sesion.execute_write(proyectar_documentos, documentos)


def leer(driver, cypher, **params):
    with driver.session() as sesion:
        return sesion.run(cypher, **params).data()


def snapshot(driver):
    return (leer(driver, 'MATCH (n) RETURN elementId(n) AS id, properties(n) AS props ORDER BY id'),
            leer(driver, 'MATCH (a)-[r]->(b) RETURN elementId(r) AS id, elementId(a) AS a, '
                 'elementId(b) AS b, type(r) AS tipo, properties(r) AS props ORDER BY id'))


def test_cliente_idempotente_actualiza_y_conserva_propiedades_ajenas(driver, documentos_proyeccion):
    cliente = documentos_proyeccion['clientes']
    escribir(driver, [('clientes', cliente)])
    escribir(driver, [('clientes', cliente)])
    cliente['nombre'] = 'Actualizada'
    with driver.session() as sesion:
        sesion.run('MATCH (c:Cliente {id:$id}) SET c.ajena=1', id=cliente['_id']).consume()
        sesion.execute_write(proyectar_documento, 'clientes', cliente)
    assert leer(driver, 'MATCH (c:Cliente {id:$id}) RETURN properties(c) AS p', id=cliente['_id']) == [
        {'p': dict(id=cliente['_id'], nombre='Actualizada', apellido='Prueba', activo=False, ajena=1)}]


def test_modelo_completo_y_consultas_reales(driver, documentos_proyeccion):
    docs = documentos_proyeccion
    segunda = deepcopy(docs['recetas'])
    segunda['_id'] += '-2'
    segunda['estado'] = 'Vencida'
    # Dependencias en orden inverso: todos los nodos se escriben antes de reconciliar.
    escribir(driver, list(reversed(list(docs.items()))) + [('recetas', segunda)])
    escribir(driver, list(docs.items()))
    venta = docs['ventas']
    assert leer(driver, 'MATCH (v:Venta {id:$id})-[r:CONTIENE]->(p:Producto) '
                'RETURN r.id_detalle AS id, p.id AS producto, r.precio_unit AS precio ORDER BY id',
                id=venta['_id']) == [
        {'id': 'D1', 'producto': docs['productos']['_id'], 'precio': 100},
        {'id': 'D2', 'producto': docs['productos']['_id'], 'precio': 120}]
    assert leer(driver, 'MATCH (c:Cliente {id:$c})-[:REALIZO]->(v:Venta {id:$v})'
                '-[:ATENDIDA_POR]->(f:Farmaceutico)-[:TRABAJA_EN]->(s:Sucursal) '
                'MATCH (v)-[:USA_RECETA]->(r:Receta)<-[:TIENE_RECETA]-(c) '
                'RETURN f.id AS f, s.id AS s, r.id AS r', c=docs['clientes']['_id'], v=venta['_id']) == [
        dict(f=docs['farmaceuticos']['_id'], s=docs['sucursales']['_id'], r=docs['recetas']['_id'])]
    esperado_receta = dict(tipo='Simple', medico='Médico prueba', dispensas_realizadas=1,
                          dispensas_autorizadas=1, proxima_dispensa=None)
    assert q03_historial(driver, docs['clientes']['_id']) == [
        dict(fecha=date(2026, 1, 1), tipo_evento='RECETA', id_registro=docs['recetas']['_id'],
             estado='Completada', detalle=esperado_receta),
        dict(fecha=date(2026, 1, 1), tipo_evento='RECETA', id_registro=segunda['_id'],
             estado='Vencida', detalle=esperado_receta),
        dict(fecha=date(2026, 1, 2), tipo_evento='VENTA', id_registro=venta['_id'], estado='Pendiente',
             detalle=dict(tipo='Con receta', total=320, medio_pago='Efectivo', id_receta=docs['recetas']['_id'],
                          items=[dict(id_detalle='D1', orden=0, id_producto=docs['productos']['_id'],
                                      nombre_al_vender='Nombre anterior', cantidad=2, precio_unit=100, subtotal=200),
                                 dict(id_detalle='D2', orden=1, id_producto=docs['productos']['_id'],
                                      nombre_al_vender=None, cantidad=1, precio_unit=120, subtotal=120)])),
    ]
    assert [r for r in q04_clientes_con_recetas(driver) if r['id_cliente'] == docs['clientes']['_id']] == [
        dict(id_cliente=docs['clientes']['_id'], nombre='Ana', apellido='Prueba', cantidad=2)]
    assert q10_clientes_sucursal(driver, docs['sucursales']['_id']) == [
        dict(id_cliente=docs['clientes']['_id'], nombre='Ana', apellido='Prueba')]


def test_reconciliar_items_producto_receta_y_aislar_otras_ventas(driver, documentos_proyeccion):
    docs = documentos_proyeccion
    otra = deepcopy(docs['ventas'])
    otra['_id'] += '-otra'
    escribir(driver, list(docs.items()) + [('ventas', otra)])
    antes_otra = leer(driver, 'MATCH (:Venta {id:$id})-[r]->(n) '
                      'RETURN elementId(r) AS r, n.id AS destino, properties(r) AS props ORDER BY r',
                      id=otra['_id'])
    producto2 = deepcopy(docs['productos'])
    producto2['_id'] += '-2'
    receta2 = deepcopy(docs['recetas'])
    receta2['_id'] += '-2'
    venta = deepcopy(docs['ventas'])
    venta['items'] = [dict(venta['items'][1], id_producto=producto2['_id'], precio_unit=400, subtotal=400)]
    venta['id_receta'] = receta2['_id']
    venta.update(total=400, estado='Completada')
    escribir(driver, [('ventas', venta), ('productos', producto2), ('recetas', receta2)])
    assert leer(driver, 'MATCH (:Venta {id:$id})-[r:CONTIENE]->(p) '
                'RETURN r.id_detalle AS id, r.orden AS orden, r.precio_unit AS precio, p.id AS p',
                id=venta['_id']) == [dict(id='D2', orden=0, precio=400, p=producto2['_id'])]
    assert leer(driver, 'MATCH (:Venta {id:$id})-[:USA_RECETA]->(r) RETURN r.id AS id',
                id=venta['_id']) == [{'id': receta2['_id']}]
    venta.pop('id_receta')
    escribir(driver, [('ventas', venta)])
    assert leer(driver, 'MATCH (:Venta {id:$id})-[:USA_RECETA]->(r) RETURN r.id', id=venta['_id']) == []
    assert leer(driver, 'MATCH (:Venta {id:$id})-[r]->(n) '
                'RETURN elementId(r) AS r, n.id AS destino, properties(r) AS props ORDER BY r',
                id=otra['_id']) == antes_otra
    assert leer(driver, 'MATCH (p:Producto) WHERE p.id IN $ids RETURN count(p) AS n',
                ids=[producto2['_id'], docs['productos']['_id']]) == [{'n': 2}]
    evento = next(e for e in q03_historial(driver, docs['clientes']['_id']) if e['id_registro'] == venta['_id'])
    assert evento['estado'] == 'Completada'
    assert evento['detalle']['id_receta'] is None
    assert evento['detalle']['items'][0]['precio_unit'] == 400


def test_farmaceutico_cambia_sucursal_sin_usar_venta_id_sucursal(driver, documentos_proyeccion):
    docs = documentos_proyeccion
    escribir(driver, list(docs.items()))
    nueva = deepcopy(docs['sucursales'])
    nueva['_id'] += '-nueva'
    profesional = deepcopy(docs['farmaceuticos'])
    profesional['id_sucursal'] = nueva['_id']
    escribir(driver, [('farmaceuticos', profesional), ('sucursales', nueva)])
    assert leer(driver, 'MATCH (:Farmaceutico {id:$id})-[:TRABAJA_EN]->(s) RETURN s.id AS id',
                id=profesional['_id']) == [{'id': nueva['_id']}]
    assert q10_clientes_sucursal(driver, docs['sucursales']['_id']) == []
    assert q10_clientes_sucursal(driver, nueva['_id']) == [
        dict(id_cliente=docs['clientes']['_id'], nombre='Ana', apellido='Prueba')]


@pytest.mark.parametrize('dependencia', ['id_cliente', 'id_farmaceutico', 'id_receta', 'id_producto'])
def test_dependencia_faltante_rollback_completo(driver, documentos_proyeccion, dependencia):
    docs = documentos_proyeccion
    escribir(driver, list(docs.items()))
    antes = snapshot(driver)
    venta = deepcopy(docs['ventas'])
    if dependencia == 'id_producto':
        venta['items'][1]['id_producto'] = 'INEXISTENTE'
    else:
        venta[dependencia] = 'INEXISTENTE'
    cliente = dict(docs['clientes'], nombre='NO DEBE CONFIRMARSE')
    with pytest.raises(ErrorDominio, match='Dependencia'):
        escribir(driver, [('clientes', cliente), ('ventas', venta)])
    assert snapshot(driver) == antes
    venta['_id'] += '-nueva'
    with pytest.raises(ErrorDominio):
        escribir(driver, [('ventas', venta)])
    assert snapshot(driver) == antes


def test_dependencia_incompleta_no_se_adopta(driver, documentos_proyeccion):
    docs = documentos_proyeccion
    escribir(driver, [(c, d) for c, d in docs.items() if c not in ('productos', 'ventas')])
    with driver.session() as sesion:
        sesion.run('CREATE (:Producto {id:$id})', id=docs['productos']['_id']).consume()
    antes = snapshot(driver)
    with pytest.raises(ErrorDominio, match='incompleta'):
        escribir(driver, [('ventas', docs['ventas'])])
    assert snapshot(driver) == antes


def test_receta_reasigna_titular_y_quita_fecha_opcional(driver, documentos_proyeccion):
    docs = documentos_proyeccion
    docs['recetas']['proxima_dispensa'] = datetime(2026, 1, 3, 1, tzinfo=UTC)
    escribir(driver, list(docs.items()))
    assert q03_historial(driver, docs['clientes']['_id'])[0]['detalle']['proxima_dispensa'] == date(2026, 1, 2)
    nuevo = dict(docs['clientes'], _id=docs['clientes']['_id'] + '-nuevo')
    receta = dict(docs['recetas'], id_cliente=nuevo['_id'], estado='Vencida')
    receta.pop('proxima_dispensa')
    escribir(driver, [('recetas', receta), ('clientes', nuevo)])
    assert leer(driver, 'MATCH (c)-[:TIENE_RECETA]->(:Receta {id:$id}) RETURN c.id AS id',
                id=receta['_id']) == [{'id': nuevo['_id']}]
    assert leer(driver, 'MATCH (r:Receta {id:$id}) RETURN r.proxima_dispensa AS fecha, r.estado AS estado',
                id=receta['_id']) == [dict(fecha=None, estado='Vencida')]
    assert leer(driver, 'MATCH (:Venta {id:$id})-[:USA_RECETA]->(r) RETURN r.id AS id',
                id=docs['ventas']['_id']) == [{'id': receta['_id']}]


def test_venta_reasigna_cliente_y_profesional_sin_tocar_otra_venta(driver, documentos_proyeccion):
    docs = documentos_proyeccion
    otra = dict(docs['ventas'], _id=docs['ventas']['_id'] + '-otra')
    escribir(driver, list(docs.items()) + [('ventas', otra)])
    nuevo_cliente = dict(docs['clientes'], _id=docs['clientes']['_id'] + '-nuevo')
    nuevo_profesional = dict(docs['farmaceuticos'], _id=docs['farmaceuticos']['_id'] + '-nuevo')
    venta = dict(docs['ventas'], id_cliente=nuevo_cliente['_id'],
                 id_farmaceutico=nuevo_profesional['_id'], id_receta=None)
    escribir(driver, [('ventas', venta), ('clientes', nuevo_cliente), ('farmaceuticos', nuevo_profesional)])
    assert leer(driver, 'MATCH (c:Cliente)-[:REALIZO]->(v:Venta {id:$id})-[:ATENDIDA_POR]->(f) '
                'RETURN c.id AS c, f.id AS f', id=venta['_id']) == [
        dict(c=nuevo_cliente['_id'], f=nuevo_profesional['_id'])]
    assert leer(driver, 'MATCH (c:Cliente)-[:REALIZO]->(v:Venta {id:$id})-[:ATENDIDA_POR]->(f) '
                'RETURN c.id AS c, f.id AS f', id=otra['_id']) == [
        dict(c=docs['clientes']['_id'], f=docs['farmaceuticos']['_id'])]
