"""Procesamiento recuperable bajo demanda: snapshot → Neo4j → ack MongoDB."""

from neo4j.exceptions import DriverError, Neo4jError
from pymongo import ReadPreference
from pymongo.errors import PyMongoError
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from farmared.errores import CodigoError, ErrorDominio
from farmared.grafo.proyecciones import proyectar_documentos
from farmared.proyeccion.dependencias import resolver_documentos
from farmared.proyeccion.estado import ErrorEvento, confirmar_evento, diagnostico, error_mongo
from farmared.proyeccion.exclusion import exclusion


def _leer_snapshot(db):
    evento = None
    try:
        with db.client.start_session() as sesion:
            with sesion.start_transaction(read_concern=ReadConcern('snapshot'),
                                          write_concern=WriteConcern('majority'),
                                          read_preference=ReadPreference.PRIMARY):
                evento = db.outbox.find_one({'procesado': False}, session=sesion,
                                           sort=[('creado_en', 1), ('_id', 1)])
                if evento is None:
                    return None
                documentos = resolver_documentos(db, sesion, evento)
        # Los dos contextos MongoDB ya terminaron antes de escribir Neo4j.
        return evento['_id'], documentos
    except PyMongoError as error:
        raise ErrorEvento(evento.get('_id') if evento else None, error_mongo(error),
                          'No se pudo completar la lectura snapshot de MongoDB.') from None


def sincronizar(db, driver, lock_path, *, max_eventos: int | None = None) -> dict:
    """Procesa pendientes hasta agotarlos en una observación, un límite o un error.

    Requiere esquema Neo4j preparado y un mismo lock para todos los consumidores
    del entorno. No abre conexiones ni cierra db/driver. max_eventos=0 solo observa.
    Un error de evento detiene la ejecución sin reintento de ese evento en el bucle.
    Un resultado sin pendientes no certifica consistencia global ni futura.
    """
    if max_eventos is not None and (type(max_eventos) is not int or max_eventos < 0):
        raise ErrorDominio(CodigoError.VALIDACION, 'max_eventos debe ser None o un entero no negativo.')
    resumen = dict(procesados=0, eventos_procesados=[], pendientes_observados=None,
                   fallidos=[], limite_alcanzado=False, estado='sin_pendientes_observados')
    with exclusion(lock_path):
        # Usa majority para observación y ack incluso si el llamador pasó otro Database.
        db = db.with_options(read_concern=ReadConcern('majority'), write_concern=WriteConcern('majority'),
                             read_preference=ReadPreference.PRIMARY)
        while max_eventos is None or resumen['procesados'] < max_eventos:
            try:
                unidad = _leer_snapshot(db)
            except ErrorEvento as error:
                resumen['fallidos'].append(diagnostico(error.id_evento, error.codigo, error.mensaje))
                break
            if unidad is None:
                break
            id_evento, documentos = unidad
            try:
                with driver.session() as sesion:
                    sesion.execute_write(proyectar_documentos, documentos)
            except DriverError:
                resumen['fallidos'].append(diagnostico(id_evento, 'NEO4J_CONEXION',
                                                       'No se confirmó la transacción Neo4j; revisar conectividad.'))
                break
            except Neo4jError:
                resumen['fallidos'].append(diagnostico(id_evento, 'NEO4J_ESCRITURA',
                                                       'Neo4j rechazó la proyección; revisar permisos o restricciones.'))
                break
            except ErrorDominio as error:
                resumen['fallidos'].append(diagnostico(id_evento, 'PROYECCION_' + error.codigo,
                                                       'La proyección no pudo asegurar las relaciones requeridas.'))
                break
            try:
                confirmar_evento(db, id_evento)
            except (PyMongoError, ErrorEvento):
                resumen['fallidos'].append(diagnostico(id_evento, 'OUTBOX_CONFIRMACION',
                    'Neo4j confirmó pero no se pudo confirmar el ack MongoDB; reentrega segura.',
                    neo4j_confirmado=True))
                break
            resumen['procesados'] += 1
            resumen['eventos_procesados'].append(id_evento)
        resumen['limite_alcanzado'] = max_eventos is not None and resumen['procesados'] >= max_eventos
        try:
            resumen['pendientes_observados'] = db.outbox.count_documents({'procesado': False})
        except PyMongoError as error:
            resumen['fallidos'].append(diagnostico(None, error_mongo(error),
                                                   'No se pudieron contar los pendientes al finalizar.'))
        if resumen['fallidos']:
            resumen['estado'] = 'error'
        elif resumen['limite_alcanzado']:
            resumen['estado'] = 'limite_alcanzado'
        elif resumen['pendientes_observados'] > 0:
            resumen['estado'] = 'pendientes_observados'
    return resumen
