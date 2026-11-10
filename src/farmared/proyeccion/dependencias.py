"""Resolución postorden de documentos completos dentro de una sesión MongoDB."""

from farmared.errores import ErrorDominio
from farmared.grafo.mapeos import RELACIONES, mapear_documento
from farmared.proyeccion.estado import ErrorEvento, validar_evento


def resolver_documentos(db, sesion, evento):
    """Lee cada identidad una vez, valida y devuelve dependencias antes de sus raíces."""
    raices = validar_evento(evento)
    visitando, resueltas, documentos = set(), set(), []

    def visitar(coleccion, id, *, raiz=False):
        clave = (coleccion, id)
        if clave in visitando:
            raise ErrorEvento(evento['_id'], 'CICLO_DEPENDENCIAS', 'Se detectó un ciclo de referencias.')
        if clave in resueltas:
            return
        visitando.add(clave)
        doc = db[coleccion].find_one({'_id': id}, session=sesion)
        if doc is None:
            codigo = 'DOCUMENTO_INEXISTENTE' if raiz else 'DEPENDENCIA_INEXISTENTE'
            raise ErrorEvento(evento['_id'], codigo, f'No existe {coleccion}/{id}.')
        try:
            mapa = mapear_documento(coleccion, doc)
        except ErrorDominio:
            raise ErrorEvento(evento['_id'], 'DOCUMENTO_INVALIDO',
                              f'Campos de proyección inválidos en {coleccion}/{id}.') from None
        if mapa['propiedades']['id'] != id:
            raise ErrorEvento(evento['_id'], 'DOCUMENTO_INVALIDO', 'La identidad fuente no coincide con la referencia.')
        for tipo, (destino, _, _) in RELACIONES.get(coleccion, {}).items():
            referencia = mapa['referencias'][tipo]
            if referencia is not None:
                visitar(destino, referencia)
        for item in mapa['items']:
            visitar('productos', item['id_producto'])
        visitando.remove(clave)
        resueltas.add(clave)
        documentos.append((coleccion, doc))

    for coleccion, id in raices:
        visitar(coleccion, id, raiz=True)
    return documentos
