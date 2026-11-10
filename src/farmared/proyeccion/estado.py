"""Contrato outbox, confirmación condicional y diagnósticos sin datos fuente."""

from collections.abc import Mapping
from datetime import datetime
from typing import get_args

from pymongo.errors import ConnectionFailure

from farmared.contratos import ColeccionProyectada
from farmared.errores import ErrorDominio


class ErrorEvento(ErrorDominio):
    def __init__(self, id_evento, codigo, mensaje):
        self.id_evento = id_evento if isinstance(id_evento, str) else None
        super().__init__(codigo, mensaje)


def validar_evento(evento):
    id = evento.get('_id')
    def invalido():
        return ErrorEvento(id, 'EVENTO_INVALIDO', 'Outbox no respeta _id, afectadas, procesado y creado_en.')
    if not isinstance(id, str) or not id.strip() or evento.get('procesado') is not False:
        raise invalido()
    if not isinstance(evento.get('creado_en'), datetime):
        raise invalido()
    afectadas = evento.get('afectadas')
    if not isinstance(afectadas, list) or not afectadas:
        raise invalido()
    claves = []
    for afectada in afectadas:
        if not isinstance(afectada, Mapping):
            raise invalido()
        coleccion, identificador = afectada.get('coleccion'), afectada.get('id')
        if (coleccion not in get_args(ColeccionProyectada)
                or not isinstance(identificador, str) or not identificador.strip()):
            raise invalido()
        claves.append((coleccion, identificador))
    if len(claves) != len(set(claves)):
        raise invalido()
    return claves


def confirmar_evento(db, id_evento):
    resultado = db.outbox.update_one({'_id': id_evento, 'procesado': False},
                                     {'$set': {'procesado': True}})
    if not resultado.acknowledged or resultado.matched_count != 1 or resultado.modified_count != 1:
        raise ErrorEvento(id_evento, 'OUTBOX_CONFIRMACION',
                          'No se confirmó la transición pendiente → procesado del evento específico.')


def error_mongo(error):
    return ('MONGO_CONEXION' if isinstance(error, ConnectionFailure) else 'MONGO_LECTURA')


def diagnostico(id_evento, codigo, causa, *, neo4j_confirmado=False):
    return dict(id_evento=id_evento, codigo=codigo, causa=causa, neo4j_confirmado=neo4j_confirmado)
