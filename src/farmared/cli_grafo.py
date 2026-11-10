"""Adaptador CLI de D: registro sin drivers y delegación a las APIs existentes."""

import argparse
from contextlib import ExitStack
from dataclasses import replace
from datetime import date
import json
from pathlib import Path

from farmared.config import Config
from farmared.conexiones import obtener_mongo, obtener_neo4j
from farmared.errores import CodigoError, ErrorDominio

COMANDOS_GRAFO = {nombre: ('farmared.cli_grafo', 'ejecutar') for nombre in
                  ('grafo-init', 'sync', 'grafo-verify', 'grafo-rebuild', 'q03', 'q04', 'q10')}


def _no_vacio(valor):
    if not valor.strip():
        raise argparse.ArgumentTypeError('Se requiere un identificador no vacío.')
    return valor


def _no_negativo(valor):
    try:
        entero = int(valor)
    except ValueError:
        raise argparse.ArgumentTypeError('Se requiere un entero no negativo.') from None
    if entero < 0:
        raise argparse.ArgumentTypeError('Se requiere un entero no negativo.')
    return entero


def registrar_comandos(subparsers):
    subparsers.add_parser('grafo-init', help='Asegura restricciones Neo4j sin cargar datos.')
    sync = subparsers.add_parser('sync', help='Consume outbox bajo demanda; consistencia eventual.')
    verify = subparsers.add_parser('grafo-verify', help='Compara contenido MongoDB–Neo4j; no corrige datos.')
    rebuild = subparsers.add_parser('grafo-rebuild', help='Reconstrucción administrativa en destino dedicado.')
    for parser in (sync, verify, rebuild):
        parser.add_argument('--base', required=True, type=_no_vacio, help='Base MongoDB explícita de origen.')
        parser.add_argument('--lock-path', type=_no_vacio, help='Archivo compartido del entorno; padre existente. '
                            'Por defecto ~/.farmared/sync.lock, común a los comandos D del usuario.')
    sync.add_argument('--max-eventos', type=_no_negativo, help='Límite opcional; 0 solo observa pendientes.')
    verify.add_argument('--confirmar-escrituras-pausadas', action='store_true',
                        help='Declara fuente estable; sin esta opción el resultado es diagnóstico y sale con 1.')
    rebuild.add_argument('--confirmar-entorno-aislado', action='store_true')
    rebuild.add_argument('--confirmar-escrituras-pausadas', action='store_true')
    rebuild.add_argument('--confirmar-sincronizador-pausado', action='store_true')
    rebuild.add_argument('--confirmar-actualizacion-existente', action='store_true',
                         help='Autoriza reemplazar propiedades/relaciones propias de un grafo existente.')
    q03 = subparsers.add_parser('q03', help='Historial completo de ventas y recetas en Neo4j.')
    q03.add_argument('--id-cliente', required=True, type=_no_vacio)
    subparsers.add_parser('q04', help='Clientes con más de una receta en Neo4j.')
    q10 = subparsers.add_parser('q10', help='Clientes atendidos por profesionales de una sucursal.')
    q10.add_argument('--id-sucursal', required=True, type=_no_vacio)


def _fecha_json(valor):
    if type(valor) is date:
        return valor.isoformat()
    raise TypeError(f'Tipo no serializable: {type(valor).__name__}')


def _mostrar(resultado):
    print(json.dumps(resultado, ensure_ascii=False, sort_keys=True, default=_fecha_json))


def _ruta_lock(args):
    if args.lock_path is not None:
        return Path(args.lock_path)
    # Una ruta fija por usuario: independiente del cwd, URI, alias o base MongoDB.
    directorio = Path.home() / '.farmared'
    directorio.mkdir(parents=True, exist_ok=True)
    return directorio / 'sync.lock'


def ejecutar(args: argparse.Namespace) -> int:
    comando = args.comando
    if comando == 'grafo-rebuild' and not (args.confirmar_entorno_aislado
            and args.confirmar_escrituras_pausadas and args.confirmar_sincronizador_pausado):
        raise ErrorDominio(CodigoError.VALIDACION,
                           'Confirmar entorno aislado, escrituras pausadas y sincronizador pausado antes de conectar.')
    config = Config.from_env()
    necesita_mongo = comando in ('sync', 'grafo-verify', 'grafo-rebuild')
    if necesita_mongo:
        config = replace(config, mongo_db=args.base)
        if config.mongo_db in {'admin', 'config', 'local'}:
            raise ErrorDominio(CodigoError.VALIDACION, 'Elegir una base de negocio, no una base interna MongoDB.')
    # Solo ejecutar el comando seleccionado importa los drivers y módulos D.
    from neo4j.exceptions import DriverError, Neo4jError
    from pymongo.errors import ConnectionFailure, PyMongoError
    try:
        with ExitStack() as recursos:
            if necesita_mongo:
                lock = _ruta_lock(args)
                db = obtener_mongo(config)
                recursos.callback(db.client.close)
            driver = recursos.enter_context(obtener_neo4j(config))
            if comando == 'grafo-init':
                from farmared.grafo import preparar_grafo
                preparar_grafo(driver)
                _mostrar(dict(comando=comando, esquema='listo'))
                return 0
            if comando in ('q03', 'q04', 'q10'):
                from importlib import import_module
                nombres = dict(q03='q03_historial', q04='q04_clientes_con_recetas', q10='q10_clientes_sucursal')
                funcion = getattr(import_module('farmared.consultas.' + comando), nombres[comando])
                parametros = ([args.id_cliente] if comando == 'q03' else
                              [args.id_sucursal] if comando == 'q10' else [])
                resultado = dict(consulta=comando, proyeccion='eventualmente_consistente',
                                 resultados=funcion(driver, *parametros))
                if comando == 'q03':
                    resultado['id_cliente'] = args.id_cliente
                elif comando == 'q10':
                    resultado['id_sucursal'] = args.id_sucursal
                _mostrar(resultado)
                return 0
            if comando == 'sync':
                from farmared.proyeccion import sincronizar
                resumen = sincronizar(db, driver, lock, max_eventos=args.max_eventos)
                _mostrar(dict(comando=comando, base=config.mongo_db, **resumen))
                return 1 if resumen['fallidos'] or resumen['estado'] == 'error' else 0
            if comando == 'grafo-verify':
                from farmared.proyeccion import verificar_proyeccion
                informe = verificar_proyeccion(db, driver, lock,
                    confirmar_escrituras_pausadas=args.confirmar_escrituras_pausadas)
                _mostrar(dict(comando=comando, base=config.mongo_db, **informe))
                return 0 if args.confirmar_escrituras_pausadas and informe['equivalente'] and informe['alcance'] == 'estado_estable_declarado' else 1
            if comando == 'grafo-rebuild':
                from farmared.proyeccion import reconstruir_grafo
                resultado = reconstruir_grafo(db, driver, lock,
                    confirmar_entorno_aislado=args.confirmar_entorno_aislado,
                    confirmar_escrituras_pausadas=args.confirmar_escrituras_pausadas,
                    confirmar_actualizacion_existente=args.confirmar_actualizacion_existente)
                resultado = {**resultado, 'sincronizador_pausado_confirmado': args.confirmar_sincronizador_pausado}
                _mostrar(dict(comando=comando, base=config.mongo_db, **resultado))
                return 0 if resultado['habilitable'] and resultado['estado'] == 'verificada' else 1
            raise ErrorDominio(CodigoError.VALIDACION, 'Comando de grafo desconocido.')
    except (DriverError, ConnectionFailure):
        raise ErrorDominio(CodigoError.CONEXION, 'Falló la conexión durante la operación de grafo.') from None
    except (Neo4jError, PyMongoError):
        raise ErrorDominio(CodigoError.INTEGRIDAD, 'El motor rechazó la operación de grafo; revisar permisos y estado.') from None
