import argparse
import json
from dataclasses import replace
from datetime import datetime

from farmared.config import Config
from farmared.conexiones import obtener_mongo

COMANDOS_MONGO = {nombre: ("farmared.cli_mongo", "ejecutar") for nombre in ("q01", "q09")}


def registrar_comandos(subparsers) -> None:
    q01 = subparsers.add_parser("q01", help="Productos activos con todos los datos de su proveedor (MongoDB).")
    q01.add_argument("--base", required=True, help="Base MongoDB explícita.")
    q09 = subparsers.add_parser("q09", help="Ventas libres menores a $5000, excepto anuladas (MongoDB).")
    q09.add_argument("--base", required=True, help="Base MongoDB explícita.")


def _fecha_json(valor):
    if isinstance(valor, datetime):
        return valor.isoformat()
    raise TypeError(f"Tipo no serializable: {type(valor).__name__}")


def ejecutar(args: argparse.Namespace) -> int:
    if args.comando == "q01":
        from farmared.consultas.q01 import q01_productos_activos as consultar
    else:
        from farmared.consultas.q09 import q09_ventas_libres as consultar

    db = obtener_mongo(replace(Config.from_env(), mongo_db=args.base))
    try:
        salida = {"consulta": args.comando, "base": db.name,
                  "resultados": consultar(db)}
        print(json.dumps(salida, ensure_ascii=False, default=_fecha_json))
        return 0
    finally:
        db.client.close()
