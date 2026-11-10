from copy import deepcopy
from datetime import date
import json
from unittest.mock import MagicMock

import pytest
from neo4j.time import Date

from farmared.errores import ErrorDominio
from farmared.grafo.mapeos import ETIQUETAS
from farmared.proyeccion import reconstruccion
from farmared.proyeccion.exclusion import exclusion
from farmared.proyeccion.fuente import COLECCIONES, estado_esperado, leer_fuente
from farmared.proyeccion.verificacion import comparar


def observado(esperado):
    nodos = [dict(etiquetas=[e], id=id, propiedades=deepcopy(p), elemento=f'N{i}')
             for i, ((e, id), p) in enumerate(esperado['nodos'].items())]
    relaciones = [dict(tipo=t, origen_etiquetas=[o], origen_id=oi, destino_etiquetas=[d], destino_id=di,
                        propiedades=deepcopy(p), elemento=f'R{i}')
                  for i, ((t, o, oi, d, di, _), p) in enumerate(esperado['relaciones'].items())]
    return nodos, relaciones


@pytest.fixture
def esperado(documentos_proyeccion):
    return estado_esperado(list(documentos_proyeccion.items()))


@pytest.mark.parametrize('aislado,pausadas', [(False, False), (True, False), (False, True), (1, True), (True, 1)])
def test_confirmaciones_requeridas_antes_de_motores(aislado, pausadas, tmp_path):
    db, driver = MagicMock(), MagicMock()
    with pytest.raises(ErrorDominio):
        reconstruccion.reconstruir_grafo(db, driver, tmp_path / 'lock',
            confirmar_entorno_aislado=aislado, confirmar_escrituras_pausadas=pausadas)
    db.client.start_session.assert_not_called()
    driver.session.assert_not_called()


def test_lock_compartido_con_sincronizador(tmp_path):
    with exclusion(tmp_path / 'lock'):
        with pytest.raises(ErrorDominio) as error:
            reconstruccion.reconstruir_grafo(MagicMock(), MagicMock(), tmp_path / 'lock',
                confirmar_entorno_aislado=True, confirmar_escrituras_pausadas=True)
    assert error.value.codigo == 'SYNC_EN_CURSO'


def test_seis_colecciones_snapshot_y_orden_sin_outbox(documentos_proyeccion):
    db = MagicMock()
    cols = {}
    for c in COLECCIONES:
        col = MagicMock()
        col.find.return_value.sort.return_value = [deepcopy(documentos_proyeccion[c])]
        cols[c] = col
    db.__getitem__.side_effect = cols.__getitem__
    assert leer_fuente(db) == list(documentos_proyeccion.items())
    assert COLECCIONES == ('clientes', 'sucursales', 'farmaceuticos', 'productos', 'recetas', 'ventas')
    assert [llamada.args[0] for llamada in db.__getitem__.call_args_list] == list(COLECCIONES)
    sesion = db.client.start_session.return_value.__enter__.return_value
    assert sesion.start_transaction.call_args.kwargs['read_concern'].level == 'snapshot'
    for col in cols.values():
        col.find.assert_called_once_with({}, session=sesion)
        col.update_one.assert_not_called()
        col.delete_many.assert_not_called()
    db.outbox.find.assert_not_called()
    db.outbox.update_many.assert_not_called()


def test_fuente_vacia_y_equivalencia():
    assert estado_esperado([]) == {'nodos': {}, 'relaciones': {}}
    assert comparar(estado_esperado([]), ([], [])) == dict(
        equivalente=True, diferencias=[], conteos=dict(nodos_esperados=0, nodos_observados=0,
                                                      relaciones_esperadas=0, relaciones_observadas=0))


def test_dependencias_faltantes_antes_de_escribir(documentos_proyeccion):
    docs = [(c, d) for c, d in documentos_proyeccion.items() if c != 'productos']
    with pytest.raises(ErrorDominio, match='Dependencia ausente'):
        estado_esperado(docs)


def test_equivalencia_con_date_neo4j_y_opcionales_ausentes(esperado):
    nodos, relaciones = observado(esperado)
    for fila in nodos:
        for k, v in list(fila['propiedades'].items()):
            if type(v) is date:
                fila['propiedades'][k] = Date.from_native(v)
            elif v is None:
                fila['propiedades'].pop(k)
    for fila in relaciones:
        fila['propiedades'] = {k: v for k, v in fila['propiedades'].items() if v is not None}
    assert comparar(esperado, (nodos, relaciones))['equivalente'] is True


@pytest.mark.parametrize('cambio,tipo', [('faltante', 'nodo_faltante'), ('sobrante', 'nodo_sobrante'),
                                      ('propiedad', 'propiedad_diferente'), ('duplicado', 'nodo_duplicado'),
                                      ('tipo', 'propiedad_diferente'), ('extra', 'propiedad_sobrante')])
def test_diferencias_nodos_sin_publicar_datos(esperado, cambio, tipo):
    nodos, relaciones = observado(esperado)
    if cambio == 'faltante':
        nodos.pop(0)
    elif cambio == 'sobrante':
        nodos.append(dict(etiquetas=['Cliente'], id='SOBRANTE', propiedades={}, elemento='extra'))
    elif cambio == 'duplicado':
        nodos.append(deepcopy(nodos[0]))
    elif cambio == 'tipo':
        nodos[0]['propiedades']['activo'] = 0  # False != entero 0.
    elif cambio == 'extra':
        nodos[0]['propiedades']['secreto'] = 'NO PUBLICAR'
    else:
        nodos[0]['propiedades']['nombre'] = 'NO PUBLICAR'
    informe = comparar(esperado, (nodos, relaciones))
    assert informe['equivalente'] is False
    assert tipo in [d['tipo'] for d in informe['diferencias']]
    assert 'NO PUBLICAR' not in json.dumps(informe)


@pytest.mark.parametrize('cambio,tipo', [('faltante', 'relacion_faltante'), ('sobrante', 'relacion_sobrante'),
                                      ('duplicado', 'detalle_duplicado'), ('precio', 'propiedad_relacion_diferente'),
                                      ('producto', 'relacion_sobrante'), ('extra', 'propiedad_relacion_sobrante')])
def test_diferencias_relaciones_y_detalles(esperado, cambio, tipo):
    nodos, relaciones = observado(esperado)
    item = next(r for r in relaciones if r['tipo'] == 'CONTIENE')
    if cambio == 'faltante':
        relaciones.remove(item)
    elif cambio == 'sobrante':
        relaciones.append(dict(item, destino_id='OTRO'))
    elif cambio == 'duplicado':
        relaciones.append(deepcopy(item))
    elif cambio == 'precio':
        item['propiedades']['precio_unit'] = 999
    elif cambio == 'producto':
        item['destino_id'] = 'OTRO'
    else:
        item['propiedades']['ajena'] = 1
    informe = comparar(esperado, (nodos, relaciones))
    assert tipo in [d['tipo'] for d in informe['diferencias']]
    if cambio == 'precio':
        assert next(d for d in informe['diferencias'] if d['tipo'] == tipo)['campo'] == 'precio_unit'


def test_misma_cantidad_no_es_equivalencia_y_fecha_incorrecta(esperado):
    nodos, relaciones = observado(esperado)
    nodos[0]['id'] = 'OTRO-ID'
    fila = next(n for n in nodos if n['etiquetas'] == ['Venta'])
    fila['propiedades']['fecha'] = '2026-01-02'
    informe = comparar(esperado, (nodos, relaciones))
    assert informe['conteos']['nodos_esperados'] == informe['conteos']['nodos_observados']
    assert any(d.get('campo') == 'fecha' for d in informe['diferencias'])
    assert {'nodo_faltante', 'nodo_sobrante'} <= {d['tipo'] for d in informe['diferencias']}


def test_actualizacion_existente_necesita_confirmacion_y_no_borra_nodos(esperado):
    tx = MagicMock()
    tx.run.return_value.data.side_effect = [[dict(etiquetas=['Cliente'], id=next(iter(esperado['nodos']))[1],
                                                propiedades={})], []]
    tx.run.return_value.single.return_value = {'n': 0}
    with pytest.raises(ErrorDominio) as error:
        reconstruccion._validar_destino(tx, esperado, False)
    assert error.value.codigo == 'ACTUALIZACION_NO_CONFIRMADA'
    assert all('DELETE' not in c.args[0] for c in tx.run.call_args_list)


def test_error_recuperable_no_exito_y_lock_liberado(tmp_path, monkeypatch):
    from pymongo.errors import ConnectionFailure
    monkeypatch.setattr(reconstruccion, 'leer_fuente', MagicMock(side_effect=ConnectionFailure('sin conexión')))
    resultado = reconstruccion.reconstruir_grafo(MagicMock(), MagicMock(), tmp_path / 'lock',
        confirmar_entorno_aislado=True, confirmar_escrituras_pausadas=True)
    assert resultado['estado'] == 'error' and resultado['recuperable']
    assert not resultado['habilitable']
    assert resultado['mongo_modificado'] is False and resultado['outbox_modificada'] is False
    with exclusion(tmp_path / 'lock'):
        pass


@pytest.mark.parametrize('id', [None, 1, ['dato-no-publicar']])
def test_identidad_corrupta_en_neo4j_no_rompe_diagnostico(esperado, id):
    nodos, relaciones = observado(esperado)
    nodos[0]['id'] = id
    relaciones[0]['origen_id'] = id
    informe = comparar(esperado, (nodos, relaciones))
    assert not informe['equivalente']
    assert any(d['tipo'] == 'nodo_sin_id' for d in informe['diferencias'])
    assert 'dato-no-publicar' not in json.dumps(informe)


def test_detalle_duplicado_entre_productos_distintos(esperado):
    nodos, relaciones = observado(esperado)
    item = next(r for r in relaciones if r['tipo'] == 'CONTIENE')
    relaciones.append(dict(item, destino_id='OTRO-PRODUCTO'))
    informe = comparar(esperado, (nodos, relaciones))
    assert any(d['tipo'] == 'detalle_duplicado' and d['id_detalle'] == 'D1' for d in informe['diferencias'])
    relaciones[-1]['propiedades'] = dict(item['propiedades'], id_detalle=['invalido'])
    assert any(d['tipo'] == 'detalle_id_invalido' for d in comparar(esperado, (nodos, relaciones))['diferencias'])
