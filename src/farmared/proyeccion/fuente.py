"""Lectura snapshot completa de las seis colecciones y representación esperada."""

from typing import get_args

from pymongo import ReadPreference
from pymongo.read_concern import ReadConcern

from farmared.contratos import ColeccionProyectada
from farmared.errores import CodigoError, ErrorDominio
from farmared.grafo.mapeos import ETIQUETAS, RELACIONES, mapear_documento

COLECCIONES = get_args(ColeccionProyectada)


def leer_fuente(db):
    """Materializa un snapshot de negocio; nunca lee/escribe outbox ni escribe MongoDB."""
    with db.client.start_session() as sesion:
        with sesion.start_transaction(read_concern=ReadConcern('snapshot'),
                                      read_preference=ReadPreference.PRIMARY):
            documentos = [(coleccion, doc) for coleccion in COLECCIONES
                          for doc in db[coleccion].find({}, session=sesion).sort('_id', 1)]
    return documentos


def estado_esperado(documentos):
    """Reutiliza el mapper; valida todas las referencias contra el snapshot completo."""
    mapas = [(coleccion, mapear_documento(coleccion, doc)) for coleccion, doc in documentos]
    nodos, relaciones = {}, {}
    for _, mapa in mapas:
        clave = (mapa['etiqueta'], mapa['propiedades']['id'])
        if clave in nodos:
            raise ErrorDominio(CodigoError.INTEGRIDAD, 'Identidad repetida en el snapshot fuente.')
        nodos[clave] = mapa['propiedades']
    for coleccion, mapa in mapas:
        identidad = (mapa['etiqueta'], mapa['propiedades']['id'])
        for tipo, (destino, _, entrante) in RELACIONES.get(coleccion, {}).items():
            referencia = mapa['referencias'][tipo]
            if referencia is None:
                continue
            extremo = (ETIQUETAS[destino], referencia)
            _exigir(nodos, extremo)
            origen, fin = (extremo, identidad) if entrante else (identidad, extremo)
            relaciones[(tipo, *origen, *fin, None)] = {}
        for item in mapa['items']:
            extremo = ('Producto', item['id_producto'])
            _exigir(nodos, extremo)
            relaciones[('CONTIENE', *identidad, *extremo, item['propiedades']['id_detalle'])] = item['propiedades']
    return dict(nodos=nodos, relaciones=relaciones)


def _exigir(nodos, extremo):
    if extremo not in nodos:
        raise ErrorDominio(CodigoError.INTEGRIDAD,
                           f'Dependencia ausente en el snapshot: {extremo[0]}/{extremo[1]}.')
