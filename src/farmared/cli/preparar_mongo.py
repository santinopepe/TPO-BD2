"""Inicialización explícita de la base MongoDB; el setup completo sigue pendiente."""

import argparse
import json
from dataclasses import replace

from farmared.config import Config
from farmared.conexiones import obtener_mongo
from farmared.esquema.base_mongo import VALIDADORES, preparar_mongo_base


def ejecutar(args: argparse.Namespace) -> int:
    db = obtener_mongo(replace(Config.from_env(), mongo_db=args.base))
    try:
        preparar_mongo_base(db)
        print(json.dumps({"base": db.name, "esquema": "listo", "colecciones": list(VALIDADORES)}, ensure_ascii=False))
    finally:
        db.client.close()
    return 0
