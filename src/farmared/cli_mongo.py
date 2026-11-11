import argparse
import json
from dataclasses import replace
from datetime import datetime

from farmared.clock import SystemClock
from farmared.config import Config
from farmared.conexiones import obtener_mongo

COMANDOS_MONGO = {nombre: ("farmared.cli_mongo", "ejecutar") for nombre in ("q01", "q05", "q06", "q07", "q08", "q09")}


def registrar_comandos(subparsers) -> None:
    q01 = subparsers.add_parser("q01", help="Productos activos con todos los datos de su proveedor (MongoDB).")
    q01.add_argument("--base", required=True, help="Base MongoDB explícita.")
    q05 = subparsers.add_parser("q05", help="Farmacéuticos activos y cantidad de ventas no anuladas en los últimos 60 días (MongoDB).")
    q05.add_argument("--base", required=True, help="Base MongoDB explícita.")
    q06 = subparsers.add_parser("q06", help="Recetas prolongadas vigentes con dispensa anterior a hoy y datos del cliente (MongoDB).")
    q06.add_argument("--base", required=True, help="Base MongoDB explícita.")
    q07 = subparsers.add_parser("q07", help="Top 5 productos por unidades en ventas completadas (MongoDB).")
    q07.add_argument("--base", required=True, help="Base MongoDB explícita.")
    q08 = subparsers.add_parser("q08", help="Lotes con menos de 50 unidades, producto, proveedor y sucursal (MongoDB).")
    q08.add_argument("--base", required=True, help="Base MongoDB explícita.")
    q09 = subparsers.add_parser("q09", help="Ventas libres menores a $5000, excepto anuladas (MongoDB).")
    q09.add_argument("--base", required=True, help="Base MongoDB explícita.")


def _fecha_json(valor):
    if isinstance(valor, datetime):
        return valor.isoformat()
    raise TypeError(f"Tipo no serializable: {type(valor).__name__}")


def ejecutar(args: argparse.Namespace) -> int:
    parametros = ()
    if args.comando == "q01":
        from farmared.consultas.q01 import q01_productos_activos as consultar
    elif args.comando == "q05":
        from farmared.consultas.q05 import q05_ventas_por_farmaceutico as consultar
        parametros = (SystemClock(),)
    elif args.comando == "q06":
        from farmared.consultas.q06 import q06_recetas_prolongadas as consultar
        parametros = (SystemClock(),)
    elif args.comando == "q07":
        from farmared.consultas.q07 import q07_top_productos as consultar
    elif args.comando == "q08":
        from farmared.consultas.q08 import q08_lotes_stock_bajo as consultar
    else:
        from farmared.consultas.q09 import q09_ventas_libres as consultar

    db = obtener_mongo(replace(Config.from_env(), mongo_db=args.base))
    try:
        salida = {"consulta": args.comando, "base": db.name,
                  "resultados": consultar(db, *parametros)}
        print(json.dumps(salida, ensure_ascii=False, default=_fecha_json))
        return 0
    finally:
        db.client.close()
