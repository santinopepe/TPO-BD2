"""Carga solo MongoDB; el grafo se verifica mediante la sincronización de D."""

import argparse
import json
from dataclasses import replace

from farmared.carga.modelos import ErrorDatasets
from farmared.carga.mongo import cargar_mongo
from farmared.carga.validacion import rutas_desde_directorios
from farmared.cli.salidas import resumen_carga
from farmared.config import Config
from farmared.conexiones import obtener_mongo


def ejecutar(args: argparse.Namespace) -> int:
    db = obtener_mongo(replace(Config.from_env(), mongo_db=args.base))
    try:
        try:
            resultado = cargar_mongo(db, rutas_desde_directorios(*args.directorio))
        except ErrorDatasets as error:
            print(json.dumps(error.resumen(), ensure_ascii=False))
            return 1
        print(json.dumps(resumen_carga(db.name, resultado), ensure_ascii=False))
        return 0
    finally:
        db.client.close()
