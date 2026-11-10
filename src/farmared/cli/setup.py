"""Bootstrap de A disponible; la integración C/D requiere sus módulos reales."""

import argparse
import json
import sys
from dataclasses import replace

from farmared.config import Config

PENDIENTES = [
    {"responsable": "C", "interfaz": "preparar_consultas_mongo(db)"},
    {"responsable": "D", "interfaz": "preparar_grafo(driver)"},
    {"responsable": "D", "interfaz": "sincronizar(db, driver, lock_path)"},
]


def ejecutar(args: argparse.Namespace) -> int:
    config = replace(Config.from_env(), mongo_db=args.base)
    if not args.solo_mongo:
        print(json.dumps({
            "base": config.mongo_db, "setup": "pendiente_integracion", "alcance": "completo",
            "pendientes": PENDIENTES, "escrituras": 0, "proyeccion": "no_comprobada",
        }, ensure_ascii=False))
        print("NO_IMPLEMENTADO: setup completo requiere integrar los módulos de Persona C y Persona D. "
              "Usar --solo-mongo para ejecutar únicamente la carga de A.", file=sys.stderr)
        return 3

    # La ruta pendiente no importa drivers ni abre conexiones.
    from farmared.carga.modelos import ErrorDatasets
    from farmared.carga.mongo import cargar_mongo
    from farmared.carga.validacion import rutas_desde_directorios, validar_datasets
    from farmared.cli.salidas import resumen_carga
    from farmared.conexiones import obtener_mongo

    rutas = rutas_desde_directorios(*args.directorio)
    try:
        validar_datasets(rutas)  # También rechaza fuentes inválidas antes de conectar.
    except ErrorDatasets as error:
        print(json.dumps(error.resumen(), ensure_ascii=False))
        return 1
    db = obtener_mongo(config)
    try:
        try:
            resultado = cargar_mongo(db, rutas)  # Revalida los bytes que efectivamente carga.
        except ErrorDatasets as error:
            print(json.dumps(error.resumen(), ensure_ascii=False))
            return 1
        print(json.dumps({
            **resumen_carga(db.name, resultado), "setup": "mongo_listo", "alcance": "solo_mongo",
            "pendientes": PENDIENTES,
        }, ensure_ascii=False))
        return 0
    finally:
        db.client.close()
