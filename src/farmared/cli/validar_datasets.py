"""Valida fuentes sin configuración ni conexiones a motores."""

import argparse
import json

from farmared.carga.modelos import ErrorDatasets
from farmared.carga.validacion import rutas_desde_directorios, validar_datasets


def ejecutar(args: argparse.Namespace) -> int:
    try:
        resultado = validar_datasets(rutas_desde_directorios(*args.directorio))
    except ErrorDatasets as error:
        print(json.dumps(error.resumen(), ensure_ascii=False))
        return 1
    print(json.dumps(resultado.resumen(), ensure_ascii=False))
    return 0
