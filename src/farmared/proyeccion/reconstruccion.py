"""Reconstrucción administrativa sin eliminación automática de nodos."""

from neo4j import READ_ACCESS
from neo4j.exceptions import DriverError, Neo4jError
from pymongo.errors import PyMongoError

from farmared.errores import CodigoError, ErrorDominio
from farmared.grafo import preparar_grafo
from farmared.grafo.mapeos import ETIQUETAS
from farmared.grafo.proyecciones import proyectar_documentos
from farmared.proyeccion.exclusion import exclusion
from farmared.proyeccion.fuente import estado_esperado, leer_fuente
from farmared.proyeccion.verificacion import CAMPOS_ITEM, CAMPOS_NODO, TIPOS, comparar, leer_grafo


def _validar_destino(tx, esperado, confirmar_actualizacion):
    # Inspección completa: no se asume que todo lo que hay en la base sea nuestro.
    nodos = tx.run('MATCH (n) RETURN labels(n) AS etiquetas, n.id AS id, properties(n) AS propiedades').data()
    for fila in nodos:
        if (len(fila['etiquetas']) != 1 or fila['etiquetas'][0] not in ETIQUETAS.values()
                or not isinstance(fila['id'], str)
                or (fila['etiquetas'][0], fila['id']) not in esperado['nodos']):
            raise ErrorDominio('DESTINO_NO_AISLADO',
                               'Hay nodos ajenos, sobrantes o sin identidad: usar otro destino vacío y aislado.')
        if fila['propiedades'].keys() - set(CAMPOS_NODO[fila['etiquetas'][0]]):
            raise ErrorDominio('DESTINO_NO_AISLADO', 'Hay propiedades de nodos ajenas al modelo; usar otro destino.')
    if tx.run('MATCH ()-[r]->() WHERE NOT type(r) IN $tipos RETURN count(r) AS n', tipos=TIPOS).single()['n']:
        raise ErrorDominio('DESTINO_NO_AISLADO', 'El destino contiene relaciones ajenas; no se modificó.')
    if tx.run(
        "MATCH ()-[r]->() WHERE any(k IN keys(r) WHERE NOT k IN "
        "CASE WHEN type(r) = 'CONTIENE' THEN $campos ELSE [] END) RETURN count(r) AS n",
        campos=list(CAMPOS_ITEM),
    ).single()['n']:
        raise ErrorDominio('DESTINO_NO_AISLADO', 'Hay propiedades de relaciones ajenas; no se modificaron.')
    for restriccion in tx.run('SHOW CONSTRAINTS').data():
        if not (restriccion['entityType'] == 'NODE' and restriccion['type'] == 'UNIQUENESS'
                and len(restriccion['labelsOrTypes']) == 1
                and restriccion['labelsOrTypes'][0] in ETIQUETAS.values()
                and restriccion['properties'] == ['id']):
            raise ErrorDominio('DESTINO_NO_AISLADO', 'Hay restricciones ajenas; no se eliminan ni reemplazan.')
    if nodos and confirmar_actualizacion is not True:
        raise ErrorDominio('ACTUALIZACION_NO_CONFIRMADA',
                           'El destino no está vacío; confirmar explícitamente la actualización de propiedades y relaciones.')


def _reconstruir_tx(tx, documentos, esperado, confirmar_actualizacion):
    _validar_destino(tx, esperado, confirmar_actualizacion)
    proyectar_documentos(tx, documentos)
    informe = comparar(esperado, leer_grafo(tx))
    if not informe['equivalente']:
        raise ErrorDominio('VERIFICACION_FALLIDA', 'El resultado difiere del snapshot fuente; se revierte la transacción.')
    return informe


def reconstruir_grafo(db, driver, lock_path, *, confirmar_entorno_aislado=False,
                       confirmar_escrituras_pausadas=False, confirmar_actualizacion_existente=False) -> dict:
    """Reconstruye todo el estado en memoria y una única transacción de datos Neo4j.

    Sin borrado de nodos ni modificación de MongoDB/outbox. Solo habilitar el destino
    administrativo para consultas si el resultado dice habilitable=True. El DDL de
    restricciones es incremental y no integra la transacción de datos. No cierra db/driver.
    """
    if confirmar_entorno_aislado is not True or confirmar_escrituras_pausadas is not True:
        raise ErrorDominio(CodigoError.VALIDACION, 'Confirmar entorno aislado y escrituras de negocio pausadas.')
    if type(confirmar_actualizacion_existente) is not bool:
        raise ErrorDominio(CodigoError.VALIDACION, 'confirmar_actualizacion_existente debe ser booleano.')
    resumen = dict(estado='error', habilitable=False, recuperable=True,
                   precondiciones=dict(entorno_aislado_confirmado=True, escrituras_pausadas_confirmadas=True,
                                       actualizacion_existente_confirmada=confirmar_actualizacion_existente,
                                       exclusion_compartida=True),
                   fase='lectura_fuente', verificacion=None, error=None, mongo_modificado=False,
                   outbox_modificada=False, commit_neo4j='no_confirmado')
    with exclusion(lock_path):
        try:
            documentos = leer_fuente(db)
            esperado = estado_esperado(documentos)
            resumen['fase'] = 'validacion_destino'
            with driver.session(default_access_mode=READ_ACCESS) as sesion:
                sesion.execute_read(_validar_destino, esperado, confirmar_actualizacion_existente)
            resumen['fase'] = 'restricciones'
            preparar_grafo(driver)
            resumen['fase'] = 'proyeccion_y_verificacion'
            with driver.session() as sesion:
                informe = sesion.execute_write(_reconstruir_tx, documentos, esperado, confirmar_actualizacion_existente)
            resumen.update(estado='verificada', habilitable=True, recuperable=False, fase='finalizada',
                           verificacion=informe, commit_neo4j='confirmado')
        except ErrorDominio as error:
            resumen['error'] = dict(codigo=error.codigo, causa=error.mensaje)
        except (PyMongoError, DriverError, Neo4jError) as error:
            resumen['error'] = dict(codigo=type(error).__name__,
                                   causa='Falló un motor; no habilitar el destino. Corregir y repetir en el mismo entorno aislado.')
    return resumen
