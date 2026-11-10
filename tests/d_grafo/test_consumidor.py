"""Dobles para contratos del consumidor; integración real en otro módulo."""

from copy import deepcopy
from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import MagicMock

import pytest
from neo4j.exceptions import Neo4jError, ServiceUnavailable
from pymongo.errors import ConnectionFailure, OperationFailure

from farmared.errores import ErrorDominio
from farmared.proyeccion import consumidor
from farmared.proyeccion.dependencias import resolver_documentos
from farmared.proyeccion.estado import ErrorEvento, confirmar_evento, validar_evento
from farmared.proyeccion.exclusion import exclusion


def evento(documentos, coleccion='ventas', id='E1'):
    return dict(_id=id, procesado=False, creado_en=datetime(2026, 1, 2, tzinfo=UTC),
                afectadas=[dict(coleccion=coleccion, id=documentos[coleccion]['_id'])])


def dobles(documentos, eventos):
    db, driver = MagicMock(), MagicMock()
    db.with_options.return_value = db
    db.outbox.find_one.side_effect = eventos
    db.outbox.count_documents.return_value = 0
    db.outbox.update_one.return_value.acknowledged = True
    db.outbox.update_one.return_value.matched_count = 1
    db.outbox.update_one.return_value.modified_count = 1
    colecciones = {}
    for nombre, doc in documentos.items():
        col = MagicMock()
        col.find_one.side_effect = lambda filtro, session, doc=doc: deepcopy(doc) if filtro['_id'] == doc['_id'] else None
        colecciones[nombre] = col
    db.__getitem__.side_effect = colecciones.__getitem__
    return db, driver


def test_resuelve_venta_con_productos_repetidos_una_vez_y_orden(documentos_proyeccion):
    docs = documentos_proyeccion
    producto2 = dict(docs['productos'], _id='P-SEGUNDO')
    docs['ventas']['items'].append(dict(docs['ventas']['items'][0], id_detalle='D3', id_producto='P-SEGUNDO'))
    db, _ = dobles(docs, [])
    col = db.__getitem__('productos')
    col.find_one.side_effect = lambda filtro, session: deepcopy(producto2 if filtro['_id'] == 'P-SEGUNDO' else docs['productos'])
    sesion = object()
    resultado = resolver_documentos(db, sesion, evento(docs))
    assert [c for c, _ in resultado] == ['clientes', 'sucursales', 'farmaceuticos', 'recetas', 'productos', 'productos', 'ventas']
    assert col.find_one.call_count == 2
    assert resultado[-1] == ('ventas', docs['ventas'])
    assert all(c.find_one.call_args.kwargs['session'] is sesion for c in (db[n] for n in docs))


def test_resuelve_receta_y_su_cliente(documentos_proyeccion):
    db, _ = dobles(documentos_proyeccion, [])
    assert resolver_documentos(db, object(), evento(documentos_proyeccion, 'recetas')) == [
        ('clientes', documentos_proyeccion['clientes']), ('recetas', documentos_proyeccion['recetas'])]


@pytest.mark.parametrize('raiz,codigo', [(True, 'DOCUMENTO_INEXISTENTE'), (False, 'DEPENDENCIA_INEXISTENTE')])
def test_documento_o_dependencia_faltante(documentos_proyeccion, raiz, codigo):
    db, _ = dobles(documentos_proyeccion, [])
    db['ventas' if raiz else 'productos'].find_one.return_value = None
    db['ventas' if raiz else 'productos'].find_one.side_effect = None
    with pytest.raises(ErrorEvento) as error:
        resolver_documentos(db, object(), evento(documentos_proyeccion))
    assert error.value.codigo == codigo


def test_ciclo_explicito(documentos_proyeccion, monkeypatch):
    from farmared.grafo.mapeos import RELACIONES
    doc = documentos_proyeccion['clientes']
    doc['id_cliente'] = doc['_id']
    monkeypatch.setitem(RELACIONES, 'clientes', {'SELF': ('clientes', 'id_cliente', False)})
    db, _ = dobles(documentos_proyeccion, [])
    with pytest.raises(ErrorEvento, match='ciclo'):
        resolver_documentos(db, object(), evento(documentos_proyeccion, 'clientes'))


def test_snapshot_cerrado_commit_neo4j_y_luego_ack(documentos_proyeccion, tmp_path):
    docs = documentos_proyeccion
    e = evento(docs)
    db, driver = dobles(docs, [e, None])
    pasos = []
    sesion_mongo = db.client.start_session.return_value.__enter__.return_value
    sesion_mongo.start_transaction.return_value.__exit__.side_effect = lambda *a: pasos.append('snapshot_cerrado') or False
    db.client.start_session.return_value.__exit__.side_effect = lambda *a: pasos.append('sesion_cerrada') or False
    sesion_neo = driver.session.return_value.__enter__.return_value
    def escritura(funcion, documentos):
        assert pasos == ['snapshot_cerrado', 'sesion_cerrada']
        assert funcion is consumidor.proyectar_documentos
        assert documentos[-1] == ('ventas', docs['ventas'])
        pasos.append('commit_neo4j')
    sesion_neo.execute_write.side_effect = escritura
    resultado_ack = db.outbox.update_one.return_value
    def ack(*args, **kwargs):
        assert pasos[-1] == 'commit_neo4j'
        pasos.append('ack')
        return resultado_ack
    db.outbox.update_one.side_effect = ack
    resultado = consumidor.sincronizar(db, driver, tmp_path / 'sync.lock')
    assert resultado == dict(procesados=1, eventos_procesados=['E1'], pendientes_observados=0,
                             fallidos=[], limite_alcanzado=False, estado='sin_pendientes_observados')
    db.outbox.find_one.assert_called_with({'procesado': False}, session=sesion_mongo,
                                        sort=[('creado_en', 1), ('_id', 1)])
    db.outbox.update_one.assert_called_once_with({'_id': 'E1', 'procesado': False}, {'$set': {'procesado': True}})
    assert sesion_mongo.start_transaction.call_args.kwargs['read_concern'].level == 'snapshot'
    assert db.with_options.call_args.kwargs['write_concern'].document == {'w': 'majority'}
    driver.close.assert_not_called()


def test_omision_de_procesados_y_resumen_sin_completitud(documentos_proyeccion, tmp_path):
    db, driver = dobles(documentos_proyeccion, [None])
    resultado = consumidor.sincronizar(db, driver, tmp_path / 'lock')
    assert resultado['procesados'] == 0
    assert resultado['estado'] == 'sin_pendientes_observados'
    assert 'completa' not in resultado
    driver.session.assert_not_called()
    db.outbox.update_one.assert_not_called()


@pytest.mark.parametrize('campo,valor', [('_id', ''), ('creado_en', 'fecha'), ('afectadas', []),
                                        ('afectadas', [None]), ('afectadas', [{'coleccion': 'outbox', 'id': 'x'}]),
                                        ('procesado', True)])
def test_evento_invalido(campo, valor, documentos_proyeccion):
    e = evento(documentos_proyeccion)
    e[campo] = valor
    with pytest.raises(ErrorEvento) as error:
        validar_evento(e)
    assert error.value.codigo == 'EVENTO_INVALIDO'


def test_varias_afectadas_sin_duplicar_dependencias(documentos_proyeccion):
    docs = documentos_proyeccion
    e = evento(docs)
    e['afectadas'].append(dict(coleccion='recetas', id=docs['recetas']['_id']))
    db, _ = dobles(docs, [])
    assert len(resolver_documentos(db, object(), e)) == 6
    e['afectadas'].append(e['afectadas'][0])
    with pytest.raises(ErrorEvento):
        validar_evento(e)


@pytest.mark.parametrize('error,codigo', [
    (ServiceUnavailable('credencial-secreta'), 'NEO4J_CONEXION'),
    (Neo4jError('credencial-secreta'), 'NEO4J_ESCRITURA'),
    (ErrorDominio('INTEGRIDAD', 'credencial-secreta'), 'PROYECCION_INTEGRIDAD'),
])
def test_error_neo4j_sin_ack_y_sin_reintento_infinito(error, codigo, documentos_proyeccion, tmp_path):
    db, driver = dobles(documentos_proyeccion, [evento(documentos_proyeccion)])
    driver.session.return_value.__enter__.return_value.execute_write.side_effect = error
    db.outbox.count_documents.return_value = 1
    resultado = consumidor.sincronizar(db, driver, tmp_path / 'lock')
    assert resultado['estado'] == 'error'
    assert resultado['procesados'] == 0
    assert resultado['fallidos'][0]['id_evento'] == 'E1'
    assert resultado['fallidos'][0]['codigo'] == codigo
    assert 'credencial-secreta' not in json.dumps(resultado)
    assert db.outbox.find_one.call_count == 1
    db.outbox.update_one.assert_not_called()
    with exclusion(tmp_path / 'lock'):
        pass


@pytest.mark.parametrize('error,codigo', [(ConnectionFailure('secreto'), 'MONGO_CONEXION'),
                                         (OperationFailure('secreto'), 'MONGO_LECTURA')])
def test_error_mongo_lectura_sin_neo4j(error, codigo, documentos_proyeccion, tmp_path):
    db, driver = dobles(documentos_proyeccion, [])
    db.outbox.find_one.side_effect = error
    resultado = consumidor.sincronizar(db, driver, tmp_path / 'lock')
    assert resultado['fallidos'][0]['codigo'] == codigo
    driver.session.assert_not_called()
    db.outbox.update_one.assert_not_called()


def test_ack_fallido_y_reintento_explicito(documentos_proyeccion, tmp_path):
    db, driver = dobles(documentos_proyeccion, [evento(documentos_proyeccion)])
    db.outbox.update_one.side_effect = ConnectionFailure('no ack')
    db.outbox.count_documents.return_value = 1
    resultado = consumidor.sincronizar(db, driver, tmp_path / 'lock')
    assert resultado['fallidos'][0]['codigo'] == 'OUTBOX_CONFIRMACION'
    assert resultado['fallidos'][0]['neo4j_confirmado'] is True
    assert resultado['procesados'] == 0
    db.outbox.update_one.side_effect = None
    db.outbox.find_one.side_effect = [evento(documentos_proyeccion), None]
    db.outbox.count_documents.return_value = 0
    assert consumidor.sincronizar(db, driver, tmp_path / 'lock')['procesados'] == 1
    assert driver.session.return_value.__enter__.return_value.execute_write.call_count == 2


@pytest.mark.parametrize('ack,matched,modified', [(False, 0, 0), (True, 0, 0), (True, 1, 0)])
def test_confirma_resultado_condicional(ack, matched, modified):
    db = MagicMock()
    db.outbox.update_one.return_value.acknowledged = ack
    db.outbox.update_one.return_value.matched_count = matched
    db.outbox.update_one.return_value.modified_count = modified
    with pytest.raises(ErrorEvento):
        confirmar_evento(db, 'E')


@pytest.mark.parametrize('limite', [0, 1, 2])
def test_limite(documentos_proyeccion, tmp_path, limite):
    db, driver = dobles(documentos_proyeccion, [evento(documentos_proyeccion, id=f'E{i}') for i in range(3)])
    db.outbox.count_documents.return_value = 3 - limite
    resultado = consumidor.sincronizar(db, driver, tmp_path / 'lock', max_eventos=limite)
    assert resultado['procesados'] == limite
    assert resultado['limite_alcanzado'] is True
    assert resultado['pendientes_observados'] == 3 - limite
    assert db.outbox.update_one.call_count == limite


@pytest.mark.parametrize('limite', [True, -1, 1.5, '1'])
def test_validar_limite_antes_de_motores(limite, tmp_path):
    db, driver = MagicMock(), MagicMock()
    with pytest.raises(ErrorDominio) as error:
        consumidor.sincronizar(db, driver, tmp_path / 'lock', max_eventos=limite)
    assert error.value.codigo == 'VALIDACION'
    db.with_options.assert_not_called()


def test_bloqueo_real_otro_proceso_y_liberacion_por_caida(tmp_path):
    ruta = tmp_path / 'compartido.lock'
    codigo = ('import sys; from farmared.proyeccion.exclusion import exclusion; '
              'ctx=exclusion(sys.argv[1]); ctx.__enter__(); print("BLOQUEADO", flush=True); sys.stdin.readline()')
    proceso = subprocess.Popen([sys.executable, '-c', codigo, str(ruta)], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert proceso.stdout.readline().strip() == 'BLOQUEADO'
        db, driver = MagicMock(), MagicMock()
        with pytest.raises(ErrorDominio) as error:
            consumidor.sincronizar(db, driver, ruta)
        assert error.value.codigo == 'SYNC_EN_CURSO'
        db.with_options.assert_not_called()
    finally:
        proceso.kill()
        proceso.communicate(timeout=10)
    assert ruta.exists()  # El archivo persiste; el lock del SO ya fue liberado.
    with exclusion(ruta):
        pass


def test_error_inesperado_no_se_oculta_y_libera_lock(documentos_proyeccion, tmp_path):
    db, driver = dobles(documentos_proyeccion, [evento(documentos_proyeccion)])
    driver.session.return_value.__enter__.return_value.execute_write.side_effect = RuntimeError('bug')
    with pytest.raises(RuntimeError):
        consumidor.sincronizar(db, driver, tmp_path / 'lock')
    with exclusion(tmp_path / 'lock'):
        pass


@pytest.mark.parametrize('ruta', [None, '', '  ', [], 1])
def test_ruta_lock_invalida(ruta):
    with pytest.raises(ErrorDominio) as error:
        with exclusion(ruta):
            pass
    assert error.value.codigo == 'VALIDACION'


def test_directorio_no_es_lock(tmp_path):
    with pytest.raises(ErrorDominio):
        with exclusion(tmp_path):
            pass


def test_evento_malformado_detiene_sin_marcar(documentos_proyeccion, tmp_path):
    e = evento(documentos_proyeccion)
    e['afectadas'] = []
    db, driver = dobles(documentos_proyeccion, [e])
    db.outbox.count_documents.return_value = 1
    resultado = consumidor.sincronizar(db, driver, tmp_path / 'lock')
    assert resultado['fallidos'][0]['codigo'] == 'EVENTO_INVALIDO'
    assert resultado['fallidos'][0]['id_evento'] == 'E1'
    db.outbox.update_one.assert_not_called()
    driver.session.assert_not_called()


def test_documento_invalido_y_error_recuento(documentos_proyeccion, tmp_path):
    documentos_proyeccion['clientes']['activo'] = 'False'
    db, driver = dobles(documentos_proyeccion, [evento(documentos_proyeccion)])
    db.outbox.count_documents.side_effect = ConnectionFailure('no disponible')
    resultado = consumidor.sincronizar(db, driver, tmp_path / 'lock')
    assert [e['codigo'] for e in resultado['fallidos']] == ['DOCUMENTO_INVALIDO', 'MONGO_CONEXION']
    assert resultado['pendientes_observados'] is None
    assert resultado['estado'] == 'error'
    driver.session.assert_not_called()


def test_evento_nuevo_entre_snapshot_vacio_y_recuento(documentos_proyeccion, tmp_path):
    db, driver = dobles(documentos_proyeccion, [None])
    db.outbox.count_documents.return_value = 1
    resultado = consumidor.sincronizar(db, driver, tmp_path / 'lock')
    assert resultado['estado'] == 'pendientes_observados'
    assert resultado['pendientes_observados'] == 1
    assert resultado['procesados'] == 0 and resultado['fallidos'] == []
    driver.session.assert_not_called()
