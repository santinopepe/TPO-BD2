from copy import deepcopy
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from bson.int64 import Int64
from neo4j.exceptions import ServiceUnavailable

from farmared.errores import ErrorDominio
from farmared.grafo.mapeos import fecha_comercial, mapear_documento
from farmared.grafo.proyecciones import proyectar_documento, proyectar_documentos


@pytest.mark.parametrize('coleccion', ['clientes', 'sucursales', 'farmaceuticos', 'productos', 'recetas', 'ventas'])
def test_mapeo_campos_tipos_y_sin_mutacion(documentos_proyeccion, coleccion):
    doc = documentos_proyeccion[coleccion]
    antes = deepcopy(doc)
    mapa = mapear_documento(coleccion, doc)
    assert mapa['propiedades']['id'] == doc['_id']
    assert '_id' not in mapa['propiedades']
    assert 'importacion' not in mapa['propiedades']
    assert doc == antes
    if 'activo' in doc:
        assert mapa['propiedades']['activo'] is False
    if coleccion == 'ventas':
        assert mapa['referencias'] == dict(REALIZO=doc['id_cliente'], ATENDIDA_POR=doc['id_farmaceutico'],
                                         USA_RECETA=doc['id_receta'])
        assert mapa['propiedades']['fecha'] == date(2026, 1, 2)
        assert mapa['propiedades']['total'] == 320
        assert mapa['items'] == [
            dict(id_producto=doc['items'][0]['id_producto'], propiedades=dict(
                id_detalle='D1', orden=0, cantidad=2, precio_unit=100, subtotal=200,
                nombre_al_vender='Nombre anterior')),
            dict(id_producto=doc['items'][1]['id_producto'], propiedades=dict(
                id_detalle='D2', orden=1, cantidad=1, precio_unit=120, subtotal=120,
                nombre_al_vender=None)),
        ]
        mapa['items'][0]['propiedades']['precio_unit'] = 1
        assert doc == antes
    elif coleccion == 'farmaceuticos':
        assert mapa['referencias'] == {'TRABAJA_EN': doc['id_sucursal']}
    elif coleccion == 'recetas':
        assert mapa['referencias'] == {'TIENE_RECETA': doc['id_cliente']}
        assert mapa['propiedades']['proxima_dispensa'] is None


@pytest.mark.parametrize('valor,esperado', [
    (datetime(2026, 1, 2, 1, tzinfo=UTC), date(2026, 1, 1)),
    (datetime(2026, 1, 2, 3, tzinfo=UTC), date(2026, 1, 2)),
    (date(2026, 1, 2), date(2026, 1, 2)),
])
def test_fecha_comercial_antes_de_extraer_dia(valor, esperado):
    assert fecha_comercial(valor) == esperado


@pytest.mark.parametrize('valor', [None, '2026-01-02', 123, datetime(2026, 1, 2)])
def test_fecha_invalida_o_sin_zona(valor):
    with pytest.raises(ErrorDominio):
        fecha_comercial(valor)


@pytest.mark.parametrize('id', [None, '', '  ', 1, True])
def test_id_invalido(documentos_proyeccion, id):
    doc = documentos_proyeccion['clientes']
    doc['_id'] = id
    with pytest.raises(ErrorDominio):
        mapear_documento('clientes', doc)


@pytest.mark.parametrize('coleccion,campo,valor', [
    ('clientes', 'activo', 1), ('clientes', 'nombre', None),
    ('ventas', 'total', 1.5), ('ventas', 'total', True), ('ventas', 'total', -1),
    ('ventas', 'items', []), ('ventas', 'items', None), ('ventas', 'items', [None]),
    ('ventas', 'estado', 'inventado'), ('ventas', 'id_cliente', ''),
    ('farmaceuticos', 'id_sucursal', None), ('recetas', 'dispensas_realizadas', True),
    ('recetas', 'dispensas_autorizadas', 4),
])
def test_documentos_mal_formados(documentos_proyeccion, coleccion, campo, valor):
    doc = documentos_proyeccion[coleccion]
    doc[campo] = valor
    with pytest.raises(ErrorDominio):
        mapear_documento(coleccion, doc)


@pytest.mark.parametrize('campo,valor', [('cantidad', True), ('precio_unit', 1.2),
                                        ('subtotal', -1), ('id_producto', None),
                                        ('nombre_al_vender', {}), ('id_detalle', '')])
def test_items_invalidos(documentos_proyeccion, campo, valor):
    doc = documentos_proyeccion['ventas']
    doc['items'][0][campo] = valor
    with pytest.raises(ErrorDominio):
        mapear_documento('ventas', doc)


def test_ids_detalle_unicos_por_venta(documentos_proyeccion):
    doc = documentos_proyeccion['ventas']
    doc['items'][1]['id_detalle'] = 'D1'
    with pytest.raises(ErrorDominio, match='repetido'):
        mapear_documento('ventas', doc)


def test_opcionales_ausentes_y_bson_int64(documentos_proyeccion):
    venta = documentos_proyeccion['ventas']
    venta.pop('id_receta')
    venta['total'] = Int64(320)
    venta['items'][0]['cantidad'] = Int64(2)
    mapa = mapear_documento('ventas', venta)
    assert mapa['referencias']['USA_RECETA'] is None
    assert type(mapa['propiedades']['total']) is int
    assert type(mapa['items'][0]['propiedades']['cantidad']) is int
    receta = documentos_proyeccion['recetas']
    receta.pop('proxima_dispensa')
    assert mapear_documento('recetas', receta)['propiedades']['proxima_dispensa'] is None


@pytest.mark.parametrize('coleccion,doc', [('outbox', {}), ('proveedores', {}), ('clientes', None), (None, {})])
def test_fuentes_no_soportadas(coleccion, doc):
    with pytest.raises(ErrorDominio):
        mapear_documento(coleccion, doc)


def test_validar_unidad_completa_antes_de_escribir(documentos_proyeccion):
    tx = MagicMock()
    with pytest.raises(ErrorDominio):
        proyectar_documentos(tx, [('clientes', documentos_proyeccion['clientes']), ('ventas', {})])
    tx.run.assert_not_called()
    with pytest.raises(ErrorDominio, match='repetido'):
        proyectar_documentos(tx, [('clientes', documentos_proyeccion['clientes'])] * 2)
    tx.run.assert_not_called()


def test_no_confirma_y_propaga_error_driver(documentos_proyeccion):
    tx = MagicMock()
    tx.run.side_effect = ServiceUnavailable('conexión')
    with pytest.raises(ServiceUnavailable):
        proyectar_documento(tx, 'clientes', documentos_proyeccion['clientes'])
    tx.commit.assert_not_called()
    tx.close.assert_not_called()


def test_compatibilidad_documentos_reales_del_loader_sin_motores(tmp_path):
    from farmared.carga.transformacion import transformar_mongo
    from farmared.carga.validacion import rutas_desde_directorios, validar_datasets
    raiz = Path(__file__).resolve().parents[2]
    from farmared.carga.adicionales import generar_adicionales
    adicionales = tmp_path / 'adicionales'
    generar_adicionales(adicionales, raiz / 'data/originales', base_date=date(2026, 11, 10))
    documentos = transformar_mongo(validar_datasets(rutas_desde_directorios(raiz / 'data/originales', adicionales)))
    total = 0
    for coleccion in ('clientes', 'sucursales', 'farmaceuticos', 'recetas', 'productos', 'ventas'):
        for doc in documentos[coleccion]:
            original = deepcopy(doc)
            mapear_documento(coleccion, doc)
            assert doc == original
            total += 1
    assert total > 0
