"""Comparación de contenido, tipos y multiplicidades de la proyección."""

from collections import defaultdict
from contextlib import nullcontext
from datetime import date, datetime

from neo4j import READ_ACCESS
from neo4j.time import Date

from farmared.grafo.mapeos import CAMPOS, ETIQUETAS, RELACIONES
from farmared.proyeccion.exclusion import exclusion
from farmared.proyeccion.fuente import estado_esperado, leer_fuente

TIPOS = sorted({'CONTIENE'} | {t for relaciones in RELACIONES.values() for t in relaciones})
CAMPOS_NODO = {ETIQUETAS[c]: ('id', *campos) for c, campos in CAMPOS.items()}
CAMPOS_ITEM = ('id_detalle', 'orden', 'cantidad', 'precio_unit', 'subtotal', 'nombre_al_vender')


def leer_grafo(tx):
    nodos = tx.run(
        'MATCH (n) WHERE any(e IN labels(n) WHERE e IN $etiquetas) '
        'RETURN labels(n) AS etiquetas, n.id AS id, properties(n) AS propiedades, elementId(n) AS elemento',
        etiquetas=list(ETIQUETAS.values()),
    ).data()
    relaciones = tx.run(
        'MATCH (a)-[r]->(b) WHERE type(r) IN $tipos '
        'OR any(e IN labels(a) + labels(b) WHERE e IN $etiquetas) '
        'RETURN labels(a) AS origen_etiquetas, a.id AS origen_id, elementId(a) AS origen_elemento, '
        'labels(b) AS destino_etiquetas, b.id AS destino_id, elementId(b) AS destino_elemento, type(r) AS tipo, '
        'properties(r) AS propiedades, elementId(r) AS elemento',
        tipos=TIPOS, etiquetas=list(ETIQUETAS.values()),
    ).data()
    return nodos, relaciones


def _canonico(valor):
    # Comparación estricta: True no equivale a 1; fecha no equivale a texto/timestamp.
    if isinstance(valor, Date):
        try:
            valor = valor.to_native()
        except (ValueError, OverflowError):
            return ('fecha_fuera_de_rango', str(valor))
    if type(valor) is date:
        return ('date', valor.isoformat())
    if isinstance(valor, datetime):
        return ('datetime', valor.isoformat())
    return (type(valor).__name__, repr(valor))


def _identificador(valor, elemento):
    return valor if isinstance(valor, str) else '@elemento:' + elemento


def _etiqueta(etiquetas):
    return '|'.join(sorted(etiquetas))


def _localizar_relacion(clave):
    tipo, origen, id_origen, destino, id_destino, detalle = clave
    return dict(relacion=tipo, origen=dict(etiqueta=origen, id=id_origen),
                destino=dict(etiqueta=destino, id=id_destino), id_detalle=detalle)


def comparar(esperado, observado):
    """Diagnóstico sin valores personales: IDs, campo afectado y clase de diferencia."""
    filas_nodos, filas_relaciones = observado
    diferencias, nodos, relaciones = [], defaultdict(list), defaultdict(list)
    for fila in filas_nodos:
        etiqueta = _etiqueta(fila['etiquetas'])
        identificador = _identificador(fila['id'], fila['elemento'])
        clave = (etiqueta, identificador)
        nodos[clave].append(fila['propiedades'])
        if not isinstance(fila['id'], str):
            diferencias.append(dict(tipo='nodo_sin_id', etiqueta=etiqueta, elemento=fila['elemento']))
    for fila in filas_relaciones:
        origen = _identificador(fila['origen_id'], fila.get('origen_elemento', fila['elemento'] + '-origen'))
        destino = _identificador(fila['destino_id'], fila.get('destino_elemento', fila['elemento'] + '-destino'))
        detalle = None
        if fila['tipo'] == 'CONTIENE':
            valor = fila['propiedades'].get('id_detalle')
            detalle = _identificador(valor, fila['elemento'] + '-detalle')
            if not isinstance(valor, str):
                diferencias.append(dict(tipo='detalle_id_invalido', elemento=fila['elemento'],
                                        origen=dict(etiqueta=_etiqueta(fila['origen_etiquetas']), id=origen)))
        clave = (fila['tipo'], _etiqueta(fila['origen_etiquetas']), origen,
                 _etiqueta(fila['destino_etiquetas']), destino, detalle)
        relaciones[clave].append(fila['propiedades'])
    for clave in sorted(esperado['nodos'].keys() | nodos.keys(), key=repr):
        local = dict(etiqueta=clave[0], id=clave[1])
        if clave not in esperado['nodos']:
            diferencias.append(dict(tipo='nodo_sobrante', **local))
            continue
        if clave not in nodos:
            diferencias.append(dict(tipo='nodo_faltante', **local))
            continue
        if len(nodos[clave]) > 1:
            diferencias.append(dict(tipo='nodo_duplicado', cantidad=len(nodos[clave]), **local))
        for props in nodos[clave]:
            for campo in sorted(props.keys() - set(CAMPOS_NODO[clave[0]])):
                diferencias.append(dict(tipo='propiedad_sobrante', campo=campo, **local))
            for campo in CAMPOS_NODO[clave[0]]:
                if _canonico(esperado['nodos'][clave].get(campo)) != _canonico(props.get(campo)):
                    diferencias.append(dict(tipo='propiedad_diferente', campo=campo, **local))
    for clave in sorted(esperado['relaciones'].keys() | relaciones.keys(), key=repr):
        local = _localizar_relacion(clave)
        if clave not in esperado['relaciones']:
            diferencias.append(dict(tipo='relacion_sobrante', **local))
        elif clave not in relaciones:
            diferencias.append(dict(tipo='relacion_faltante', **local))
        if len(relaciones.get(clave, ())) > 1:
            diferencias.append(dict(tipo='detalle_duplicado' if clave[0] == 'CONTIENE' else 'relacion_duplicada',
                                    cantidad=len(relaciones[clave]), **local))
        if clave in esperado['relaciones']:
            for props in relaciones.get(clave, ()):
                permitidos = set(CAMPOS_ITEM) if clave[0] == 'CONTIENE' else set()
                for campo in sorted(props.keys() - permitidos):
                    diferencias.append(dict(tipo='propiedad_relacion_sobrante', campo=campo, **local))
                for campo in CAMPOS_ITEM if clave[0] == 'CONTIENE' else ():
                    if _canonico(esperado['relaciones'][clave].get(campo)) != _canonico(props.get(campo)):
                        diferencias.append(dict(tipo='propiedad_relacion_diferente', campo=campo, **local))
    # La identidad lógica de un detalle es venta/id_detalle, también si cambió el producto.
    detalles = defaultdict(int)
    for clave, filas in relaciones.items():
        if clave[0] == 'CONTIENE':
            detalles[(clave[1], clave[2], clave[5])] += len(filas)
    for (etiqueta, id, detalle), cantidad in detalles.items():
        if cantidad > 1 and not any(d['tipo'] == 'detalle_duplicado' and d['origen']['id'] == id
                                    and d['id_detalle'] == detalle for d in diferencias):
            diferencias.append(dict(tipo='detalle_duplicado', relacion='CONTIENE',
                                    origen=dict(etiqueta=etiqueta, id=id), id_detalle=detalle, cantidad=cantidad))
    return dict(equivalente=not diferencias, diferencias=diferencias,
                conteos=dict(nodos_esperados=len(esperado['nodos']), nodos_observados=len(filas_nodos),
                             relaciones_esperadas=len(esperado['relaciones']), relaciones_observadas=len(filas_relaciones)))


def verificar_proyeccion(db, driver, lock_path=None, *, confirmar_escrituras_pausadas=False) -> dict:
    """Compara contenido; sin período estable declarado es solo diagnóstico puntual.

    lock_path opcional coordina con sincronizar; no prueba ausencia de escritores.
    Los errores de fuente o de motores se propagan, nunca equivalen a 'equivalente'.
    """
    with exclusion(lock_path) if lock_path is not None else nullcontext():
        esperado = estado_esperado(leer_fuente(db))
        with driver.session(default_access_mode=READ_ACCESS) as sesion:
            informe = sesion.execute_read(lambda tx: comparar(esperado, leer_grafo(tx)))
    informe['precondiciones'] = dict(escrituras_pausadas_confirmadas=confirmar_escrituras_pausadas is True,
                                    exclusion_compartida=lock_path is not None)
    informe['alcance'] = ('estado_estable_declarado' if confirmar_escrituras_pausadas is True and lock_path is not None
                          else 'diagnostico_puntual')
    return informe
