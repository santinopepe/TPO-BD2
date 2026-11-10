"""Vista previa o reset confirmado de una base de demo explícita."""

import argparse
import json
import sys
from dataclasses import replace

from farmared.config import Config
from farmared.demo import resetear_demo_mongo


def ejecutar(args: argparse.Namespace) -> int:
    config = replace(Config.from_env(), mongo_db=args.base)
    def anunciar(destino):
        print(json.dumps({"reset_confirmado": destino, "accion": "eliminar_base_completa"},
                         ensure_ascii=False), file=sys.stderr, flush=True)

    resultado = resetear_demo_mongo(config, confirmar_base=args.confirmar_base, antes_de_borrar=anunciar)
    print(json.dumps(resultado, ensure_ascii=False))
    return 0
